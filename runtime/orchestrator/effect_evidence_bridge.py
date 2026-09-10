from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .tool_authorization import (
    ToolAuthorizationContract,
    owned_scope_digest,
    validate_contract,
)
from .worker_authority import GovernedEffectEvidence

WRITE_OPERATION = "PROJECT_OWNED_FILE_WRITE"


class EffectEvidenceBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EffectEvidenceBridgeError(
            "tool effect evidence is not canonicalizable",
            reason_taxonomy="EFFECT_EVIDENCE_MALFORMED",
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EffectEvidenceBridgeError(
            "tool effect evidence is missing or unsafe",
            reason_taxonomy="EFFECT_EVIDENCE_MISSING",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EffectEvidenceBridgeError(
            "tool effect evidence is malformed",
            reason_taxonomy="EFFECT_EVIDENCE_MALFORMED",
        ) from exc
    if not isinstance(value, dict):
        raise EffectEvidenceBridgeError(
            "tool effect evidence is malformed",
            reason_taxonomy="EFFECT_EVIDENCE_MALFORMED",
        )
    return value


def _validate_identity(
    identity: Mapping[str, Any],
    *,
    active_write_contract: ToolAuthorizationContract,
    expected_owned_scope: tuple[str, ...],
) -> None:
    expected = {
        "operation_class_id": WRITE_OPERATION,
        "worker_task_id": active_write_contract.worker_task_id,
        "project_id": active_write_contract.project_id,
        "gate_id": active_write_contract.gate_id,
        "lv_id": active_write_contract.lv_id,
        "run_id": active_write_contract.run_id,
        "plan_digest": active_write_contract.canonical_plan_sha256,
        "requirement_digest": active_write_contract.requirement_digest,
        "package_digest": active_write_contract.package_binding_sha256,
        "owned_scope_sha256": owned_scope_digest(expected_owned_scope),
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise EffectEvidenceBridgeError(
            "tool effect identity drifted from ACTIVE WRITE contract",
            reason_taxonomy="EFFECT_EVIDENCE_CONTRACT_BINDING_DRIFT",
        )


def collect_governed_write_effect_evidence(
    journal_root: str | Path,
    *,
    active_write_contract: ToolAuthorizationContract,
    expected_owned_scope: Sequence[str],
) -> tuple[GovernedEffectEvidence, ...]:
    validate_contract(active_write_contract)
    if (
        active_write_contract.contract_status != "ACTIVE"
        or active_write_contract.operation_class_id != WRITE_OPERATION
    ):
        raise EffectEvidenceBridgeError(
            "ACTIVE PROJECT_OWNED_FILE_WRITE contract is required",
            reason_taxonomy="EFFECT_EVIDENCE_WRITE_AUTHORITY_INVALID",
        )

    owned_scope = tuple(expected_owned_scope)
    if not owned_scope or len(owned_scope) != len(set(owned_scope)):
        raise EffectEvidenceBridgeError(
            "expected owned scope is missing or ambiguous",
            reason_taxonomy="EFFECT_EVIDENCE_SCOPE_INVALID",
        )
    if owned_scope_digest(owned_scope) != active_write_contract.owned_scope_sha256:
        raise EffectEvidenceBridgeError(
            "owned scope drifted from ACTIVE WRITE contract",
            reason_taxonomy="EFFECT_EVIDENCE_SCOPE_DRIFT",
        )

    root = Path(journal_root)
    if not root.is_dir() or root.is_symlink():
        raise EffectEvidenceBridgeError(
            "tool effect journal is missing or unsafe",
            reason_taxonomy="EFFECT_EVIDENCE_MISSING",
        )

    current_identity = {
        "worker_task_id": active_write_contract.worker_task_id,
        "project_id": active_write_contract.project_id,
        "gate_id": active_write_contract.gate_id,
        "lv_id": active_write_contract.lv_id,
        "run_id": active_write_contract.run_id,
    }

    evidence: list[GovernedEffectEvidence] = []
    for intent_path in sorted(root.glob("*.intent.json")):
        intent = _read_json(intent_path)
        identity = intent.get("identity")
        operation = intent.get("operation")
        if operation is None and isinstance(identity, Mapping):
            operation = identity.get("operation_class_id")
        if operation != WRITE_OPERATION:
            continue

        if not isinstance(identity, Mapping):
            raise EffectEvidenceBridgeError(
                "WRITE intent identity is malformed",
                reason_taxonomy="EFFECT_EVIDENCE_INTENT_INVALID",
            )
        if any(identity.get(key) != value for key, value in current_identity.items()):
            continue

        if intent.get("schema_version") != "orchestration.tool-effect-intent.v2":
            raise EffectEvidenceBridgeError(
                "current WRITE intent is not v2 evidence",
                reason_taxonomy="EFFECT_EVIDENCE_SCHEMA_UNSUPPORTED",
            )

        effect_id = intent.get("effect_id")
        scope_ref = intent.get("scope_ref")
        if (
            not isinstance(effect_id, str)
            or not effect_id
            or intent_path.name != f"{effect_id}.intent.json"
            or not isinstance(scope_ref, str)
            or scope_ref not in owned_scope
            or intent.get("authorization_status") != "AUTHORIZED"
        ):
            raise EffectEvidenceBridgeError(
                "WRITE intent binding is invalid",
                reason_taxonomy="EFFECT_EVIDENCE_INTENT_INVALID",
            )

        _validate_identity(
            identity,
            active_write_contract=active_write_contract,
            expected_owned_scope=owned_scope,
        )

        receipt_path = root / f"{effect_id}.receipt.json"
        if not receipt_path.exists():
            raise EffectEvidenceBridgeError(
                "WRITE intent has no durable receipt",
                reason_taxonomy="EFFECT_EVIDENCE_RECOVERY_AMBIGUOUS",
            )
        receipt = _read_json(receipt_path)
        intent_digest = _digest(intent)
        receipt_digest = _digest(receipt)

        if (
            receipt.get("schema_version") != "orchestration.tool-effect-receipt.v2"
            or receipt.get("effect_id") != effect_id
            or receipt.get("intent_digest") != intent_digest
            or receipt.get("authoritative_completion_binding") != _digest(dict(identity))
            or receipt.get("execution_status") not in {"COMPLETED", "FAILED"}
            or receipt.get("security_status") not in {"PASS", "BLOCK"}
        ):
            raise EffectEvidenceBridgeError(
                "WRITE receipt does not exactly bind its intent",
                reason_taxonomy="EFFECT_EVIDENCE_RECEIPT_DRIFT",
            )

        evidence.append(
            GovernedEffectEvidence(
                effect_id=effect_id,
                operation=WRITE_OPERATION,
                scope_ref=scope_ref,
                intent_digest=intent_digest,
                receipt_intent_digest=str(receipt["intent_digest"]),
                receipt_digest=receipt_digest,
                authorized=True,
                mutation_performed=receipt["execution_status"] == "COMPLETED",
                security_passed=receipt["security_status"] == "PASS",
                evidence_refs=(
                    f"tool-effect://{effect_id}/intent#{intent_digest}",
                    f"tool-effect://{effect_id}/receipt#{receipt_digest}",
                ),
            )
        )

    return tuple(sorted(evidence, key=lambda item: item.effect_id))


def verify_single_governed_write_effect(
    journal_root: str | Path,
    *,
    active_write_contract: ToolAuthorizationContract,
    expected_owned_scope: Sequence[str],
    expected_scope_ref: str,
) -> dict[str, Any]:
    """Independent bounded verifier for the proof97 single-WRITE invariant."""
    try:
        evidence = collect_governed_write_effect_evidence(
            journal_root,
            active_write_contract=active_write_contract,
            expected_owned_scope=expected_owned_scope,
        )
    except EffectEvidenceBridgeError as exc:
        return {
            "status": "FAIL",
            "verifier": "single_governed_write_effect.v1",
            "reason_taxonomy": exc.reason_taxonomy,
            "effect_count": 0,
        }
    matching = [
        item
        for item in evidence
        if (
            item.operation == WRITE_OPERATION
            and item.scope_ref == expected_scope_ref
            and item.authorized
            and item.mutation_performed
            and item.security_passed
            and item.intent_receipt_consistent
        )
    ]
    if len(evidence) != 1 or len(matching) != 1:
        return {
            "status": "FAIL",
            "verifier": "single_governed_write_effect.v1",
            "reason_taxonomy": "EFFECT_EVIDENCE_COUNT_OR_SCOPE_MISMATCH",
            "effect_count": len(evidence),
            "matching_effect_count": len(matching),
        }
    item = matching[0]
    return {
        "status": "PASS",
        "verifier": "single_governed_write_effect.v1",
        "reason_taxonomy": "SINGLE_GOVERNED_WRITE_EFFECT_VERIFIED",
        "effect_count": 1,
        "effect_id": item.effect_id,
        "evidence_refs": list(item.evidence_refs),
    }

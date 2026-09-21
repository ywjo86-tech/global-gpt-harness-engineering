from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .tool_authorization import (
    ToolAuthorizationContract,
    owned_scope_digest,
    validate_contract,
)
from .worker_authority import GovernedEffectEvidence
from .gate_continuation_contract import GateContinuationContract

WRITE_OPERATION = "PROJECT_OWNED_FILE_WRITE"
_SENSITIVE_SCOPE_PARTS = frozenset({".git", ".env", "auth.json", "credentials", "credentials.json"})


class EffectEvidenceBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


def _scope_ref_within_owned_scope(scope_ref: str, owned_scope: tuple[str, ...]) -> bool:
    if scope_ref in owned_scope:
        return True
    if not scope_ref or "\\" in scope_ref:
        return False
    candidate = PurePosixPath(scope_ref)
    lowered = {part.lower() for part in candidate.parts}
    if (candidate.is_absolute() or ".." in candidate.parts or not candidate.parts
            or candidate.as_posix() != scope_ref or lowered.intersection(_SENSITIVE_SCOPE_PARTS)):
        return False
    for scope in owned_scope:
        if not isinstance(scope, str) or not scope.endswith("/"):
            continue
        base = PurePosixPath(scope[:-1])
        try:
            child = candidate.relative_to(base)
        except ValueError:
            continue
        if child.parts:
            return True
    return False


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
            or not _scope_ref_within_owned_scope(scope_ref, owned_scope)
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


@dataclass(frozen=True, slots=True)
class EffectReconciliationEvidence:
    status: str
    reason_taxonomy: str
    retry_disposition: str
    effect_count: int
    effect_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evidence_sha256: str


def _reconciliation_evidence(
    *, status: str, reason_taxonomy: str, retry_disposition: str,
    effect_ids: Sequence[str] = (), evidence_refs: Sequence[str] = (),
) -> EffectReconciliationEvidence:
    ids = tuple(sorted(str(item) for item in effect_ids))
    refs = tuple(sorted(str(item) for item in evidence_refs))
    unsigned = {
        "schema_version": "orchestration.effect-reconciliation-evidence.v1",
        "status": status,
        "reason_taxonomy": reason_taxonomy,
        "retry_disposition": retry_disposition,
        "effect_count": len(ids),
        "effect_ids": list(ids),
        "evidence_refs": list(refs),
    }
    return EffectReconciliationEvidence(
        status=status, reason_taxonomy=reason_taxonomy, retry_disposition=retry_disposition,
        effect_count=len(ids), effect_ids=ids, evidence_refs=refs, evidence_sha256=_digest(unsigned),
    )


def verify_auto_effect_reconciliation(
    journal_root: str | Path, *, contract: GateContinuationContract,
    active_write_contract: ToolAuthorizationContract | None = None,
    expected_owned_scope: Sequence[str] = (), expected_scope_ref: str | None = None,
) -> EffectReconciliationEvidence:
    """Read-only AUTO effect reconciliation against the canonical ToolEffectJournal.

    This verifier never executes or repairs an effect. Any incomplete, unsafe, or
    unbound effect evidence fails closed so ownership remains with Full MCP / the
    user-decision boundary rather than DCC.
    """
    if not isinstance(contract, GateContinuationContract):
        raise TypeError("GateContinuationContract is required")

    root = Path(journal_root)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy="EFFECT_EVIDENCE_UNSAFE", retry_disposition="BLOCKED"
        )

    observed_paths = () if not root.exists() else tuple(sorted(
        path for path in root.iterdir()
        if path.is_file() and (path.name.endswith(".intent.json") or path.name.endswith(".receipt.json"))
    ))
    observed_ids = tuple(sorted({path.name.split(".", 1)[0] for path in observed_paths}))

    if contract.external_effect_policy == "NO_EXTERNAL_EFFECT":
        if observed_paths:
            return _reconciliation_evidence(
                status="BLOCKED", reason_taxonomy="UNEXPECTED_EFFECT_EVIDENCE", retry_disposition="BLOCKED",
                effect_ids=observed_ids,
            )
        return _reconciliation_evidence(
            status="PASS", reason_taxonomy="NO_EXTERNAL_EFFECT_VERIFIED", retry_disposition="NO_EFFECT"
        )

    if contract.external_effect_policy != "GOVERNED_REPOSITORY_EFFECTS_ONLY":
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy="EFFECT_POLICY_UNSUPPORTED", retry_disposition="BLOCKED"
        )
    if active_write_contract is None or not expected_owned_scope or not expected_scope_ref:
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy="EFFECT_EVIDENCE_AUTHORITY_MISSING", retry_disposition="BLOCKED",
            effect_ids=observed_ids,
        )

    try:
        evidence = collect_governed_write_effect_evidence(
            root, active_write_contract=active_write_contract, expected_owned_scope=expected_owned_scope
        )
    except EffectEvidenceBridgeError as exc:
        reason = (
            "AMBIGUOUS_EFFECT_EVIDENCE"
            if exc.reason_taxonomy in {"EFFECT_EVIDENCE_RECOVERY_AMBIGUOUS", "EFFECT_EVIDENCE_MISSING"}
            else exc.reason_taxonomy
        )
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy=reason, retry_disposition="BLOCKED", effect_ids=observed_ids
        )

    matching = [
        item for item in evidence
        if item.operation == WRITE_OPERATION and item.scope_ref == expected_scope_ref
    ]
    all_refs = tuple(ref for item in evidence for ref in item.evidence_refs)
    ids = tuple(item.effect_id for item in evidence)
    if len(evidence) != 1 or len(matching) != 1:
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy="EFFECT_EVIDENCE_COUNT_OR_SCOPE_MISMATCH",
            retry_disposition="BLOCKED", effect_ids=ids, evidence_refs=all_refs,
        )
    item = matching[0]
    if not (item.authorized and item.mutation_performed and item.security_passed and item.intent_receipt_consistent):
        return _reconciliation_evidence(
            status="BLOCKED", reason_taxonomy="EFFECT_EVIDENCE_NOT_SAFE", retry_disposition="BLOCKED",
            effect_ids=ids, evidence_refs=all_refs,
        )
    return _reconciliation_evidence(
        status="PASS", reason_taxonomy="GOVERNED_REPOSITORY_EFFECT_VERIFIED", retry_disposition="COMPLETED",
        effect_ids=ids, evidence_refs=all_refs,
    )

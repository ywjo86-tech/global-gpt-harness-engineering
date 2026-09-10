from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .completion_authority import (
    FrozenCompletionAuthority,
    CriterionVerificationEvidence,
    VERIFIER_TYPE,
    verify_all_frozen_completion_criteria,
)
from .completion_contract import (
    CompletionAssessment,
    CompletionCriterion,
    CompletionEvaluator,
    CompletionState,
    ExecutionObligation,
    VerifierResult,
    derive_execution_obligation,
)
from .execution_contract import CanonicalExecutionContract


class CompletionContractBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class CompletionBridgeAssessment:
    assessment: CompletionAssessment
    execution_obligation: ExecutionObligation
    evidence: tuple[CriterionVerificationEvidence, ...]


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompletionContractBridgeError(
            "Completion evidence is not canonically serializable",
            reason_taxonomy="COMPLETION_BRIDGE_EVIDENCE_INVALID",
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def build_completion_criteria(
    authority: FrozenCompletionAuthority,
) -> tuple[CompletionCriterion, ...]:
    if not authority.criteria:
        raise CompletionContractBridgeError(
            "Frozen Completion Authority contains no criteria",
            reason_taxonomy="COMPLETION_BRIDGE_CRITERIA_MISSING",
        )
    return tuple(
        CompletionCriterion(
            criterion_id=item.criterion_id,
            verifier_type=item.verifier_type,
            authoritative_source_ref=item.authoritative_source_ref,
            verifier_config={
                "task_ref": authority.task_ref,
                "snapshot_sha256": authority.snapshot_sha256,
                "node_set_digest": authority.node_set_digest,
                "node_names": list(item.node_names),
            },
            mandatory=item.mandatory,
        )
        for item in authority.criteria
    )


def _evidence_projection(
    item: CriterionVerificationEvidence,
) -> dict[str, Any]:
    value = item.canonical_projection()
    value["evidence_digest"] = item.evidence_digest
    return value


def _frozen_pytest_verifier(
    criterion: CompletionCriterion,
    authoritative_value: Any,
) -> VerifierResult:
    if not isinstance(authoritative_value, Mapping):
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_INVALID",
        )

    expected_source_ref = criterion.authoritative_source_ref
    expected_snapshot = criterion.verifier_config.get("snapshot_sha256")
    expected_node_set = criterion.verifier_config.get("node_set_digest")

    if (
        authoritative_value.get("criterion_id") != criterion.criterion_id
        or authoritative_value.get("authoritative_source_ref") != expected_source_ref
        or authoritative_value.get("snapshot_sha256") != expected_snapshot
        or authoritative_value.get("node_set_digest") != expected_node_set
    ):
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_BINDING_DRIFT",
        )

    supplied_digest = authoritative_value.get("evidence_digest")
    if not isinstance(supplied_digest, str) or not supplied_digest:
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_DIGEST_MISSING",
        )
    unsigned = {
        key: value
        for key, value in authoritative_value.items()
        if key != "evidence_digest"
    }
    if _digest(unsigned) != supplied_digest:
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_DIGEST_DRIFT",
        )

    raw_state = authoritative_value.get("state")
    try:
        state = CompletionState(raw_state)
    except (TypeError, ValueError):
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_STATE_INVALID",
        )

    reason = authoritative_value.get("reason_taxonomy")
    if not isinstance(reason, str):
        return VerifierResult(
            state=CompletionState.UNKNOWN,
            reason_taxonomy="AUTHORITATIVE_COMPLETION_EVIDENCE_REASON_INVALID",
        )

    return VerifierResult(
        state=state,
        evidence_refs=(
            f"{expected_source_ref}#evidence={supplied_digest}",
        ),
        reason_taxonomy=reason,
    )


def _authoritative_sources(
    evidence: Sequence[CriterionVerificationEvidence],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in evidence:
        if item.authoritative_source_ref in result:
            raise CompletionContractBridgeError(
                "Duplicate authoritative Completion source ref",
                reason_taxonomy="COMPLETION_BRIDGE_DUPLICATE_SOURCE",
            )
        result[item.authoritative_source_ref] = _evidence_projection(item)
    return result


def assess_frozen_completion(
    authority: FrozenCompletionAuthority,
    *,
    evidence: Sequence[CriterionVerificationEvidence],
) -> CompletionAssessment:
    criteria = build_completion_criteria(authority)
    evidence_tuple = tuple(evidence)
    if len(evidence_tuple) != len(criteria):
        raise CompletionContractBridgeError(
            "Frozen Completion evidence count does not match criterion count",
            reason_taxonomy="COMPLETION_BRIDGE_EVIDENCE_COUNT_DRIFT",
        )

    evaluator = CompletionEvaluator({VERIFIER_TYPE: _frozen_pytest_verifier})
    assessment = evaluator.evaluate(criteria, _authoritative_sources(evidence_tuple))

    expected_ids = tuple(sorted(item.criterion_id for item in criteria))
    actual_ids = tuple(sorted(item.criterion_id for item in assessment.criterion_results))
    if actual_ids != expected_ids:
        raise CompletionContractBridgeError(
            "CompletionAssessment criterion identity drift",
            reason_taxonomy="COMPLETION_BRIDGE_CRITERION_ID_DRIFT",
        )
    return assessment


def evaluate_frozen_completion(
    authority: FrozenCompletionAuthority,
    project_root: str | Path,
    *,
    timeout: int = 120,
) -> CompletionAssessment:
    evidence = verify_all_frozen_completion_criteria(
        authority,
        project_root,
        timeout=timeout,
    )
    return assess_frozen_completion(authority, evidence=evidence)


def evaluate_contract_completion(
    active_contract: CanonicalExecutionContract,
    authority: FrozenCompletionAuthority,
    project_root: str | Path,
    *,
    timeout: int = 120,
) -> CompletionBridgeAssessment:
    if tuple(sorted(active_contract.completion_criteria_ids)) != tuple(
        sorted(item.criterion_id for item in authority.criteria)
    ):
        raise CompletionContractBridgeError(
            "ACTIVE Contract completion criteria do not match Frozen Completion Authority",
            reason_taxonomy="COMPLETION_BRIDGE_CONTRACT_CRITERIA_DRIFT",
        )

    evidence = verify_all_frozen_completion_criteria(
        authority,
        project_root,
        timeout=timeout,
    )
    assessment = assess_frozen_completion(authority, evidence=evidence)
    obligation = derive_execution_obligation(
        active_contract.task_effect_policy,
        assessment,
    )
    return CompletionBridgeAssessment(
        assessment=assessment,
        execution_obligation=obligation,
        evidence=tuple(evidence),
    )

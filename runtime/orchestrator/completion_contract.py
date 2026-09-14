from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


BLOCKED_COMPLETION_CONTRACT = "BLOCKED_COMPLETION_CONTRACT"


class TaskEffectPolicy(str, Enum):
    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"


class CompletionState(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


class ExecutionObligation(str, Enum):
    READ_ONLY_EXECUTION = "READ_ONLY_EXECUTION"
    MUTATION_REQUIRED = "MUTATION_REQUIRED"
    NONE_SATISFIED = "NONE_SATISFIED"
    BLOCKED = "BLOCKED"


class CompletionContractError(ValueError):
    """Fail-closed completion contract definition error."""

    def __init__(self, message: str, *, reason_taxonomy: str = BLOCKED_COMPLETION_CONTRACT) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


class CompletionContractDriftError(CompletionContractError):
    """Raised when pre/post evaluation uses a different criterion set."""


def _freeze_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, MappingABC):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CompletionContractError("criterion configuration keys must be strings")
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, SequenceABC) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json_value(item) for item in value)
    raise CompletionContractError(
        f"criterion configuration contains unsupported value type: {type(value).__name__}"
    )


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class CompletionCriterion:
    criterion_id: str
    verifier_type: str
    authoritative_source_ref: str
    verifier_config: Mapping[str, Any] = field(default_factory=dict)
    mandatory: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.criterion_id, str):
            raise CompletionContractError("completion criterion_id must be a string")
        if not isinstance(self.verifier_type, str):
            raise CompletionContractError(f"{self.criterion_id}: verifier_type must be a string")
        if not isinstance(self.authoritative_source_ref, str):
            raise CompletionContractError(
                f"{self.criterion_id}: authoritative_source_ref must be a string"
            )
        if not isinstance(self.mandatory, bool):
            raise CompletionContractError(f"{self.criterion_id}: mandatory must be bool")
        criterion_id = self.criterion_id.strip()
        verifier_type = self.verifier_type.strip()
        source_ref = self.authoritative_source_ref.strip()
        if not criterion_id:
            raise CompletionContractError("completion criterion_id is required")
        if not verifier_type:
            raise CompletionContractError(f"{criterion_id}: verifier_type is required")
        if not source_ref:
            raise CompletionContractError(f"{criterion_id}: authoritative_source_ref is required")
        object.__setattr__(self, "criterion_id", criterion_id)
        object.__setattr__(self, "verifier_type", verifier_type)
        object.__setattr__(self, "authoritative_source_ref", source_ref)
        object.__setattr__(self, "verifier_config", _freeze_json_value(dict(self.verifier_config)))

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "verifier_type": self.verifier_type,
            "authoritative_source_ref": self.authoritative_source_ref,
            "verifier_config": _thaw_json_value(self.verifier_config),
            "mandatory": self.mandatory,
        }


@dataclass(frozen=True, slots=True)
class VerifierResult:
    state: CompletionState
    evidence_refs: tuple[str, ...] = ()
    reason_taxonomy: str = ""


@dataclass(frozen=True, slots=True)
class CriterionResult:
    criterion_id: str
    verifier_type: str
    authoritative_source_ref: str
    state: CompletionState
    evidence_refs: tuple[str, ...] = ()
    reason_taxonomy: str = ""
    mandatory: bool = True


@dataclass(frozen=True, slots=True)
class CompletionAssessment:
    criterion_results: tuple[CriterionResult, ...]
    overall_state: CompletionState
    criterion_set_digest: str
    evidence_refs: tuple[str, ...]


Verifier = Callable[[CompletionCriterion, Any], VerifierResult]


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CompletionContractError(f"criterion set is not reproducibly serializable: {exc}") from exc


def criterion_set_digest(criteria: Sequence[CompletionCriterion]) -> str:
    normalized = _validated_criteria(criteria)
    canonical = _canonical_json([criterion.canonical_projection() for criterion in normalized])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_criteria(criteria: Sequence[CompletionCriterion]) -> tuple[CompletionCriterion, ...]:
    normalized = tuple(criteria)
    if not normalized:
        raise CompletionContractError("at least one completion criterion is required")
    ids = [criterion.criterion_id for criterion in normalized]
    if len(ids) != len(set(ids)):
        raise CompletionContractError("duplicate completion criterion_id is not allowed")
    if not any(criterion.mandatory for criterion in normalized):
        raise CompletionContractError("at least one mandatory completion criterion is required")
    return tuple(sorted(normalized, key=lambda criterion: criterion.criterion_id))


class CompletionEvaluator:
    """Deterministic completion truth evaluator.

    The evaluator accepts only criterion definitions, registered verifier functions,
    and authoritative source snapshots. Worker claims and Orchestrator opinions are
    intentionally absent from this interface.
    """

    def __init__(self, verifier_registry: Mapping[str, Verifier]) -> None:
        registry = dict(verifier_registry)
        for name, verifier in registry.items():
            if not isinstance(name, str) or not name.strip():
                raise CompletionContractError("verifier registry names must be non-empty strings")
            if not callable(verifier):
                raise CompletionContractError(f"verifier {name!r} is not callable")
        self._verifier_registry = MappingProxyType(registry)

    @staticmethod
    def _safe_verify(
        verifier: Verifier,
        criterion: CompletionCriterion,
        authoritative_value: Any,
    ) -> VerifierResult:
        try:
            result = verifier(criterion, authoritative_value)
        except Exception:
            # Fail closed without persisting raw source values or exception content.
            return VerifierResult(
                state=CompletionState.UNKNOWN,
                reason_taxonomy="VERIFIER_EXECUTION_UNRESOLVED",
            )
        if (
            not isinstance(result, VerifierResult)
            or not isinstance(result.state, CompletionState)
            or not isinstance(result.reason_taxonomy, str)
            or any(not isinstance(ref, str) for ref in result.evidence_refs)
        ):
            return VerifierResult(
                state=CompletionState.UNKNOWN,
                reason_taxonomy="INVALID_VERIFIER_RESULT",
            )
        return result

    def evaluate(
        self,
        criteria: Sequence[CompletionCriterion],
        authoritative_sources: Mapping[str, Any],
    ) -> CompletionAssessment:
        normalized = _validated_criteria(criteria)
        digest = criterion_set_digest(normalized)
        results: list[CriterionResult] = []

        for criterion in normalized:
            verifier = self._verifier_registry.get(criterion.verifier_type)
            if verifier is None:
                results.append(
                    CriterionResult(
                        criterion_id=criterion.criterion_id,
                        verifier_type=criterion.verifier_type,
                        authoritative_source_ref=criterion.authoritative_source_ref,
                        state=CompletionState.UNKNOWN,
                        reason_taxonomy="UNKNOWN_VERIFIER_TYPE",
                        mandatory=criterion.mandatory,
                    )
                )
                continue

            if criterion.authoritative_source_ref not in authoritative_sources:
                results.append(
                    CriterionResult(
                        criterion_id=criterion.criterion_id,
                        verifier_type=criterion.verifier_type,
                        authoritative_source_ref=criterion.authoritative_source_ref,
                        state=CompletionState.UNKNOWN,
                        reason_taxonomy="AUTHORITATIVE_SOURCE_UNRESOLVED",
                        mandatory=criterion.mandatory,
                    )
                )
                continue

            authoritative_value = authoritative_sources[criterion.authoritative_source_ref]
            first_result = self._safe_verify(verifier, criterion, authoritative_value)
            second_result = self._safe_verify(verifier, criterion, authoritative_value)
            if first_result != second_result:
                verifier_result = VerifierResult(
                    state=CompletionState.UNKNOWN,
                    reason_taxonomy="NON_REPRODUCIBLE_VERIFIER_RESULT",
                )
            else:
                verifier_result = first_result

            results.append(
                CriterionResult(
                    criterion_id=criterion.criterion_id,
                    verifier_type=criterion.verifier_type,
                    authoritative_source_ref=criterion.authoritative_source_ref,
                    state=verifier_result.state,
                    evidence_refs=tuple(sorted(set(verifier_result.evidence_refs))),
                    reason_taxonomy=verifier_result.reason_taxonomy,
                    mandatory=criterion.mandatory,
                )
            )

        mandatory_states = [result.state for result in results if result.mandatory]
        if CompletionState.UNKNOWN in mandatory_states:
            overall = CompletionState.UNKNOWN
        elif CompletionState.UNSATISFIED in mandatory_states:
            overall = CompletionState.UNSATISFIED
        else:
            overall = CompletionState.SATISFIED

        evidence_refs = tuple(
            sorted({ref for result in results for ref in result.evidence_refs})
        )
        return CompletionAssessment(
            criterion_results=tuple(results),
            overall_state=overall,
            criterion_set_digest=digest,
            evidence_refs=evidence_refs,
        )


def derive_execution_obligation(
    task_effect_policy: TaskEffectPolicy,
    assessment: CompletionAssessment,
) -> ExecutionObligation:
    if assessment.overall_state is CompletionState.UNKNOWN:
        return ExecutionObligation.BLOCKED
    if task_effect_policy is TaskEffectPolicy.READ_ONLY:
        return ExecutionObligation.READ_ONLY_EXECUTION
    if assessment.overall_state is CompletionState.UNSATISFIED:
        return ExecutionObligation.MUTATION_REQUIRED
    if assessment.overall_state is CompletionState.SATISFIED:
        return ExecutionObligation.NONE_SATISFIED
    return ExecutionObligation.BLOCKED


def require_same_criterion_set(
    pre_assessment: CompletionAssessment,
    post_assessment: CompletionAssessment,
) -> None:
    if pre_assessment.criterion_set_digest != post_assessment.criterion_set_digest:
        raise CompletionContractDriftError(
            "pre/post completion criterion_set_digest mismatch"
        )

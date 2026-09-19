from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .contracts import canonical_digest

EVIDENCE_REF_SCHEMA_V1 = "ai-office.baseline-closure-evidence-ref.v1"
BASELINE_CLOSURE_CANDIDATE_SCHEMA_V1 = "ai-office.baseline-closure-candidate.v1"
REQUIRED_EXIT_EVIDENCE_IDS = (
    "EVD-018", "EVD-019", "EVD-020", "EVD-021", "EVD-022", "EVD-023",
)


class BaselineClosureError(ValueError):
    pass


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise BaselineClosureError(f"invalid {label}")
    item = value.strip()
    if any(ch in item for ch in ("\x00", "\n", "\r")):
        raise BaselineClosureError(f"invalid {label}")
    return item


def _sha(value: object, label: str) -> str:
    item = _text(value, label)
    if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
        raise BaselineClosureError(f"invalid {label}")
    return item


@dataclass(frozen=True, slots=True)
class BaselineClosureEvidenceRefV1:
    schema_version: str
    evidence_id: str
    evidence_ref: str
    evidence_digest: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_REF_SCHEMA_V1:
            raise BaselineClosureError("unsupported closure evidence schema")
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "evidence_ref", _text(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "evidence_digest", _sha(self.evidence_digest, "evidence_digest"))
        if self.status not in {"PASS", "FAIL", "BLOCKED"}:
            raise BaselineClosureError("invalid closure evidence status")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BaselineClosureCandidateV1:
    schema_version: str
    canonical_identity_ref: str
    required_evidence_ids: tuple[str, ...]
    canonical_evidence: tuple[BaselineClosureEvidenceRefV1, ...]
    alias_name: str
    alias_evidence: tuple[BaselineClosureEvidenceRefV1, ...]
    blocker_count: int
    unresolved_major_count: int
    must_traceability_coverage: int
    alias_equality_disposition: str
    disposition: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != BASELINE_CLOSURE_CANDIDATE_SCHEMA_V1:
            raise BaselineClosureError("unsupported baseline closure candidate schema")
        object.__setattr__(self, "canonical_identity_ref", _text(self.canonical_identity_ref, "canonical_identity_ref"))
        object.__setattr__(self, "alias_name", _text(self.alias_name, "alias_name"))
        if self.required_evidence_ids != REQUIRED_EXIT_EVIDENCE_IDS:
            raise BaselineClosureError("required exit evidence contract mismatch")
        for value, label in ((self.blocker_count, "blocker_count"), (self.unresolved_major_count, "unresolved_major_count")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BaselineClosureError(f"invalid {label}")
        if (isinstance(self.must_traceability_coverage, bool)
                or not isinstance(self.must_traceability_coverage, int)
                or not 0 <= self.must_traceability_coverage <= 100):
            raise BaselineClosureError("invalid must_traceability_coverage")
        if self.alias_equality_disposition not in {"IDENTICAL", "MISMATCH"}:
            raise BaselineClosureError("invalid alias equality disposition")
        if self.disposition not in {"GO_CANDIDATE", "NO_GO"}:
            raise BaselineClosureError("invalid closure disposition")
        if self.disposition == "GO_CANDIDATE" and self.reason_codes:
            raise BaselineClosureError("GO candidate cannot contain failure reasons")
        if self.disposition == "NO_GO" and not self.reason_codes:
            raise BaselineClosureError("NO_GO candidate requires reasons")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "canonical_identity_ref": self.canonical_identity_ref,
            "required_evidence_ids": list(self.required_evidence_ids),
            "canonical_evidence": [item.to_dict() for item in self.canonical_evidence],
            "alias_name": self.alias_name,
            "alias_evidence": [item.to_dict() for item in self.alias_evidence],
            "blocker_count": self.blocker_count,
            "unresolved_major_count": self.unresolved_major_count,
            "must_traceability_coverage": self.must_traceability_coverage,
            "alias_equality_disposition": self.alias_equality_disposition,
            "disposition": self.disposition,
            "reason_codes": list(self.reason_codes),
        }

    @property
    def candidate_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "candidate_digest": self.candidate_digest}


def _materialize(values: Iterable[BaselineClosureEvidenceRefV1]) -> tuple[BaselineClosureEvidenceRefV1, ...]:
    items = tuple(values)
    if any(not isinstance(item, BaselineClosureEvidenceRefV1) for item in items):
        raise BaselineClosureError("closure evidence must use BaselineClosureEvidenceRefV1")
    return items


def _ids(items: tuple[BaselineClosureEvidenceRefV1, ...]) -> tuple[str, ...]:
    return tuple(item.evidence_id for item in items)


def _identity_map(items: tuple[BaselineClosureEvidenceRefV1, ...]) -> dict[str, tuple[str, str]]:
    return {item.evidence_id: (item.evidence_ref, item.evidence_digest) for item in items}


def build_baseline_closure_candidate(
    *,
    canonical_identity_ref: str,
    canonical_evidence: Iterable[BaselineClosureEvidenceRefV1],
    alias_name: str,
    alias_evidence: Iterable[BaselineClosureEvidenceRefV1],
    blocker_count: int,
    unresolved_major_count: int,
    must_traceability_coverage: int,
) -> BaselineClosureCandidateV1:
    canonical = _materialize(canonical_evidence)
    alias = _materialize(alias_evidence)
    reasons: list[str] = []

    canonical_ids = _ids(canonical)
    alias_ids = _ids(alias)
    required = set(REQUIRED_EXIT_EVIDENCE_IDS)

    if len(canonical_ids) != len(set(canonical_ids)):
        reasons.append("DUPLICATE_CANONICAL_EVIDENCE")
    if len(alias_ids) != len(set(alias_ids)):
        reasons.append("DUPLICATE_ALIAS_EVIDENCE")
    canonical_set = set(canonical_ids)
    alias_set = set(alias_ids)
    if required - canonical_set:
        reasons.append("INCOMPLETE_CANONICAL_EVIDENCE")
    if canonical_set - required:
        reasons.append("UNEXPECTED_CANONICAL_EVIDENCE")
    if required - alias_set:
        reasons.append("INCOMPLETE_ALIAS_EVIDENCE")
    if alias_set - required:
        reasons.append("UNEXPECTED_ALIAS_EVIDENCE")
    if any(item.status != "PASS" for item in canonical):
        reasons.append("CANONICAL_EVIDENCE_NOT_PASS")
    if any(item.status != "PASS" for item in alias):
        reasons.append("ALIAS_EVIDENCE_NOT_PASS")

    alias_identical = (
        canonical_ids == REQUIRED_EXIT_EVIDENCE_IDS
        and alias_ids == REQUIRED_EXIT_EVIDENCE_IDS
        and _identity_map(canonical) == _identity_map(alias)
    )
    if not alias_identical:
        reasons.append("ALIAS_EVIDENCE_MISMATCH")
    if blocker_count != 0:
        reasons.append("BLOCKERS_OPEN")
    if unresolved_major_count != 0:
        reasons.append("MAJORS_OPEN")
    if must_traceability_coverage != 100:
        reasons.append("TRACEABILITY_INCOMPLETE")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return BaselineClosureCandidateV1(
        BASELINE_CLOSURE_CANDIDATE_SCHEMA_V1,
        canonical_identity_ref,
        REQUIRED_EXIT_EVIDENCE_IDS,
        canonical,
        alias_name,
        alias,
        blocker_count,
        unresolved_major_count,
        must_traceability_coverage,
        "IDENTICAL" if alias_identical else "MISMATCH",
        "GO_CANDIDATE" if not unique_reasons else "NO_GO",
        unique_reasons,
    )

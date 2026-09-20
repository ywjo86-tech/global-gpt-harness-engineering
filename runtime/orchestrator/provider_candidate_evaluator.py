from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateEvidenceV1:
    provider_id: str
    protocol_class: str
    credential_required: bool
    cost_class: str
    live_ready: bool
    latency_ms: int | None
    quota_visible: bool
    rate_visible: bool
    structured_output: bool
    model_catalog_visible: bool
    observability_score: int


@dataclass(frozen=True, slots=True)
class CandidateEvaluationV1:
    provider_id: str
    score_vector: tuple[int, ...]
    recommended_state: str
    reasons: tuple[str, ...]


def _protocol_compatible(value: str) -> bool:
    return str(value).strip().lower() in {"openai-compatible", "omniroute-openai-v1"}


def evaluate_candidate(evidence: CandidateEvidenceV1) -> CandidateEvaluationV1:
    compatible = _protocol_compatible(evidence.protocol_class)
    latency_known = evidence.latency_ms is not None and evidence.latency_ms >= 0
    latency_band = 0 if not latency_known else 3 if evidence.latency_ms <= 500 else 2 if evidence.latency_ms <= 2000 else 1
    cost = str(evidence.cost_class).strip().lower()
    score = (
        1 if compatible else 0,
        1 if evidence.live_ready else 0,
        2 if cost == "free" else 1 if cost == "paid" else 0,
        1 if not evidence.credential_required else 0,
        latency_band,
        1 if evidence.quota_visible else 0,
        1 if evidence.rate_visible else 0,
        1 if evidence.structured_output else 0,
        1 if evidence.model_catalog_visible else 0,
        max(0, min(int(evidence.observability_score), 3)),
    )
    reasons: list[str] = []
    if not compatible: reasons.append("protocol_incompatible_or_unknown")
    if not evidence.live_ready: reasons.append("live_access_not_yet_proven")
    if not evidence.model_catalog_visible: reasons.append("model_catalog_not_visible")
    # Evaluation may nominate CANDIDATE only; QUALIFIED is Task 7 live-gate authority.
    state = "CANDIDATE" if compatible and evidence.model_catalog_visible else "DISCOVERED"
    return CandidateEvaluationV1(evidence.provider_id, score, state, tuple(reasons))


def nominate_top_candidates(evidence: tuple[CandidateEvidenceV1, ...]) -> tuple[CandidateEvaluationV1, ...]:
    evaluations = tuple(evaluate_candidate(item) for item in evidence)
    candidates = tuple(item for item in evaluations if item.recommended_state == "CANDIDATE")
    if not candidates:
        return ()
    best = max(item.score_vector for item in candidates)
    # Preserve input/evidence order and all exact ties; provider identity never breaks ties.
    return tuple(item for item in candidates if item.score_vector == best)

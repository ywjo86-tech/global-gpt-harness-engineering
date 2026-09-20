from __future__ import annotations

import unittest

from runtime.orchestrator.provider_candidate_evaluator import (
    CandidateEvidenceV1, evaluate_candidate, nominate_top_candidates,
)


def _candidate(provider_id: str, *, ready: bool, cost_class: str = "free") -> CandidateEvidenceV1:
    return CandidateEvidenceV1(
        provider_id=provider_id, protocol_class="openai-compatible",
        credential_required=False, cost_class=cost_class, live_ready=ready,
        latency_ms=100 if ready else None, quota_visible=True,
        rate_visible=True, structured_output=True, model_catalog_visible=True,
        observability_score=1,
    )


class ProviderCandidateEvaluatorTests(unittest.TestCase):
    def test_brand_name_is_not_a_scoring_dimension(self) -> None:
        a = _candidate("z-provider", ready=True)
        b = _candidate("a-provider", ready=True)
        self.assertEqual(evaluate_candidate(a).score_vector, evaluate_candidate(b).score_vector)

    def test_missing_live_access_cannot_be_qualified(self) -> None:
        result = evaluate_candidate(_candidate("provider-x", ready=False))
        self.assertNotEqual(result.recommended_state, "QUALIFIED")
        self.assertEqual(result.recommended_state, "CANDIDATE")

    def test_evaluator_never_promotes_beyond_candidate(self) -> None:
        self.assertEqual(evaluate_candidate(_candidate("provider-x", ready=True)).recommended_state, "CANDIDATE")

    def test_ties_are_retained_without_lexical_brand_tiebreak(self) -> None:
        results = nominate_top_candidates((_candidate("z-provider", ready=False), _candidate("a-provider", ready=False)))
        self.assertEqual({r.provider_id for r in results}, {"z-provider", "a-provider"})

    def test_incompatible_protocol_is_not_nominated(self) -> None:
        bad = CandidateEvidenceV1("provider-x", "unknown", False, "free", False, None, True, True, True, True, 1)
        self.assertEqual(nominate_top_candidates((bad,)), ())


if __name__ == "__main__": unittest.main()

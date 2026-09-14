from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionContractDriftError,
    CompletionCriterion,
    CompletionEvaluator,
    CompletionState,
    ExecutionObligation,
    TaskEffectPolicy,
    VerifierResult,
    derive_execution_obligation,
    require_same_criterion_set,
)


def equals_expected(criterion: CompletionCriterion, value: object) -> VerifierResult:
    expected = criterion.verifier_config.get("expected")
    state = CompletionState.SATISFIED if value == expected else CompletionState.UNSATISFIED
    return VerifierResult(state=state, evidence_refs=(f"evidence:{criterion.criterion_id}",))


def unknown_verifier(criterion: CompletionCriterion, value: object) -> VerifierResult:
    return VerifierResult(
        state=CompletionState.UNKNOWN,
        evidence_refs=(f"evidence:{criterion.criterion_id}",),
        reason_taxonomy="SOURCE_VALUE_INDETERMINATE",
    )


class CompletionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = CompletionEvaluator(
            {
                "equals": equals_expected,
                "unknown": unknown_verifier,
            }
        )
        self.criteria = (
            CompletionCriterion(
                criterion_id="criterion-a",
                verifier_type="equals",
                authoritative_source_ref="source-a",
                verifier_config={"expected": True},
            ),
            CompletionCriterion(
                criterion_id="criterion-b",
                verifier_type="equals",
                authoritative_source_ref="source-b",
                verifier_config={"expected": "ready"},
            ),
        )

    def test_comp_001_all_mandatory_criteria_pass(self) -> None:
        assessment = self.evaluator.evaluate(
            self.criteria,
            {"source-a": True, "source-b": "ready"},
        )
        self.assertEqual(assessment.overall_state, CompletionState.SATISFIED)

    def test_comp_002_one_mandatory_criterion_fails(self) -> None:
        assessment = self.evaluator.evaluate(
            self.criteria,
            {"source-a": False, "source-b": "ready"},
        )
        self.assertEqual(assessment.overall_state, CompletionState.UNSATISFIED)

    def test_comp_003_unknown_criterion_fails_closed(self) -> None:
        criteria = (
            CompletionCriterion(
                criterion_id="criterion-unknown",
                verifier_type="unknown",
                authoritative_source_ref="source-unknown",
            ),
        )
        assessment = self.evaluator.evaluate(criteria, {"source-unknown": object()})
        self.assertEqual(assessment.overall_state, CompletionState.UNKNOWN)
        self.assertEqual(
            derive_execution_obligation(TaskEffectPolicy.MUTATING, assessment),
            ExecutionObligation.BLOCKED,
        )

    def test_comp_004_same_input_rerun_is_identical(self) -> None:
        sources = {"source-a": True, "source-b": "ready"}
        first = self.evaluator.evaluate(self.criteria, sources)
        second = self.evaluator.evaluate(self.criteria, sources)
        self.assertEqual(first, second)
        self.assertEqual(first.criterion_set_digest, second.criterion_set_digest)

    def test_comp_005_pre_post_digest_mismatch_blocks(self) -> None:
        pre = self.evaluator.evaluate(self.criteria, {"source-a": True, "source-b": "ready"})
        changed_criteria = self.criteria + (
            CompletionCriterion(
                criterion_id="criterion-c",
                verifier_type="equals",
                authoritative_source_ref="source-c",
                verifier_config={"expected": 1},
                mandatory=False,
            ),
        )
        post = self.evaluator.evaluate(
            changed_criteria,
            {"source-a": True, "source-b": "ready", "source-c": 1},
        )
        with self.assertRaises(CompletionContractDriftError):
            require_same_criterion_set(pre, post)

    def test_comp_006_read_only_is_policy_not_assessment(self) -> None:
        assessment = self.evaluator.evaluate(
            self.criteria,
            {"source-a": False, "source-b": "ready"},
        )
        self.assertEqual(assessment.overall_state, CompletionState.UNSATISFIED)
        self.assertEqual(
            derive_execution_obligation(TaskEffectPolicy.READ_ONLY, assessment),
            ExecutionObligation.READ_ONLY_EXECUTION,
        )
        self.assertNotIn("READ_ONLY", {state.value for state in CompletionState})

    def test_comp_007_mutating_unsatisfied_requires_mutation(self) -> None:
        assessment = self.evaluator.evaluate(
            self.criteria,
            {"source-a": False, "source-b": "ready"},
        )
        self.assertEqual(
            derive_execution_obligation(TaskEffectPolicy.MUTATING, assessment),
            ExecutionObligation.MUTATION_REQUIRED,
        )

    def test_auth_001_assessment_is_immutable(self) -> None:
        assessment = self.evaluator.evaluate(
            self.criteria,
            {"source-a": True, "source-b": "ready"},
        )
        with self.assertRaises(FrozenInstanceError):
            assessment.overall_state = CompletionState.UNSATISFIED  # type: ignore[misc]

    def test_auth_002_worker_claim_cannot_override_authoritative_source(self) -> None:
        sources = {
            "source-a": False,
            "source-b": "ready",
            "worker_claim": "no mutation needed",
        }
        assessment = self.evaluator.evaluate(self.criteria, sources)
        self.assertEqual(assessment.overall_state, CompletionState.UNSATISFIED)
        self.assertEqual(
            derive_execution_obligation(TaskEffectPolicy.MUTATING, assessment),
            ExecutionObligation.MUTATION_REQUIRED,
        )

    def test_missing_authoritative_source_is_unknown(self) -> None:
        assessment = self.evaluator.evaluate(self.criteria, {"source-a": True})
        self.assertEqual(assessment.overall_state, CompletionState.UNKNOWN)
        missing = next(
            result for result in assessment.criterion_results if result.criterion_id == "criterion-b"
        )
        self.assertEqual(missing.reason_taxonomy, "AUTHORITATIVE_SOURCE_UNRESOLVED")

    def test_unknown_verifier_type_is_unknown(self) -> None:
        criteria = (
            CompletionCriterion(
                criterion_id="criterion-x",
                verifier_type="not-registered",
                authoritative_source_ref="source-x",
            ),
        )
        assessment = self.evaluator.evaluate(criteria, {"source-x": True})
        self.assertEqual(assessment.overall_state, CompletionState.UNKNOWN)
        self.assertEqual(assessment.criterion_results[0].reason_taxonomy, "UNKNOWN_VERIFIER_TYPE")

    def test_raw_authoritative_value_is_not_persisted_in_assessment(self) -> None:
        secret_like = "do-not-persist-this-value"
        criteria = (
            CompletionCriterion(
                criterion_id="criterion-secret",
                verifier_type="equals",
                authoritative_source_ref="source-secret",
                verifier_config={"expected": secret_like},
            ),
        )
        assessment = self.evaluator.evaluate(criteria, {"source-secret": secret_like})
        self.assertNotIn(secret_like, repr(assessment))

    def test_criterion_order_does_not_change_set_digest(self) -> None:
        sources = {"source-a": True, "source-b": "ready"}
        forward = self.evaluator.evaluate(self.criteria, sources)
        reverse = self.evaluator.evaluate(tuple(reversed(self.criteria)), sources)
        self.assertEqual(forward.criterion_set_digest, reverse.criterion_set_digest)
        self.assertEqual(forward, reverse)

    def test_invalid_verifier_state_fails_closed(self) -> None:
        def invalid_state(criterion: CompletionCriterion, value: object) -> VerifierResult:
            return VerifierResult(state="SATISFIED")  # type: ignore[arg-type]

        evaluator = CompletionEvaluator({"invalid": invalid_state})
        criteria = (
            CompletionCriterion(
                criterion_id="criterion-invalid",
                verifier_type="invalid",
                authoritative_source_ref="source-invalid",
            ),
        )
        assessment = evaluator.evaluate(criteria, {"source-invalid": True})
        self.assertEqual(assessment.overall_state, CompletionState.UNKNOWN)
        self.assertEqual(assessment.criterion_results[0].reason_taxonomy, "INVALID_VERIFIER_RESULT")

    def test_nested_verifier_config_is_immutable(self) -> None:
        criterion = CompletionCriterion(
            criterion_id="criterion-nested",
            verifier_type="equals",
            authoritative_source_ref="source-nested",
            verifier_config={"nested": [1, 2]},
        )
        with self.assertRaises(AttributeError):
            criterion.verifier_config["nested"].append(3)  # type: ignore[union-attr]

    def test_non_reproducible_verifier_fails_closed(self) -> None:
        calls = {"count": 0}

        def alternating(criterion: CompletionCriterion, value: object) -> VerifierResult:
            calls["count"] += 1
            state = (
                CompletionState.SATISFIED
                if calls["count"] % 2
                else CompletionState.UNSATISFIED
            )
            return VerifierResult(state=state)

        evaluator = CompletionEvaluator({"alternating": alternating})
        criteria = (
            CompletionCriterion(
                criterion_id="criterion-alternating",
                verifier_type="alternating",
                authoritative_source_ref="source-alternating",
            ),
        )
        assessment = evaluator.evaluate(criteria, {"source-alternating": True})
        self.assertEqual(assessment.overall_state, CompletionState.UNKNOWN)
        self.assertEqual(
            assessment.criterion_results[0].reason_taxonomy,
            "NON_REPRODUCIBLE_VERIFIER_RESULT",
        )

    def test_empty_or_duplicate_criterion_contract_is_rejected(self) -> None:
        from runtime.orchestrator.completion_contract import CompletionContractError

        with self.assertRaises(CompletionContractError):
            self.evaluator.evaluate((), {})
        duplicate = self.criteria[0]
        with self.assertRaises(CompletionContractError):
            self.evaluator.evaluate((duplicate, duplicate), {"source-a": True})

    def test_non_string_config_key_is_rejected(self) -> None:
        from runtime.orchestrator.completion_contract import CompletionContractError

        with self.assertRaises(CompletionContractError):
            CompletionCriterion(
                criterion_id="criterion-config-key",
                verifier_type="equals",
                authoritative_source_ref="source-config-key",
                verifier_config={1: "invalid"},  # type: ignore[dict-item]
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from runtime.ai_office.agent_onboarding import AgentOnboardingError, evaluate_onboarding

DIGEST = "a" * 64


class AIOfficeAgentOnboardingTest(unittest.TestCase):
    def candidate(self):
        return {
            "agent_id": "external-specialist-v1",
            "source_ref": "source:approved-repository",
            "source_digest": DIGEST,
            "version_ref": "version:1.0.0",
            "risk_decision_ref": "risk:allow-001",
            "permission_decision_ref": "permission:allow-001",
            "human_approval_ref": "approval:user-001",
            "adoption_control_ref": "skill-adoption:sealed-001",
            "activation_version": 1,
            "approved_source": True,
            "immutable_version": True,
            "risk_allowed": True,
            "permission_allowed": True,
            "human_approval_required": True,
        }

    def validator(self, source_ref, source_digest, adoption_ref):
        return source_ref.startswith("source:approved") and source_digest == DIGEST and adoption_ref.startswith("skill-adoption:sealed")

    def test_017_unapproved_source_version_or_risk_blocks_eligibility(self) -> None:
        for field in ("approved_source", "immutable_version", "risk_allowed", "permission_allowed"):
            candidate = self.candidate()
            candidate[field] = False
            record = evaluate_onboarding(candidate, adoption_validator=self.validator)
            self.assertEqual(record.status, "BLOCKED")
        missing_approval = self.candidate()
        missing_approval["human_approval_ref"] = ""
        self.assertEqual(evaluate_onboarding(missing_approval, adoption_validator=self.validator).status, "BLOCKED")

    def test_018_existing_governed_adoption_validator_must_accept_exact_binding(self) -> None:
        calls = []
        def validating(source_ref, source_digest, adoption_ref):
            calls.append((source_ref, source_digest, adoption_ref))
            return self.validator(source_ref, source_digest, adoption_ref)
        record = evaluate_onboarding(self.candidate(), adoption_validator=validating)
        self.assertEqual(record.status, "ELIGIBLE")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], DIGEST)

    def test_018_activation_version_is_monotonic_and_provider_registry_is_forbidden(self) -> None:
        first = evaluate_onboarding(self.candidate(), adoption_validator=self.validator)
        next_candidate = self.candidate()
        next_candidate["activation_version"] = 2
        second = evaluate_onboarding(next_candidate, adoption_validator=self.validator, previous_record=first)
        self.assertEqual(second.status, "ELIGIBLE")
        bad = self.candidate()
        bad["provider_registry"] = "forbidden"
        with self.assertRaises(AgentOnboardingError):
            evaluate_onboarding(bad, adoption_validator=self.validator)


if __name__ == "__main__":
    unittest.main()

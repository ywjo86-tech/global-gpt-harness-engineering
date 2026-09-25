from __future__ import annotations

import inspect
import unittest

from runtime.orchestrator import ocpv2_runtime_service


class _OutboxMustNotBeUsed:
    def mark_published(self, projection_id, projection_sha256):
        raise AssertionError("project onboarding status projection must not enter canonical outbox finalization")


class ProjectOnboardingRuntimeTests(unittest.TestCase):
    def test_feature_flag_is_exact_and_fail_closed(self):
        enabled = ocpv2_runtime_service.project_onboarding_enabled_from_environment
        self.assertTrue(enabled({"OCP_PROJECT_ONBOARDING_ENABLED": "1"}))
        for value in ("", "0", "true", "TRUE", "yes", "2"):
            self.assertFalse(enabled({"OCP_PROJECT_ONBOARDING_ENABLED": value}))

    def test_status_projection_is_not_treated_as_canonical_result(self):
        ocpv2_runtime_service.finalize_remote_control_projection(
            _OutboxMustNotBeUsed(),
            {
                "schema_version": "orchestration.remote-project-onboarding-status-projection.v1",
                "message_id": "ONBOARD-1",
                "alias": "ai-commerce-intelligence",
                "request_digest": "a" * 64,
                "mode": "DRY_RUN",
                "result_class": "REGISTRATION_READY",
            },
        )

    def test_composition_injects_dedicated_onboarding_admission(self):
        source = inspect.getsource(ocpv2_runtime_service._compose_service)
        self.assertIn("ProjectOnboardingAdmission", source)
        self.assertIn("onboard_authorized=onboard", source)
        self.assertIn("project_onboarding_enabled=config.project_onboarding_enabled", source)
        self.assertIn("project_onboarding_policy_ref=config.project_onboarding_policy_ref", source)


if __name__ == "__main__":
    unittest.main()

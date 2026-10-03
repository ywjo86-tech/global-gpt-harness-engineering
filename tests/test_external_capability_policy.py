from __future__ import annotations

import unittest

from runtime.orchestrator.external_capability_policy import (
    decide_external_capability_invocation,
)


class ExternalCapabilityPolicyTests(unittest.TestCase):

    def test_state_change_never_returns_direct_executor(self):
        decision = decide_external_capability_invocation(
            execution_authority="STATE_CHANGING",
            lifecycle_state="ACTIVE",
            capability_id="publish_content",
            approved_capabilities=("publish_content",),
        )

        self.assertEqual(
            decision.disposition,
            "GATEWAY_REQUIRED",
        )
        self.assertEqual(
            decision.required_effect_boundary,
            "PRODUCTION_EXECUTION_GATEWAY",
        )

        self.assertFalse(hasattr(decision, "execute"))
        self.assertNotIn("full_mcp", repr(decision.to_dict()).lower())
        self.assertNotIn("final_assignee", decision.to_dict())
        self.assertNotIn("provider_ref", decision.to_dict())
        self.assertNotIn("model_ref", decision.to_dict())

    def test_read_only_active_capability_is_direct_read_allowed(self):
        decision = decide_external_capability_invocation(
            execution_authority="READ_ONLY",
            lifecycle_state="ACTIVE",
            capability_id="ui_design_review",
            approved_capabilities=("ui_design_review",),
        )

        self.assertEqual(
            decision.disposition,
            "DIRECT_READ_ALLOWED",
        )

    def test_unapproved_capability_is_blocked(self):
        decision = decide_external_capability_invocation(
            execution_authority="READ_ONLY",
            lifecycle_state="ACTIVE",
            capability_id="filesystem_write",
            approved_capabilities=("ui_design_review",),
        )

        self.assertEqual(decision.disposition, "BLOCKED")

    def test_non_active_lifecycle_is_blocked_before_effect_routing(self):
        decision = decide_external_capability_invocation(
            execution_authority="STATE_CHANGING",
            lifecycle_state="DRAINING",
            capability_id="publish_content",
            approved_capabilities=("publish_content",),
        )

        self.assertEqual(decision.disposition, "BLOCKED")
        self.assertEqual(decision.required_effect_boundary, "")


if __name__ == "__main__":
    unittest.main()

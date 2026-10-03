import unittest
from types import SimpleNamespace

from runtime.orchestrator.schemas import CandidateEvaluationState

from runtime.orchestrator.external_capability_binding import qualify_external_binding


CANDIDATE_EVALUATION = {
    "candidate_id": "design-agent",
    "evaluation_state": "SAFE_FOR_CONSIDERATION",
    "evidence_ref": "evidence:design-agent-evaluation",
    "permissions": ("read", "design"),
}


class ExternalCapabilityBindingTests(unittest.TestCase):
    def test_mcp_binding_does_not_require_install_or_copy(self):
        binding = qualify_external_binding(
            evaluation=CANDIDATE_EVALUATION,
            binding_kind="MCP_ENDPOINT",
            endpoint_ref="mcp:design-agent",
            requested_capabilities=("ui_design", "filesystem_write"),
            allowed_capabilities=("ui_design",),
            blocked_capabilities=("filesystem_write",),
            effect_policy="GATEWAY_REQUIRED",
        )
        self.assertEqual(binding.binding_kind, "MCP_ENDPOINT")
        self.assertEqual(binding.allowed_capabilities, ("ui_design",))
        self.assertEqual(binding.blocked_capabilities, ("filesystem_write",))
        self.assertTrue(binding.stable_asset_identifier.startswith("external-capability:sha256:"))
        self.assertFalse(hasattr(binding, "install_path"))

    def test_binding_never_selects_assignee_provider_or_model(self):
        payload = qualify_external_binding(
            evaluation=CANDIDATE_EVALUATION,
            binding_kind="ADAPTER",
            endpoint_ref="adapter:design-review",
            requested_capabilities=("ui_design",),
            allowed_capabilities=("ui_design",),
            blocked_capabilities=(),
            effect_policy="READ_ONLY",
        ).to_dict()
        self.assertFalse({"final_assignee", "provider", "model"}.intersection(payload))

    def test_binding_accepts_evaluator_enum_and_evidence_reference(self):
        evaluation = SimpleNamespace(
            evaluation_state=CandidateEvaluationState.SAFE_FOR_CONSIDERATION,
            evidence_reference="evidence:validated",
        )
        binding = qualify_external_binding(
            evaluation=evaluation,
            binding_kind="LOCAL_SKILL",
            endpoint_ref="",
            requested_capabilities=("read_only",),
            allowed_capabilities=("read_only",),
            blocked_capabilities=(),
            effect_policy="READ_ONLY",
            local_skill_asset_id="local-skill:test",
        )
        self.assertEqual(binding.evaluation_evidence_ref, "evidence:validated")



if __name__ == "__main__":
    unittest.main()

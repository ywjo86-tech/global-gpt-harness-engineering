from __future__ import annotations

import unittest

from runtime.ai_office.capability_governance import (
    CAPABILITY_NEED_SCHEMA_V1,
    CapabilityGovernanceError,
    CapabilityNeedV1,
    find_agents,
    route_capability_need,
)


class AIOfficeCapabilityGovernanceTest(unittest.TestCase):
    def need(self, capabilities=("reasoning",), authority="READ_ONLY") -> CapabilityNeedV1:
        return CapabilityNeedV1(
            CAPABILITY_NEED_SCHEMA_V1,
            "need-001",
            tuple(capabilities),
            authority,
            "purpose:fixture",
            "scope:fixture",
        )

    def test_016_owner_boundary_routing_does_not_select_provider_or_model(self) -> None:
        decision = route_capability_need(self.need(("reasoning", "review")))
        self.assertEqual(decision.owner_boundary, "MULTI_PROVIDER_ROUTER")
        self.assertEqual(decision.disposition, "ROUTABLE")
        keys = set(decision.to_dict())
        self.assertFalse({"provider", "provider_ref", "model", "model_ref"}.intersection(keys))

    def test_016_state_change_routes_only_to_execution_owner_and_mixed_owner_blocks(self) -> None:
        action = route_capability_need(self.need(("filesystem_write",), "STATE_CHANGING"))
        self.assertEqual(action.owner_boundary, "EXECUTION_BACKEND")
        mixed = route_capability_need(self.need(("reasoning", "filesystem_write"), "STATE_CHANGING"))
        self.assertEqual(mixed.disposition, "BLOCKED")
        self.assertEqual(mixed.owner_boundary, "")

    def test_016_find_agent_returns_eligibility_candidates_not_assignment(self) -> None:
        inventory = [{
            "agent_id": "qa_reviewer_agent",
            "version_ref": "registry:v1",
            "capabilities": ("reasoning", "review"),
            "inventory_ref": "inventory:canonical",
            "approved": True,
            "permission_eligible": True,
            "risk_eligible": True,
            "evidence_refs": ("evidence:registry",),
        }]
        candidates = find_agents(self.need(("reasoning", "review")), inventory)
        self.assertEqual(len(candidates), 1)
        payload = candidates[0].to_dict()
        self.assertEqual(payload["agent_id"], "qa_reviewer_agent")
        self.assertFalse({"selected", "final_assignee", "provider", "model"}.intersection(payload))

    def test_016_forbidden_provider_or_final_assignment_inventory_fails_closed(self) -> None:
        with self.assertRaises(CapabilityGovernanceError):
            find_agents(self.need(), [{"agent_id": "qa_reviewer_agent", "provider_ref": "forbidden"}])


if __name__ == "__main__":
    unittest.main()

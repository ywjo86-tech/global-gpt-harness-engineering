from __future__ import annotations

import unittest
from pathlib import Path

from poc.graphify.contracts import CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES


class GraphifyPolicyBoundaryTests(unittest.TestCase):
    def test_capability_set_is_repository_intelligence_only(self) -> None:
        forbidden = {
            "execution_backend_control", "provider_routing", "memory_persistence",
            "project_continuity", "workflow_governance", "context_assembly",
        }
        self.assertTrue(CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES)
        self.assertFalse(forbidden.intersection(CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES))

    def test_provider_boundary_config_preserves_router_authority(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "poc/graphify/config/provider_boundary.yaml").read_text(encoding="utf-8")
        self.assertIn("provider_selection_authority: PROVIDER_ROUTER", text)
        self.assertIn("task_level_provider_hardcoding: prohibited", text)
        self.assertIn("graphify_write_operations: prohibited", text)
        self.assertNotIn("automatic_multi_model_routing: enabled", text)


if __name__ == "__main__":
    unittest.main()

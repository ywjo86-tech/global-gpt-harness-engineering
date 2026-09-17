from __future__ import annotations

import unittest
from pathlib import Path

from runtime.orchestrator.contract_adapter import load_project_mapping, validate_mapping_sources
from runtime.orchestrator.gate_orchestrator import load_gate_plan, onboarding_dry_run


ROOT = Path(__file__).resolve().parents[1]


class MultiProviderFullPlanOnboardingTests(unittest.TestCase):
    def test_project_mapping_and_required_contracts_are_ready(self) -> None:
        result = onboarding_dry_run(ROOT, "MULTI_PROVIDER_FOUNDATION")
        self.assertTrue(result["contract_files_ready"], result)
        self.assertTrue(result["mapping_registered"], result)
        self.assertTrue(result["mapping_ready"], result)
        self.assertEqual(result["missing_contracts"], [])

        mapping = load_project_mapping(ROOT)
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(validate_mapping_sources(mapping), [])
        self.assertEqual(mapping.project_id, "MULTI_PROVIDER_FOUNDATION")

    def test_remaining_gates_project_exact_task_order(self) -> None:
        expected = {
            "GATE-008": ["TASK-010", "TASK-011", "TASK-012", "TASK-013", "TASK-014"],
            "GATE-009": ["TASK-015"],
            "GATE-010": ["TASK-016"],
        }
        for gate_id, tasks in expected.items():
            with self.subTest(gate_id=gate_id):
                plan = load_gate_plan(ROOT, gate_id)
                self.assertEqual([item.lv_id for item in plan.lvs], tasks)
                self.assertTrue(all(item.required_capabilities for item in plan.lvs))
                self.assertTrue(all(item.owned_files for item in plan.lvs))


if __name__ == "__main__":
    unittest.main()

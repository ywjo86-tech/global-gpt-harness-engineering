from __future__ import annotations

import unittest

from poc.graphify.phase_boundary import verify_phase2_scope


class PhaseBoundaryTests(unittest.TestCase):
    def test_poc_targets_are_allowed(self) -> None:
        record = verify_phase2_scope([
            "poc/graphify/contracts.py",
            "poc/graphify/graphify_adapter.py",
            "tests/test_graphify_adapter_contract.py",
        ])
        self.assertTrue(record["verified"])
        self.assertEqual(record["next_master_phase"], "PHASE_3_EXECUTION_BACKEND_CONTRACT_FINALIZATION")

    def test_core_or_future_phase_ownership_is_blocked(self) -> None:
        record = verify_phase2_scope(
            ["runtime/orchestrator/provider_router.py"],
            ["ai_office_implementation"],
        )
        self.assertFalse(record["verified"])
        self.assertEqual(len(record["violations"]), 2)


if __name__ == "__main__":
    unittest.main()

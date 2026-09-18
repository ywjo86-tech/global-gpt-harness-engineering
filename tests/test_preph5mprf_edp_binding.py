from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


class PrePh5MprfEdpBindingTests(unittest.TestCase):
    def test_plan_bound_edp_standard_exists_and_matches_exact_sha(self) -> None:
        root = Path(__file__).resolve().parents[1]
        plan = (
            root / "docs/history/upgrades/2026-09-18-AI-OFFICE-HARNESS-PH5/"
            "DEVELOPMENT_PLAN.pre-AI-OFFICE-HARNESS-PH5.7a5758cae4976ade902ffd4cde920cddea9390c7fb25fbc33eb7b3854604601f.txt"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"(?m)^DESIGN_DIAGNOSIS_STANDARD_SHA256:\s*`([0-9a-f]{64})`\s*$",
            plan,
        )
        self.assertIsNotNone(match, "plan must bind the EDP standard SHA-256")
        standard = root / "standards" / "EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md"
        self.assertTrue(standard.is_file(), "plan-bound EDP standard must be present")
        observed = hashlib.sha256(standard.read_bytes()).hexdigest()
        self.assertEqual(observed, match.group(1))

    def test_mapped_contract_phase_uses_canonical_gate_ledger(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if root.name != "MULTI_PROVIDER_FOUNDATION":
            self.skipTest("project identity binding requires MULTI_PROVIDER_FOUNDATION basename")
        from runtime.orchestrator.contract_loader import load_contract

        contract = load_contract(root)
        self.assertEqual(contract.current_phase, "FINAL_CLOSURE")



if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


class PrePh5MprfEdpBindingTests(unittest.TestCase):
    def test_plan_bound_edp_standard_exists_and_matches_exact_sha(self) -> None:
        root = Path(__file__).resolve().parents[1]
        plan = (root / "docs" / "DEVELOPMENT_PLAN.txt").read_text(encoding="utf-8")
        match = re.search(
            r"(?m)^DESIGN_DIAGNOSIS_STANDARD_SHA256:\s*`([0-9a-f]{64})`\s*$",
            plan,
        )
        self.assertIsNotNone(match, "plan must bind the EDP standard SHA-256")
        standard = root / "standards" / "EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md"
        self.assertTrue(standard.is_file(), "plan-bound EDP standard must be present")
        observed = hashlib.sha256(standard.read_bytes()).hexdigest()
        self.assertEqual(observed, match.group(1))


if __name__ == "__main__":
    unittest.main()

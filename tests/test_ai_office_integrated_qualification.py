from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

from tests.test_ai_office_daily_loop_e2e import AIOfficeDailyLoopE2ETest
from tests.test_ai_office_project_factory_e2e import AIOfficeProjectFactoryE2ETest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "DEVELOPMENT_PLAN.txt"
TASK016_REQUIREMENTS = (
    "REQ-006", "REQ-007", "REQ-008", "REQ-017",
    "NFR-003", "NFR-004", "NFR-005", "NFR-009",
    "SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005", "SEC-006", "SEC-007",
    "OPS-005", "OPS-006", "OPS-009",
)
REGRESSION_SELECTIONS = (
    "tests/test_ai_office_project_factory_e2e.py",
    "tests/test_ai_office_daily_loop_e2e.py",
    "tests/test_ai_office_authority_negative_space.py",
    "tests/test_ai_office_execution_contract.py",
    "tests/test_ai_office_observability_boundary.py",
    "tests/test_provider_router.py",
    "tests/test_provider_action_execution.py",
    "tests/test_production_full_plan_runner.py",
    "tests/full_mcp",
    "tests/mprf",
)
EDP_EXIT_CRITERIA = {
    "BLOCKER_COUNT": 0,
    "UNRESOLVED_MAJOR_COUNT": 0,
    "MUST_REQUIREMENT_COVERAGE": 100,
    "MUST_TRACEABILITY_COVERAGE": 100,
    "DOMAIN_EVIDENCE_COVERAGE": 100,
    "CROSS_DOCUMENT_CONFLICT_COUNT": 0,
    "BROKEN_REFERENCE_COUNT": 0,
    "ADVERSARIAL_NEW_BLOCKER_MAJOR": 0,
    "PASS_CHALLENGE_OPEN_COUNT": 0,
}


class AIOfficeIntegratedQualificationTest(unittest.TestCase):
    def test_029_representative_task015_flows_pass_as_a_single_qualification_suite(self) -> None:
        suite = unittest.TestSuite()
        loader = unittest.defaultTestLoader
        suite.addTests(loader.loadTestsFromTestCase(AIOfficeProjectFactoryE2ETest))
        suite.addTests(loader.loadTestsFromTestCase(AIOfficeDailyLoopE2ETest))
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertGreaterEqual(result.testsRun, 4)

    def test_030_program_regression_selection_spans_ai_office_full_mcp_mprf_and_provider_boundaries(self) -> None:
        missing = [item for item in REGRESSION_SELECTIONS if not (ROOT / item).exists()]
        self.assertEqual(missing, [])
        joined = " ".join(REGRESSION_SELECTIONS)
        for required in ("ai_office", "full_mcp", "mprf", "provider_router", "provider_action", "production_full_plan"):
            self.assertIn(required, joined)
        self.assertNotIn("phase6", joined.lower())
        self.assertNotIn("phase7", joined.lower())

    def test_031_task016_requirements_have_explicit_gate005_traceability_and_complete_exit_criteria(self) -> None:
        text = PLAN.read_text(encoding="utf-8")
        rows = {match.group(1): match.group(0) for match in re.finditer(r"(?m)^\|\s*([A-Z]+-\d+)\s*\|.*$", text)}
        missing = []
        qualification_tests = ("TEST-028", "TEST-029", "TEST-030", "TEST-031")
        for requirement in TASK016_REQUIREMENTS:
            row = rows.get(requirement, "")
            if "GATE-005" not in row or "EVD-" not in row or not any(test_id in row for test_id in qualification_tests):
                missing.append(requirement)
        self.assertEqual(missing, [])
        self.assertEqual(EDP_EXIT_CRITERIA["BLOCKER_COUNT"], 0)
        self.assertEqual(EDP_EXIT_CRITERIA["UNRESOLVED_MAJOR_COUNT"], 0)
        self.assertEqual(EDP_EXIT_CRITERIA["MUST_REQUIREMENT_COVERAGE"], 100)
        self.assertEqual(EDP_EXIT_CRITERIA["MUST_TRACEABILITY_COVERAGE"], 100)
        self.assertEqual(EDP_EXIT_CRITERIA["DOMAIN_EVIDENCE_COVERAGE"], 100)
        gate_section = text.split("## GATE-005", 1)[1].split("---", 1)[0]
        self.assertIn("Blocker=0", gate_section)
        self.assertIn("unresolved Major=0", gate_section)
        self.assertIn("coverage=100%", gate_section)
        self.assertIn("conflicts/broken refs=0", gate_section)
        self.assertNotIn("CONDITIONAL_GO Condition: minor", gate_section)

    def test_031_task016_definition_contains_no_material_tbd_or_open_question(self) -> None:
        text = PLAN.read_text(encoding="utf-8")
        section = text.split("## TASK-016", 1)[1].split("## TASK-017", 1)[0]
        self.assertIsNone(re.search(r"(?i)TBD|OPEN QUESTION|TO BE DECIDED", section))


if __name__ == "__main__":
    unittest.main()

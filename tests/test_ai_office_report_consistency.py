import unittest
from runtime.ai_office.report_consistency import validate_report_consistency
from runtime.ai_office.report_renderers import render_human_report, render_llm_report
from tests.reporting_fixtures import sample_report


class ReportConsistencyTests(unittest.TestCase):
    def test_valid_reports_pass(self):
        report = sample_report()
        self.assertEqual(validate_report_consistency(report, render_human_report(report), render_llm_report(report)).status, "PASS")

    def test_user_action_mismatch_fails(self):
        report = sample_report()
        human = render_human_report(report).replace(report.user_action, "Approval required")
        result = validate_report_consistency(report, human, render_llm_report(report))
        self.assertEqual(result.status, "FAIL")
        self.assertIn("user_action", result.mismatched_fields)


if __name__ == "__main__": unittest.main()

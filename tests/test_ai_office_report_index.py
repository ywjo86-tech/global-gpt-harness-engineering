import unittest
from runtime.ai_office.report_index import extract_report_index, is_report_relevant
from runtime.ai_office.report_renderers import render_llm_report
from tests.reporting_fixtures import sample_report

class ReportIndexTests(unittest.TestCase):
    def test_bounded_index(self):
        report=sample_report(); index=extract_report_index(render_llm_report(report))
        self.assertEqual(index.target, report.target); self.assertEqual(index.purpose, report.purpose)
        self.assertNotIn("TECHNICAL_REFERENCES", index.raw_sections)
        self.assertTrue(is_report_relevant(index,"AI Office","implementation"))

if __name__ == "__main__": unittest.main()

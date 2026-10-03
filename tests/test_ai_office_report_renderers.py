import unittest
from runtime.ai_office.report_renderers import render_human_report, render_llm_report
from tests.reporting_fixtures import sample_report


class ReportRendererTests(unittest.TestCase):
    def test_human_purpose_is_one_line_before_summary(self):
        text = render_human_report(sample_report())
        purpose = text.split("■ 보고서 작성 목적\n\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("\n", purpose)
        self.assertLess(text.index("■ 보고서 작성 목적"), text.index("■ 보고서 요약"))

    def test_llm_fixed_heading_order(self):
        text = render_llm_report(sample_report())
        headings = ["REPORT_META", "PURPOSE", "READ_WHEN", "SUMMARY", "CURRENT_STATE",
                    "COMPLETED", "IN_PROGRESS", "ISSUES", "USER_ACTION", "NEXT",
                    "FINAL_STATE", "TECHNICAL_REFERENCES"]
        positions = [text.index("## " + value) for value in headings]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__": unittest.main()

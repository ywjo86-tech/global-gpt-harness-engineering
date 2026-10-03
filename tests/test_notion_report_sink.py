import unittest
from runtime.ai_office.report_sinks import ReportSaveRequest
from runtime.operator_transport.notion_report_sink import NotionReportSink

class NotionSinkTests(unittest.TestCase):
    def test_active_capability_required(self):
        sink=NotionReportSink(capability_state="QUALIFIED", create_report_page=lambda _: {})
        with self.assertRaisesRegex(ValueError, "ACTIVE"):
            sink.save(ReportSaveRequest("R","NOTION","AI-OFFICE/R","body"))
    def test_active_save(self):
        sink=NotionReportSink(capability_state="ACTIVE", create_report_page=lambda _: {"page_ref":"p1","content_sha256":"a"*64})
        self.assertEqual(sink.save(ReportSaveRequest("R","NOTION","AI-OFFICE/R","body"))["remote_ref"], "p1")

if __name__ == "__main__": unittest.main()

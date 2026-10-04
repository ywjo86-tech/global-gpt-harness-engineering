import unittest
from runtime.ai_office.report_sinks import ReportSaveRequest
from runtime.operator_transport.llmwiki_report_sink import LLMWikiReportSink

class LLMWikiSinkTests(unittest.TestCase):
    def test_inbox_create_only(self):
        calls=[]; sink=LLMWikiReportSink(lambda path, body: calls.append((path,body)) or {"path":body["path"],"sha256":"a"*64})
        result=sink.save(ReportSaveRequest("RPT-1","LLMWIKI","inbox/RPT-1.md","# report\n"))
        self.assertEqual(calls[0][0], "/notes/create"); self.assertEqual(result["remote_ref"], "inbox/RPT-1.md")
    def test_outside_inbox_rejected(self):
        with self.assertRaises(ValueError):
            LLMWikiReportSink(lambda *_: {}).save(ReportSaveRequest("R","LLMWIKI","docs/x.md","x"))

if __name__ == "__main__": unittest.main()

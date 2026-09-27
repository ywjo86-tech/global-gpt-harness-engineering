import tempfile, unittest
from runtime.ai_office.report_receipts import ReportReceiptStore
from runtime.ai_office.report_sinks import ReportSaveRequest, save_once

class FakeSink:
    def __init__(self, calls): self.calls = calls
    def save(self, request):
        self.calls.append(request)
        return {"remote_ref": "r1", "digest": "a" * 64}

class ReportSinkTests(unittest.TestCase):
    def test_save_once_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]; request=ReportSaveRequest("RPT-1", "LLMWIKI", "inbox/RPT-1.md", "body")
            first=save_once(FakeSink(calls), request, ReportReceiptStore(root))
            second=save_once(FakeSink(calls), request, ReportReceiptStore(root))
            self.assertEqual(first, second); self.assertEqual(len(calls), 1)

    def test_same_identity_with_changed_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]; store=ReportReceiptStore(root); sink=FakeSink(calls)
            save_once(sink, ReportSaveRequest("RPT-1","LLMWIKI","inbox/RPT-1.md","body"), store)
            with self.assertRaisesRegex(ValueError, "content"):
                save_once(sink, ReportSaveRequest("RPT-1","LLMWIKI","inbox/RPT-1.md","changed"), store)
            self.assertEqual(len(calls), 1)

if __name__ == "__main__": unittest.main()

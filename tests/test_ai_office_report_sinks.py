import hashlib, tempfile, threading, time, unittest
from runtime.ai_office.report_receipts import ReportReceiptStore
from runtime.ai_office.report_sinks import ReportSaveRequest, ReportSinkError, save_once

class FakeSink:
    def __init__(self, calls): self.calls = calls
    def save(self, request):
        self.calls.append(request)
        return {"remote_ref": "r1", "digest": hashlib.sha256(request.content.encode()).hexdigest()}

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

    def test_missing_remote_digest_is_rejected(self):
        class MissingDigestSink:
            def save(self, request):
                return {"remote_ref": "missing"}
        with tempfile.TemporaryDirectory() as root:
            request=ReportSaveRequest("RPT-MISSING","LLMWIKI","inbox/RPT-MISSING.md","body")
            with self.assertRaisesRegex(ReportSinkError, "missing or invalid"):
                save_once(MissingDigestSink(), request, ReportReceiptStore(root))

    def test_concurrent_save_once_invokes_sink_once(self):
        class SlowSink:
            def __init__(self):
                self.calls=0
                self.guard=threading.Lock()
            def save(self, request):
                with self.guard:
                    self.calls+=1
                time.sleep(0.05)
                return {"remote_ref":"saved","digest":hashlib.sha256(request.content.encode()).hexdigest()}
        with tempfile.TemporaryDirectory() as root:
            sink=SlowSink(); store=ReportReceiptStore(root)
            request=ReportSaveRequest("RPT-CONCURRENT","LLMWIKI","inbox/RPT-CONCURRENT.md","body")
            start=threading.Barrier(3); receipts=[]; errors=[]
            def worker():
                try:
                    start.wait()
                    receipts.append(save_once(sink, request, store))
                except Exception as exc:
                    errors.append(exc)
            t1=threading.Thread(target=worker); t2=threading.Thread(target=worker)
            t1.start(); t2.start(); start.wait(); t1.join(5); t2.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(sink.calls, 1)
            self.assertEqual(len(receipts), 2)
            self.assertEqual(receipts[0], receipts[1])


if __name__ == "__main__": unittest.main()

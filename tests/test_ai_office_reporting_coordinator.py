import hashlib, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from runtime.ai_office.reporting_coordinator import ReportingCoordinator
from tests.reporting_fixtures import sample_report

class Sink:
    def __init__(self, destination, fail=False): self.destination=destination; self.fail=fail; self.calls=0
    def save(self, request):
        self.calls+=1
        if self.fail: raise ValueError("unavailable")
        return {
            "remote_ref": self.destination + ":1",
            "digest": hashlib.sha256(request.content.encode()).hexdigest(),
        }

class CoordinatorTests(unittest.TestCase):
    def test_partial_failure_and_retry_only_pending(self):
        with tempfile.TemporaryDirectory() as root:
            notion=Sink("NOTION"); wiki=Sink("LLMWIKI", True)
            coordinator=ReportingCoordinator(root, {"NOTION":notion,"LLMWIKI":wiki})
            first=coordinator.record(sample_report())
            self.assertEqual((first.execution_status,first.human_report_status,first.llm_report_status,first.final_completion_status),("SUCCESS","SAVED","PENDING","WAITING_REPORT"))
            wiki.fail=False; second=coordinator.retry_pending(first.report_id)
            self.assertEqual(second.final_completion_status,"COMPLETE"); self.assertEqual(notion.calls,1); self.assertEqual(wiki.calls,2)

    def test_report_id_cannot_escape_record_directory(self):
        with tempfile.TemporaryDirectory() as root:
            outside=Path(root)/"runtime"/"orchestrator_state.json"
            outside.parent.mkdir(parents=True)
            outside.write_text("sentinel")
            coordinator=ReportingCoordinator(root, {"NOTION":Sink("NOTION"),"LLMWIKI":Sink("LLMWIKI")})
            report=replace(sample_report(), report_id="../runtime/orchestrator_state")
            with self.assertRaisesRegex(ValueError, "escapes report-records"):
                coordinator.record(report)
            self.assertEqual(outside.read_text(), "sentinel")


if __name__ == "__main__": unittest.main()

from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from .report_consistency import validate_report_consistency
from .report_receipts import ReportReceiptStore
from .report_renderers import render_human_report, render_llm_report
from .report_sinks import ReportSaveRequest, save_once
from .work_records import ReportDataV1

@dataclass(frozen=True, slots=True)
class RecordingOutcomeV1:
    report_id: str; execution_status: str; verification_status: str
    human_report_status: str; llm_report_status: str; final_completion_status: str
    receipt_refs: tuple[str, ...]

class ReportingCoordinator:
    def __init__(self, root, sinks):
        self.root=Path(root).resolve(); self.records=self.root/"report-records"; self.sinks=dict(sinks)
        self.receipts=ReportReceiptStore(self.root)
    def _path(self, report_id): return self.records/f"{report_id}.json"
    def _persist(self, report):
        self.records.mkdir(parents=True,exist_ok=True); path=self._path(report.report_id)
        payload=asdict(report); tmp=path.with_suffix(".tmp"); tmp.write_text(json.dumps(payload,sort_keys=True,indent=2)+"\n"); tmp.replace(path)
    def _load(self, report_id):
        raw=json.loads(self._path(report_id).read_text())
        for key in ("summary","completed","in_progress","issues","next_actions","technical_references","evidence_refs"): raw[key]=tuple(raw[key])
        return ReportDataV1(**raw)
    def record(self, report):
        self._persist(report); return self._save_pending(report)
    def retry_pending(self, report_id): return self._save_pending(self._load(report_id))
    def _save_pending(self, report):
        human=render_human_report(report); llm=render_llm_report(report)
        if validate_report_consistency(report,human,llm).status!="PASS": raise ValueError("report consistency failed")
        receipts=[]; statuses={"NOTION":"PENDING","LLMWIKI":"PENDING"}
        requests={"NOTION":ReportSaveRequest(report.report_id,"NOTION",f"AI-OFFICE/{report.report_id}",human),
                  "LLMWIKI":ReportSaveRequest(report.report_id,"LLMWIKI",f"inbox/{report.report_id}.md",llm)}
        for destination, request in requests.items():
            try:
                receipt=save_once(self.sinks[destination],request,self.receipts); statuses[destination]="SAVED"; receipts.append(receipt.receipt_digest)
            except (KeyError, ValueError, OSError): pass
        complete=all(value=="SAVED" for value in statuses.values())
        return RecordingOutcomeV1(report.report_id,report.execution_status,report.verification_status,statuses["NOTION"],statuses["LLMWIKI"],"COMPLETE" if complete else "WAITING_REPORT",tuple(sorted(receipts)))

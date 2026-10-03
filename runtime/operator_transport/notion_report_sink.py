from typing import Callable, Mapping
from runtime.ai_office.report_sinks import ReportSaveRequest, ReportSinkError

class NotionReportSink:
    destination="NOTION"
    def __init__(self, *, capability_state: str, create_report_page: Callable[[Mapping[str, object]], Mapping[str, object]]):
        self.capability_state=capability_state; self._create_report_page=create_report_page
    def save(self, request: ReportSaveRequest):
        if self.capability_state!="ACTIVE": raise ReportSinkError("Notion report-write capability must be ACTIVE")
        if request.destination!=self.destination: raise ReportSinkError("Notion report destination mismatch")
        result=self._create_report_page({"report_id":request.report_id,"destination_key":request.destination_key,"content":request.content})
        return {"remote_ref":str(result["page_ref"]),"digest":str(result["content_sha256"])}

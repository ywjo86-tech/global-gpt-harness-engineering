from typing import Callable, Mapping
from runtime.ai_office.report_sinks import ReportSaveRequest, ReportSinkError

class LLMWikiReportSink:
    destination="LLMWIKI"
    def __init__(self, post_json: Callable[[str, Mapping[str, object]], Mapping[str, object]]): self._post_json=post_json
    def save(self, request: ReportSaveRequest):
        if request.destination!=self.destination or not request.destination_key.startswith("inbox/") or not request.destination_key.endswith(".md") or ".." in request.destination_key.split("/"):
            raise ReportSinkError("LLMWiki report path must be an inbox Markdown note")
        payload=self._post_json("/notes/create", {"path":request.destination_key,"content":request.content})
        return {"remote_ref":str(payload["path"]),"digest":str(payload["sha256"])}

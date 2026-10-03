from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Protocol

class ReportSinkError(ValueError): pass

@dataclass(frozen=True, slots=True)
class ReportSaveRequest:
    report_id: str
    destination: str
    destination_key: str
    content: str

class ReportSink(Protocol):
    def save(self, request: ReportSaveRequest): ...

def save_once(sink: ReportSink, request: ReportSaveRequest, receipt_store):
    with receipt_store.lock(request):
        existing=receipt_store.load(request)
        if existing is not None: return existing
        result=sink.save(request)
        digest=str(result.get("digest") or "")
        content_digest=hashlib.sha256(request.content.encode()).hexdigest()
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
            raise ReportSinkError("sink digest is missing or invalid")
        if digest != content_digest:
            raise ReportSinkError("sink digest mismatch")
        return receipt_store.create(request, str(result.get("remote_ref") or ""), content_digest)

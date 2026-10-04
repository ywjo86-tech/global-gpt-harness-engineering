from __future__ import annotations
import fcntl, hashlib, json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from .report_sinks import ReportSaveRequest
from runtime.orchestrator.durable_io import atomic_write_json

@dataclass(frozen=True, slots=True)
class ReportSaveReceiptV1:
    report_id: str; destination: str; destination_key: str; remote_ref: str
    content_sha256: str; saved_at: str; status: str; receipt_digest: str

class ReportReceiptStore:
    def __init__(self, root): self.root=Path(root).resolve()/"report-receipts"
    def _key(self, request):
        return hashlib.sha256(f"{request.report_id}\0{request.destination}\0{request.destination_key}".encode()).hexdigest()
    def _path(self, request):
        return self.root/f"{self._key(request)}.json"
    @contextmanager
    def lock(self, request):
        self.root.mkdir(parents=True, exist_ok=True)
        path=self.root/f"{self._key(request)}.lock"
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    def load(self, request):
        path=self._path(request)
        if not path.exists(): return None
        raw=json.loads(path.read_text()); digest=raw.pop("receipt_digest")
        expected=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if digest!=expected: raise ValueError("report receipt digest mismatch")
        if raw["content_sha256"] != hashlib.sha256(request.content.encode()).hexdigest():
            raise ValueError("report receipt content mismatch")
        return ReportSaveReceiptV1(**raw, receipt_digest=digest)
    def create(self, request, remote_ref, content_sha256):
        path=self._path(request); path.parent.mkdir(parents=True,exist_ok=True)
        raw={"report_id":request.report_id,"destination":request.destination,"destination_key":request.destination_key,
             "remote_ref":remote_ref,"content_sha256":content_sha256,"saved_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"status":"SAVED"}
        raw["receipt_digest"]=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if path.exists(): return self.load(request)
        atomic_write_json(path, raw)
        return ReportSaveReceiptV1(**raw)

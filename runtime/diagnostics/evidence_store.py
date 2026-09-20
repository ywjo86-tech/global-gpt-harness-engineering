"""Create-once digest-bound storage for non-authoritative diagnostic evidence."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .contracts import AnalysisEvidenceEnvelope


class DiagnosticEvidenceStoreError(ValueError):
    pass


class DiagnosticEvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink(): raise DiagnosticEvidenceStoreError("evidence root is unsafe")

    def put(self, envelope: AnalysisEvidenceEnvelope) -> str:
        payload=asdict(envelope)
        raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        digest=hashlib.sha256(raw).hexdigest(); target=self.root/f"{digest}.json"
        if target.exists():
            if target.is_symlink() or target.read_bytes()!=raw+b"\n":
                raise DiagnosticEvidenceStoreError("evidence digest collision or unsafe target")
            return f"diagnostic://sha256/{digest}"
        fd,tmp=tempfile.mkstemp(prefix=target.name+".",dir=str(self.root))
        try:
            with os.fdopen(fd,"wb") as handle:
                handle.write(raw+b"\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(tmp,target)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return f"diagnostic://sha256/{digest}"

"""Hash/index/checkpoint based lifecycle context resolution with bound caching."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from .lifecycle_binding import canonical_bytes, validate_binding


class IncrementalResolutionError(ValueError): pass


class IncrementalResolver:
    def __init__(self) -> None:
        self.cache: dict[tuple[str,str],dict[str,Any]]={}
        self.calls=0; self.bytes_sent=0; self.tokens_estimate=0

    def resolve(self, artifacts: Sequence[Mapping[str,Any]], binding: Mapping[str,Any],
                completed_lvs: Sequence[str] = ()) -> dict[str,Any]:
        canonical=canonical_bytes(validate_binding(binding)); binding_digest=hashlib.sha256(canonical).hexdigest()
        selected=[]; seen=set(); cache_hits=0
        for artifact in artifacts:
            lv=artifact.get("lv_id")
            if lv in completed_lvs: continue
            raw=canonical_bytes(artifact); digest=hashlib.sha256(raw).hexdigest()
            if digest in seen: continue
            seen.add(digest); key=(binding_digest,digest)
            if key in self.cache: cache_hits+=1; selected.append(self.cache[key]); continue
            item={"sha256":digest,"lv_id":lv,"index":artifact.get("index"),
                  "checkpoint":artifact.get("checkpoint"),"summary":artifact.get("summary","")}
            self.cache[key]=item; selected.append(item); self.calls+=1; self.bytes_sent+=len(canonical_bytes(item))
        self.tokens_estimate=(self.bytes_sent+3)//4
        return {"artifacts":selected,"cache_hits":cache_hits,"calls":self.calls,
                "bytes_sent":self.bytes_sent,"tokens_estimate":self.tokens_estimate,
                "validation":"FULL_BINDING_VALIDATED"}

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_record_payload(event: Mapping[str, Any]) -> bytes:
    payload = {
        key: value
        for key, value in event.items()
        if key not in {"record_hash", "effective_status"}
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def calculate_record_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_record_payload(event)).hexdigest()

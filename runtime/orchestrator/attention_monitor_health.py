"""Durable read-only health receipt for Harness attention discovery."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .durable_io import atomic_write_json
from .production_attention_watch import discover_pending_attention, discover_registered_jobs

SCHEMA = "orchestration.attention-monitor-health.v1"
TERMINAL = {"COMPLETED", "BLOCKED", "CANCELLED", "FAILED", "SUPERSEDED", "RETIRED"}

def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def build_attention_health(search_root: str | Path, *, runtime_source: str = "") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs = discover_registered_jobs(search_root)
    pending = discover_pending_attention(search_root)
    current = [row for row in pending if str(row.get("state") or "") not in TERMINAL]
    unsigned = {
        "schema_version": SCHEMA,
        "observed_at": now,
        "runtime_source": str(runtime_source),
        "search_root": str(Path(search_root).resolve()),
        "registered_job_count": len(jobs),
        "pending_attention_count": len(pending),
        "current_attention_count": len(current),
        "current_event_ids": [str(row.get("event_id") or "") for row in current],
        "status": "HEALTHY" if not current else "ATTENTION_REQUIRED",
    }
    return {**unsigned, "receipt_sha256": _digest(unsigned)}

def write_attention_health(search_root: str | Path, output: str | Path, *, runtime_source: str = "") -> dict[str, Any]:
    receipt = build_attention_health(search_root, runtime_source=runtime_source)
    atomic_write_json(Path(output), receipt)
    return receipt

def main(argv=None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--search-root", required=True); p.add_argument("--output", required=True)
    p.add_argument("--runtime-source", default="")
    a=p.parse_args(argv)
    value=write_attention_health(a.search_root,a.output,runtime_source=a.runtime_source)
    print(json.dumps(value,sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())

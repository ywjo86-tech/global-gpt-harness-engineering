"""Durable operational acceptance layered after Full Plan execution completion."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .durable_io import atomic_write_json
from .operational_post_change_gate import evaluate_post_change_gate

SCHEMA="orchestration.operational-acceptance.v1"

def _digest(v: object)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def evaluate_operational_acceptance(*, diagnostic_config: str|Path, monitor_health_receipt: str|Path,
                                    output: str|Path, stale_after_seconds: int=180) -> dict[str,Any]:
    gate=evaluate_post_change_gate(
        diagnostic_config=diagnostic_config,
        attention_watch_enabled=False,
        timer_watch_enabled=True,
        stale_after_seconds=stale_after_seconds,
        monitor_health_receipt=monitor_health_receipt,
    )
    unsigned={
        "schema_version":SCHEMA,
        "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_state":"COMPLETED",
        "operational_acceptance":"ACCEPTED" if gate["status"]=="PASS" else "BLOCKED",
        "post_change_status":gate["status"],
        "failures":list(gate.get("failures") or []),
        "post_change_gate_sha256":_digest(gate),
    }
    record={**unsigned,"record_sha256":_digest(unsigned)}
    atomic_write_json(Path(output),record)
    return record

def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--diagnostic-config",required=True); p.add_argument("--monitor-health-receipt",required=True)
    p.add_argument("--output",required=True); p.add_argument("--stale-after-seconds",type=int,default=180)
    a=p.parse_args(argv)
    value=evaluate_operational_acceptance(diagnostic_config=a.diagnostic_config,monitor_health_receipt=a.monitor_health_receipt,
                                         output=a.output,stale_after_seconds=a.stale_after_seconds)
    print(json.dumps(value,sort_keys=True))
    return 0 if value["operational_acceptance"]=="ACCEPTED" else 2

if __name__=="__main__": raise SystemExit(main())

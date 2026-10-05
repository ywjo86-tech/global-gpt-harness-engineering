"""Production attention delivery runner.

Outbound-only. It discovers policy-eligible current attention and delivers it
through an explicitly authorized adapter. It has no approve/resume/reroute
authority and fails closed when transport is unconfigured.
"""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attention_delivery import (
    ATTENTION_DELIVERY_UNCONFIGURED,
    AttentionDeliveryReceiptStore,
    HTTPSWebhookV1AttentionDeliveryAdapter,
)
from .durable_io import atomic_write_json
from .production_attention import AttentionOutbox
from .production_attention_watch import discover_pending_attention, discover_registered_jobs

SCHEMA_VERSION="orchestration.attention-delivery-health.v1"
CONTROL_AUTHORITY="NONE"

def _health_digest(value: dict[str, Any]) -> str:
    unsigned={k:v for k,v in value.items() if k!="health_sha256"}
    return hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

def validate_attention_delivery_health(value: dict[str, Any]) -> dict[str, Any]:
    required={"schema_version","observed_at","runtime_source_identity","status","current_eligible_count",
              "historical_unresolved_count","delivered_count","error_count","errors","control_authority","health_sha256"}
    if not isinstance(value,dict) or set(value)!=required:
        raise ValueError("attention delivery health shape mismatch")
    if value.get("schema_version")!=SCHEMA_VERSION or value.get("control_authority")!=CONTROL_AUTHORITY:
        raise ValueError("attention delivery health schema/authority mismatch")
    if not isinstance(value.get("runtime_source_identity"),str) or not value["runtime_source_identity"]:
        raise ValueError("attention delivery runtime identity missing")
    if value.get("health_sha256")!=_health_digest(value):
        raise ValueError("attention delivery health digest mismatch")
    return dict(value)

_TERMINAL_BLOCKING={"BLOCKED","FAILED"}
_TERMINAL_HISTORICAL={"COMPLETED","CANCELLED","SUPERSEDED","RETIRED"}


def partition_current_attention(search_root: str | Path, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jobs=discover_registered_jobs(search_root)
    latest: dict[str, tuple[int,str]]={}
    for job in jobs:
        try: registered_ns=Path(job["job_path"]).stat().st_mtime_ns
        except OSError: registered_ns=-1
        project=str(job["project_id"])
        if project not in latest or registered_ns>latest[project][0]:
            latest[project]=(registered_ns,str(job["run_id"]))
    current=[]; historical=[]
    for row in rows:
        state=str(row.get("state") or "")
        latest_run=latest.get(str(row.get("project_id") or ""),(-1,""))[1]
        is_current=(state not in _TERMINAL_BLOCKING|_TERMINAL_HISTORICAL
                    or (state in _TERMINAL_BLOCKING and str(row.get("run_id") or "")==latest_run))
        (current if is_current else historical).append(row)
    return current,historical


def run_once(*, search_root: str | Path, runtime_source_identity: str, endpoint: str="", allowlisted_endpoint: str="", secret_ref: str="",
             transport_authorized: bool=False, secret_value: str="", output_path: str | Path | None=None) -> dict[str,Any]:
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    runtime_source_identity=str(runtime_source_identity or "").strip()
    if not runtime_source_identity: raise ValueError("runtime source identity required")
    rows=discover_pending_attention(search_root)
    current,historical=partition_current_attention(search_root,rows)
    status=ATTENTION_DELIVERY_UNCONFIGURED
    delivered=[]; errors=[]
    adapter=None
    if endpoint and allowlisted_endpoint and secret_ref:
        adapter=HTTPSWebhookV1AttentionDeliveryAdapter(
            endpoint=endpoint,allowlisted_endpoints=(allowlisted_endpoint,),secret_ref=secret_ref,
            transport_authorized=transport_authorized,
            secret_loader=(lambda ref: secret_value) if secret_value else None,
        )
        status=adapter.status
    if adapter is not None and status=="READY":
        jobs={(j["project_id"],j["run_id"]):j for j in discover_registered_jobs(search_root)}
        eligible={str(row.get("event_id") or "") for row in current}
        for row in current:
            key=(str(row.get("project_id") or ""),str(row.get("run_id") or ""))
            job=jobs.get(key)
            if job is None:
                errors.append({"project_id":key[0],"run_id":key[1],"error":"REGISTERED_JOB_NOT_FOUND"}); continue
            run_base=Path(job["harness_state_root"])/"_workspace"/"production-full-plan"/key[0]/key[1]
            try:
                outbox=AttentionOutbox(run_base,project_id=key[0],run_id=key[1])
                store=AttentionDeliveryReceiptStore(run_base,project_id=key[0],run_id=key[1])
                delivered.extend(outbox.deliver_with_adapter(adapter,receipt_store=store,channel="https-webhook-v1",eligible_event_ids=eligible))
            except Exception as exc:
                errors.append({"project_id":key[0],"run_id":key[1],"error":type(exc).__name__})
        status="PASS" if not errors else "BLOCKED"
    result={
        "schema_version":SCHEMA_VERSION,"observed_at":now,"runtime_source_identity":runtime_source_identity,"status":status,
        "current_eligible_count":len(current),"historical_unresolved_count":len(historical),
        "delivered_count":len(set(delivered)),"error_count":len(errors),"errors":errors,
        "control_authority":CONTROL_AUTHORITY,
    }
    result["health_sha256"]=_health_digest(result)
    result=validate_attention_delivery_health(result)
    if output_path is not None: atomic_write_json(Path(output_path),result)
    return result


def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--search-root",required=True); p.add_argument("--output",required=True); p.add_argument("--runtime-source",required=True)
    p.add_argument("--endpoint",default=os.environ.get("ATTENTION_DELIVERY_ENDPOINT",""))
    p.add_argument("--allowlisted-endpoint",default=os.environ.get("ATTENTION_DELIVERY_ALLOWLISTED_ENDPOINT",""))
    p.add_argument("--secret-ref",default=os.environ.get("ATTENTION_DELIVERY_SECRET_REF",""))
    p.add_argument("--secret-env",default="ATTENTION_DELIVERY_TOKEN")
    p.add_argument("--transport-authorized",action="store_true",default=os.environ.get("ATTENTION_DELIVERY_AUTHORIZED")=="1")
    a=p.parse_args(argv)
    result=run_once(search_root=a.search_root,runtime_source_identity=a.runtime_source,endpoint=a.endpoint,allowlisted_endpoint=a.allowlisted_endpoint,
                    secret_ref=a.secret_ref,transport_authorized=a.transport_authorized,
                    secret_value=os.environ.get(a.secret_env,""),output_path=a.output)
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())

"""Periodic read-only operational health scan and durable acceptance projection."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from .monitor_health import build_monitor_health_receipt, record_monitor_health_receipt
from .operational_acceptance import build_operational_acceptance_record, OperationalAcceptanceStore
from .operational_post_change_gate import evaluate_post_change_gate
from .production_attention_watch import discover_pending_attention, discover_registered_jobs
from .user_service_observer import UserServiceObserver

_TERMINAL={"COMPLETED","BLOCKED","FAILED","CANCELLED","SUPERSEDED","RETIRED"}

def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--state-root",required=True); p.add_argument("--search-root",required=True)
    p.add_argument("--diagnostic-config",required=True); p.add_argument("--runtime-source",required=True)
    p.add_argument("--project-id",required=True); p.add_argument("--run-id",required=True)
    p.add_argument("--output-root",required=True); p.add_argument("--stale-after-seconds",type=int,default=180)
    a=p.parse_args(argv)
    now=datetime.now(timezone.utc)
    out=Path(a.output_root); out.mkdir(parents=True,exist_ok=True)
    jobs=discover_registered_jobs(a.search_root)
    attention=discover_pending_attention(a.search_root,now=now)
    current=[x for x in attention if str(x.get("state") or "") not in _TERMINAL]
    ar=build_monitor_health_receipt(monitor_name="ATTENTION_HEALTH",runtime_source_identity=a.runtime_source,
        search_root=a.search_root,registered_job_count=len(jobs),pending_current_event_count=len(current),
        result="PASS" if not current else "BLOCKED")
    ap=out/"attention-health.json"; record_monitor_health_receipt(ap,ar)
    obs=UserServiceObserver(allowed_units=frozenset({"global-gpt-harness-full-plan-reconcile.timer","global-gpt-harness-full-plan-reconcile.service"}))
    timer=obs.read("global-gpt-harness-full-plan-reconcile.timer")
    svc=obs.read("global-gpt-harness-full-plan-reconcile.service")
    timer_ok=(timer.get("ActiveState")=="active" and timer.get("SubState") in {"waiting","running"}
              and timer.get("Result")=="success" and svc.get("Result")=="success" and svc.get("ExecMainStatus")=="0")
    tr=build_monitor_health_receipt(monitor_name="RECONCILE_TIMER_HEALTH",runtime_source_identity=a.runtime_source,
        search_root=a.search_root,registered_job_count=len(jobs),pending_current_event_count=0,
        result="PASS" if timer_ok else "BLOCKED")
    tp=out/"reconcile-timer-health.json"; record_monitor_health_receipt(tp,tr)
    gate=evaluate_post_change_gate(diagnostic_config=a.diagnostic_config,attention_watch_enabled=True,timer_watch_enabled=True,
        attention_health_receipt=ap,timer_health_receipt=tp,stale_after_seconds=a.stale_after_seconds,now=now)
    (out/"post-change-gate.json").write_text(json.dumps(gate,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
    state_path=Path(a.state_root)/"_workspace"/"production-full-plan"/a.project_id/a.run_id/"state.json"
    state=json.loads(state_path.read_text(encoding="utf-8"))
    rec=build_operational_acceptance_record(project_id=a.project_id,run_id=a.run_id,
        full_plan_terminal_state=state,post_change_gate=gate,
        monitor_health_receipt_refs=(str(ap),str(tp)),
        runtime_release_identity_refs=(a.runtime_source,))
    OperationalAcceptanceStore(a.state_root).save_once(rec)
    (out/"operational-acceptance.json").write_text(json.dumps(rec.to_dict(),sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({"post_change":gate["status"],"operational_acceptance":rec.status,
        "current_attention":len(current),"record_sha256":rec.record_sha256},sort_keys=True))
    return 0 if rec.status=="ACCEPTED" else 2

if __name__=="__main__": raise SystemExit(main())

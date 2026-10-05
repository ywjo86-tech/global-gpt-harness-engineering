"""Periodic read-only operational health scan and durable acceptance projection."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .monitor_health import build_monitor_health_receipt, record_monitor_health_receipt
from .operational_acceptance import build_operational_acceptance_record, OperationalAcceptanceStore
from .operational_post_change_gate import evaluate_post_change_gate
from .operations_current_attention import (
    build_current_attention_projection,
    record_current_attention_projection,
)
from .operational_system_acceptance import (
    build_operational_system_acceptance,
    record_operational_system_acceptance,
)
from .operational_blockers import (
    blocking_attention_events,
    current_registered_job_keys,
    discover_current_state_blockers,
    merge_operational_blockers,
)
from .production_attention_watch import discover_pending_attention, discover_registered_jobs
from .user_service_observer import UserServiceObserver
from runtime.diagnostics.process_lifecycle import record_process_lifecycle_snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-root", required=True)
    p.add_argument("--search-root", required=True)
    p.add_argument("--diagnostic-config", required=True)
    p.add_argument("--runtime-source", required=True)
    p.add_argument(
        "--expected-runtime-source",
        help=(
            "Runtime identity that monitor receipts must represent. "
            "Defaults to --runtime-source for backward compatibility."
        ),
    )
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--stale-after-seconds", type=int, default=180)
    a = p.parse_args(argv)

    now = datetime.now(timezone.utc)
    expected_runtime = str(a.expected_runtime_source or a.runtime_source).strip()
    out = Path(a.output_root)
    out.mkdir(parents=True, exist_ok=True)

    jobs = discover_registered_jobs(a.search_root)
    current_jobs = current_registered_job_keys(jobs)
    attention = discover_pending_attention(a.search_root, now=now)
    attention_blockers = blocking_attention_events(
        attention,
        current_job_keys=current_jobs,
    )
    state_blockers = discover_current_state_blockers(jobs)
    operational_blockers = merge_operational_blockers(
        attention_blockers,
        state_blockers,
    )

    current_attention = build_current_attention_projection(
        runtime_source_identity=a.runtime_source,
        blockers=operational_blockers,
        observed_at=now,
    )
    current_attention_path = out / "current-attention.json"
    record_current_attention_projection(current_attention_path, current_attention)

    ar = build_monitor_health_receipt(
        monitor_name="ATTENTION_HEALTH",
        runtime_source_identity=a.runtime_source,
        search_root=a.search_root,
        registered_job_count=len(jobs),
        pending_current_event_count=len(operational_blockers),
        result="PASS" if not operational_blockers else "BLOCKED",
        evidence_refs=tuple(
            str(item.get("event_id") or "")
            for item in operational_blockers
            if str(item.get("event_id") or "")
        ),
        scanned_at=now.isoformat(timespec="seconds"),
    )
    ap = out / "attention-health.json"
    record_monitor_health_receipt(ap, ar)

    obs = UserServiceObserver(
        allowed_units=frozenset(
            {
                "global-gpt-harness-full-plan-reconcile.timer",
                "global-gpt-harness-full-plan-reconcile.service",
            }
        )
    )
    timer = obs.read("global-gpt-harness-full-plan-reconcile.timer")
    svc = obs.read("global-gpt-harness-full-plan-reconcile.service")
    timer_ok = (
        timer.get("ActiveState") == "active"
        and timer.get("SubState") in {"waiting", "running"}
        and timer.get("Result") == "success"
        and svc.get("Result") == "success"
        and svc.get("ExecMainStatus") == "0"
    )
    tr = build_monitor_health_receipt(
        monitor_name="RECONCILE_TIMER_HEALTH",
        runtime_source_identity=a.runtime_source,
        search_root=a.search_root,
        registered_job_count=len(jobs),
        pending_current_event_count=0,
        result="PASS" if timer_ok else "BLOCKED",
        scanned_at=now.isoformat(timespec="seconds"),
    )
    tp = out / "reconcile-timer-health.json"
    record_monitor_health_receipt(tp, tr)

    process_snapshot = record_process_lifecycle_snapshot(
        a.state_root, observed_at=now.isoformat(timespec="seconds")
    )
    process_snapshot_path = (
        Path(a.state_root)
        / "_workspace"
        / "operations-health"
        / "process-lifecycle-latest.json"
    )

    gate = evaluate_post_change_gate(
        diagnostic_config=a.diagnostic_config,
        attention_watch_enabled=True,
        timer_watch_enabled=True,
        attention_health_receipt=ap,
        timer_health_receipt=tp,
        process_lifecycle_snapshot=process_snapshot_path,
        expected_runtime_source_identity=expected_runtime,
        stale_after_seconds=a.stale_after_seconds,
        now=now,
    )
    (out / "post-change-gate.json").write_text(
        json.dumps(gate, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    state_path = (
        Path(a.state_root)
        / "_workspace"
        / "production-full-plan"
        / a.project_id
        / a.run_id
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    rec = build_operational_acceptance_record(
        project_id=a.project_id,
        run_id=a.run_id,
        full_plan_terminal_state=state,
        post_change_gate=gate,
        monitor_health_receipt_refs=(str(ap), str(tp)),
        process_lifecycle_diagnostic_refs=(str(process_snapshot_path),),
        runtime_release_identity_refs=(a.runtime_source,),
    )
    store = OperationalAcceptanceStore(a.state_root)
    rec = store.save_observation(rec)
    (out / "operational-acceptance.json").write_text(
        json.dumps(rec.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    system_rec = build_operational_system_acceptance(
        runtime_source_identity=a.runtime_source,
        expected_runtime_source_identity=expected_runtime,
        registered_project_count=len(current_jobs),
        post_change_gate=gate,
        current_attention_projection=current_attention,
        monitor_health_receipt_refs=(str(ap), str(tp)),
        process_lifecycle_diagnostic_refs=(str(process_snapshot_path),),
        created_at=now.isoformat(timespec="seconds"),
    )
    system_path = record_operational_system_acceptance(
        a.state_root,
        system_rec,
    )

    print(
        json.dumps(
            {
                "post_change": gate["status"],
                "operational_acceptance": rec.status,
                "system_acceptance": system_rec.status,
                "blocking_attention": len(operational_blockers),
                "process_lifecycle_blocking": process_snapshot["blocking_count"],
                "runtime_source": a.runtime_source,
                "expected_runtime_source": expected_runtime,
                "attention_projection": str(current_attention_path),
                "system_acceptance_path": str(system_path),
                "record_sha256": rec.record_sha256,
                "system_record_sha256": system_rec.record_sha256,
            },
            sort_keys=True,
        )
    )
    return 0 if system_rec.status == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

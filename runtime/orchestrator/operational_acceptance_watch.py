"""Periodic read-only operational health scan and durable acceptance projection."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .monitor_health import build_monitor_health_receipt, record_monitor_health_receipt
from .operational_acceptance import build_operational_acceptance_record, OperationalAcceptanceStore
from .operational_post_change_gate import evaluate_post_change_gate
from .production_attention_watch import discover_pending_attention, discover_registered_jobs
from .user_service_observer import UserServiceObserver
from runtime.diagnostics.process_lifecycle import record_process_lifecycle_snapshot


# Terminal success/retirement states do not require a live user interruption.
# BLOCKED and FAILED are deliberately excluded: an unresolved attention event in
# either state is an operational blocker even though the Full Plan run itself is
# terminal.
_NON_ACTIONABLE_ATTENTION_STATES = frozenset({
    "COMPLETED",
    "CANCELLED",
    "SUPERSEDED",
    "RETIRED",
})


def current_registered_job_keys(
    jobs: Sequence[Mapping[str, Any]],
) -> frozenset[tuple[str, str]]:
    """Return one latest registered run per project using canonical job-file mtime."""
    latest: dict[str, tuple[int, str]] = {}
    for job in jobs:
        project_id = str(job.get("project_id") or "")
        run_id = str(job.get("run_id") or "")
        job_path = Path(str(job.get("job_path") or ""))
        if not project_id or not run_id or not job_path.is_file() or job_path.is_symlink():
            continue
        try:
            registered_ns = job_path.stat().st_mtime_ns
        except OSError:
            continue
        candidate = (registered_ns, run_id)
        previous = latest.get(project_id)
        if previous is None or candidate > previous:
            latest[project_id] = candidate
    return frozenset((project_id, value[1]) for project_id, value in latest.items())


def blocking_attention_events(
    attention_events: Sequence[Mapping[str, Any]],
    *,
    current_job_keys: frozenset[tuple[str, str]] | None = None,
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for item in attention_events:
        state = str(item.get("state") or "").upper()
        if state in _NON_ACTIONABLE_ATTENTION_STATES:
            continue
        if current_job_keys is not None:
            identity = (
                str(item.get("project_id") or ""),
                str(item.get("run_id") or ""),
            )
            if identity not in current_job_keys:
                continue
        rows.append(item)
    return rows


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
    blocking_attention = blocking_attention_events(
        attention,
        current_job_keys=current_jobs,
    )

    ar = build_monitor_health_receipt(
        monitor_name="ATTENTION_HEALTH",
        runtime_source_identity=a.runtime_source,
        search_root=a.search_root,
        registered_job_count=len(jobs),
        pending_current_event_count=len(blocking_attention),
        result="PASS" if not blocking_attention else "BLOCKED",
        evidence_refs=tuple(
            str(item.get("event_id") or "")
            for item in blocking_attention
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
    print(
        json.dumps(
            {
                "post_change": gate["status"],
                "operational_acceptance": rec.status,
                "blocking_attention": len(blocking_attention),
                "process_lifecycle_blocking": process_snapshot["blocking_count"],
                "runtime_source": a.runtime_source,
                "expected_runtime_source": expected_runtime,
                "record_sha256": rec.record_sha256,
            },
            sort_keys=True,
        )
    )
    return 0 if rec.status == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

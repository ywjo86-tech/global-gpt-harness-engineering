"""Read-only AI Office operational post-change gate.

The gate never starts, stops, restarts, approves, resumes, or mutates work.  It
answers one question after an operational change: is the control/execution/
monitoring chain healthy enough to declare the change operationally complete?
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .monitor_health import evaluate_monitor_health_receipt
from .read_only_host_diagnostic_contract import DiagnosticContractError, DiagnosticPolicy
from .user_service_observer import UserServiceObserver, UserServiceObserverError

OCP_SERVICE = "ocpv2.service"
OCP_TIMER = "ocpv2.timer"
HOST_RUNNER_SERVICE = "ocpv2-host-runner.service"
RECONCILE_SERVICE = "global-gpt-harness-full-plan-reconcile.service"
RECONCILE_TIMER = "global-gpt-harness-full-plan-reconcile.timer"

OBSERVED_UNITS = frozenset({
    OCP_SERVICE, OCP_TIMER, HOST_RUNNER_SERVICE, RECONCILE_SERVICE, RECONCILE_TIMER,
})
REQUIRED_DIAGNOSTIC_UNITS = frozenset({
    OCP_SERVICE, OCP_TIMER, RECONCILE_SERVICE, RECONCILE_TIMER,
})


def _parse_systemd_local_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("LAST_TRIGGER_MISSING")
    # systemctl renders a local timestamp followed by a timezone abbreviation.
    body = text.rsplit(" ", 1)[0]
    return datetime.strptime(body, "%a %Y-%m-%d %H:%M:%S")


def _timer_check(
    name: str, data: dict[str, str], *, now: datetime, stale_after_seconds: int,
) -> dict[str, Any]:
    failures: list[str] = []
    if data.get("ActiveState") != "active" or data.get("SubState") not in {"waiting", "running"}:
        failures.append(f"{name}:NOT_ACTIVE")
    if data.get("Result") != "success":
        failures.append(f"{name}:RESULT_NOT_SUCCESS")
    age_seconds: float | None = None
    try:
        local_now = now.astimezone().replace(tzinfo=None) if now.tzinfo is not None else now
        age_seconds = max(0.0, (local_now - _parse_systemd_local_timestamp(data.get("LastTriggerUSec", ""))).total_seconds())
        if age_seconds > stale_after_seconds:
            failures.append(f"{name}:TRIGGER_STALE")
    except ValueError:
        failures.append(f"{name}:TRIGGER_UNAVAILABLE")
    return {"unit": name, "data": data, "age_seconds": age_seconds, "failures": failures}


def _oneshot_service_check(name: str, data: dict[str, str]) -> dict[str, Any]:
    failures: list[str] = []
    if data.get("Result") != "success" or data.get("ExecMainStatus") != "0":
        failures.append(f"{name}:LAST_RUN_FAILED")
    return {"unit": name, "data": data, "failures": failures}


def _resident_service_check(name: str, data: dict[str, str]) -> dict[str, Any]:
    result = _oneshot_service_check(name, data)
    if data.get("ActiveState") != "active" or data.get("SubState") != "running":
        result["failures"].append(f"{name}:NOT_RUNNING")
    return result


def evaluate_post_change_gate(
    *,
    diagnostic_config: str | Path,
    attention_watch_enabled: bool,
    timer_watch_enabled: bool,
    attention_health_receipt: dict[str, Any] | str | Path | None = None,
    timer_health_receipt: dict[str, Any] | str | Path | None = None,
    stale_after_seconds: int = 180,
    observer: UserServiceObserver | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if stale_after_seconds <= 0:
        raise ValueError("STALE_THRESHOLD_INVALID")
    current = now or datetime.now(timezone.utc)
    probe = observer or UserServiceObserver(allowed_units=OBSERVED_UNITS)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    try:
        observed = {unit: probe.read(unit) for unit in OBSERVED_UNITS}
    except UserServiceObserverError as exc:
        return {
            "schema_version": "ai-office.operational-post-change-gate.v1",
            "status": "BLOCKED",
            "failures": [f"SERVICE_OBSERVATION_FAILED:{exc}"],
            "checks": [],
        }

    checks.extend([
        _timer_check(OCP_TIMER, observed[OCP_TIMER], now=current, stale_after_seconds=stale_after_seconds),
        _oneshot_service_check(OCP_SERVICE, observed[OCP_SERVICE]),
        _resident_service_check(HOST_RUNNER_SERVICE, observed[HOST_RUNNER_SERVICE]),
        _timer_check(RECONCILE_TIMER, observed[RECONCILE_TIMER], now=current, stale_after_seconds=stale_after_seconds),
        _oneshot_service_check(RECONCILE_SERVICE, observed[RECONCILE_SERVICE]),
    ])
    for item in checks:
        failures.extend(item["failures"])

    try:
        policy = DiagnosticPolicy.load(diagnostic_config)
        missing = sorted(REQUIRED_DIAGNOSTIC_UNITS.difference(policy.user_services))
    except DiagnosticContractError as exc:
        missing = sorted(REQUIRED_DIAGNOSTIC_UNITS)
        failures.append(f"DIAGNOSTIC_POLICY_INVALID:{exc}")
    if missing:
        failures.append("DIAGNOSTIC_COVERAGE_MISSING:" + ",".join(missing))

    monitor_receipts: dict[str, Any] = {}
    monitor_now = current.astimezone(timezone.utc) if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)
    attention_receipt, attention_failures = evaluate_monitor_health_receipt(
        attention_health_receipt,
        monitor_name="ATTENTION_HEALTH",
        now=monitor_now,
        fresh_after_seconds=stale_after_seconds,
    )
    timer_receipt, timer_failures = evaluate_monitor_health_receipt(
        timer_health_receipt,
        monitor_name="RECONCILE_TIMER_HEALTH",
        now=monitor_now,
        fresh_after_seconds=stale_after_seconds,
    )
    if attention_receipt is not None:
        monitor_receipts["attention_health"] = attention_receipt
    if timer_receipt is not None:
        monitor_receipts["reconcile_timer_health"] = timer_receipt
    failures.extend(attention_failures)
    failures.extend(timer_failures)

    legacy_compatibility: list[str] = []
    if attention_health_receipt is None and attention_watch_enabled:
        legacy_compatibility.append("ATTENTION_WATCH_BOOLEAN_COMPAT_ONLY")
    if timer_health_receipt is None and timer_watch_enabled:
        legacy_compatibility.append("RECONCILE_TIMER_WATCH_BOOLEAN_COMPAT_ONLY")
    if not attention_watch_enabled:
        failures.append("ATTENTION_WATCH_DISABLED")
    if not timer_watch_enabled:
        failures.append("RECONCILE_TIMER_WATCH_DISABLED")

    result = {
        "schema_version": "ai-office.operational-post-change-gate.v1",
        "status": "PASS" if not failures else "BLOCKED",
        "stale_after_seconds": stale_after_seconds,
        "checks": checks,
        "diagnostic_required_units": sorted(REQUIRED_DIAGNOSTIC_UNITS),
        "diagnostic_missing_units": missing,
        "monitor_health_receipts": monitor_receipts,
        "legacy_monitor_compatibility": legacy_compatibility,
        "external_monitors": {
            "attention_watch_enabled": bool(attention_watch_enabled),
            "reconcile_timer_watch_enabled": bool(timer_watch_enabled),
        },
        "failures": failures,
    }
    result["gate_evidence_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the read-only AI Office post-change operational gate")
    parser.add_argument("--diagnostic-config", required=True)
    parser.add_argument("--attention-watch-enabled", action="store_true")
    parser.add_argument("--timer-watch-enabled", action="store_true")
    parser.add_argument("--attention-health-receipt")
    parser.add_argument("--timer-health-receipt")
    parser.add_argument("--stale-after-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    result = evaluate_post_change_gate(
        diagnostic_config=args.diagnostic_config,
        attention_watch_enabled=args.attention_watch_enabled,
        timer_watch_enabled=args.timer_watch_enabled,
        attention_health_receipt=args.attention_health_receipt,
        timer_health_receipt=args.timer_health_receipt,
        stale_after_seconds=args.stale_after_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

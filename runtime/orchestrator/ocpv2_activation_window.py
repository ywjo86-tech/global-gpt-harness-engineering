"""Controlled OCPv2 Full Plan activation window with deterministic timer cleanup.

The persistent OCP environment remains activation-OFF. Only the bounded POLL step
receives an ephemeral 0600 env-file copy with executable activation enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .durable_io import atomic_write_json, canonical_json_bytes

ACTIVATION_WINDOW_SCHEMA_V1 = "orchestration.ocpv2-controlled-activation-window.v1"
DEFAULT_RECONCILE_TIMER = "global-gpt-harness-full-plan-reconcile.timer"
DEFAULT_OCP_TIMER = "ocpv2.timer"
ACTIVATION_FLAG = "OCP_FULL_PLAN_ACTIVATION_ENABLED"
ACTIVATION_POLICY_REF = "OCP_FULL_PLAN_ACTIVATION_POLICY_REF"
OCP_MODE = "OCP_MODE"
WINDOW_FILENAME = "ocpv2-activation-window.json"
WATCHDOG_PREFIX = "gch-ocpv2-activation-window-recovery"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_LIVE_STATUSES = {"OPEN", "ACTIVE", "RECOVERY_REQUIRED"}
_CLOSED_STATUSES = {"CLOSED", "CLOSED_AFTER_FAILURE", "RECOVERED"}


class OCPActivationWindowError(ValueError):
    pass


class UserServiceController(Protocol):
    def is_active(self, unit: str) -> bool: ...
    def stop(self, unit: str) -> None: ...
    def start(self, unit: str) -> None: ...


class RecoveryScheduler(Protocol):
    def schedule(
        self,
        *,
        window_id: str,
        delay_seconds: int,
        state_root: Path,
        env_file: Path,
    ) -> str: ...


@dataclass(slots=True)
class SystemdUserServiceController:
    timeout_seconds: int = 20

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["systemctl", "--user", *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )

    def is_active(self, unit: str) -> bool:
        result = self._run("is-active", unit, check=False)
        return result.returncode == 0 and result.stdout.strip() == "active"

    def stop(self, unit: str) -> None:
        self._run("stop", unit)

    def start(self, unit: str) -> None:
        self._run("start", unit)


@dataclass(slots=True)
class SystemdTransientRecoveryScheduler:
    timeout_seconds: int = 20

    def schedule(
        self,
        *,
        window_id: str,
        delay_seconds: int,
        state_root: Path,
        env_file: Path,
    ) -> str:
        safe_window = re.sub(r"[^A-Za-z0-9_.-]+", "-", window_id)[:80].strip("-")
        if not safe_window:
            raise OCPActivationWindowError("watchdog window id invalid")
        unit = f"{WATCHDOG_PREFIX}-{safe_window}"
        repo_root = Path(__file__).resolve().parents[2]
        pythonpath = str(repo_root)
        existing_pythonpath = os.environ.get("PYTHONPATH", "").strip()
        if existing_pythonpath:
            pythonpath += os.pathsep + existing_pythonpath
        command = [
            "systemd-run",
            "--user",
            f"--unit={unit}",
            f"--on-active={int(delay_seconds)}s",
            "--collect",
            f"--working-directory={repo_root}",
            f"--setenv=PYTHONPATH={pythonpath}",
            sys.executable,
            "-m",
            "runtime.orchestrator.ocpv2_activation_window",
            "recover",
            "--state-root",
            str(state_root),
            "--env-file",
            str(env_file),
            "--force",
        ]
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        return unit


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise OCPActivationWindowError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OCPActivationWindowError(f"{label} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OCPActivationWindowError(f"{label} invalid") from exc
    if parsed.tzinfo is None:
        raise OCPActivationWindowError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _seal(payload: Mapping[str, object]) -> dict[str, object]:
    unsigned = {key: value for key, value in payload.items() if key != "record_sha256"}
    digest = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    return {**unsigned, "record_sha256": digest}


def _validate_record(value: Mapping[str, object]) -> dict[str, object]:
    record = dict(value)
    if record.get("schema_version") != ACTIVATION_WINDOW_SCHEMA_V1:
        raise OCPActivationWindowError("activation window schema mismatch")
    digest = record.get("record_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise OCPActivationWindowError("activation window digest missing")
    if digest != _seal(record)["record_sha256"]:
        raise OCPActivationWindowError("activation window digest mismatch")
    _parse_time(record.get("opened_at"), "opened_at")
    _parse_time(record.get("expires_at"), "expires_at")
    if record.get("status") not in _LIVE_STATUSES | _CLOSED_STATUSES:
        raise OCPActivationWindowError("activation window status invalid")
    timers = record.get("timers")
    if not isinstance(timers, dict) or not timers:
        raise OCPActivationWindowError("activation window timer snapshot missing")
    if any(not isinstance(k, str) or not isinstance(v, bool) for k, v in timers.items()):
        raise OCPActivationWindowError("activation window timer snapshot invalid")
    if record.get("persistent_activation_flag") != "0":
        raise OCPActivationWindowError("persistent activation flag baseline must be 0")
    failures = record.get("cleanup_failures")
    if not isinstance(failures, list) or any(not isinstance(item, str) for item in failures):
        raise OCPActivationWindowError("activation window cleanup failures invalid")
    return record


def activation_window_path(state_root: str | Path) -> Path:
    root = Path(state_root).expanduser().absolute()
    if root.exists() and root.is_symlink():
        raise OCPActivationWindowError("state root symlink refused")
    return root / "operations-v2" / WINDOW_FILENAME


def _read_env_lines(env_file: Path) -> list[str]:
    if env_file.is_symlink() or not env_file.is_file():
        raise OCPActivationWindowError("unsafe or missing OCP env file")
    try:
        return env_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise OCPActivationWindowError("OCP env file unreadable") from exc


def _env_map(env_file: str | Path) -> dict[str, str]:
    path = Path(env_file).expanduser().absolute()
    result: dict[str, str] = {}
    for raw in _read_env_lines(path):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OCPActivationWindowError("malformed OCP env line")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in result:
            raise OCPActivationWindowError("duplicate/empty OCP env key")
        result[key] = value.strip()
    return result


def activation_flag_value(env_file: str | Path) -> str:
    value = _env_map(env_file).get(ACTIVATION_FLAG)
    if value is None:
        raise OCPActivationWindowError("activation flag missing")
    return value


def _validate_persistent_activation_baseline(env_file: str | Path) -> dict[str, str]:
    values = _env_map(env_file)
    if values.get(ACTIVATION_FLAG) != "0":
        raise OCPActivationWindowError("persistent activation flag baseline must be 0")
    if values.get(OCP_MODE) != "ACTIVE":
        raise OCPActivationWindowError("OCP_MODE must be ACTIVE for executable activation")
    policy_ref = str(values.get(ACTIVATION_POLICY_REF) or "").strip()
    if not policy_ref or not _SAFE_ID.fullmatch(policy_ref):
        raise OCPActivationWindowError("exact Full Plan activation policy ref required")
    return values


def _write_record(path: Path, payload: Mapping[str, object]) -> dict[str, object]:
    sealed = _seal(payload)
    atomic_write_json(path, sealed)
    return sealed


def load_activation_window(state_root: str | Path) -> dict[str, object] | None:
    path = activation_window_path(state_root)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OCPActivationWindowError("unsafe activation window marker")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OCPActivationWindowError("activation window marker unreadable") from exc
    if not isinstance(value, dict):
        raise OCPActivationWindowError("activation window marker invalid")
    return _validate_record(value)


def _timer_snapshot(controller: UserServiceController, timers: tuple[str, ...]) -> dict[str, bool]:
    if not timers or len(set(timers)) != len(timers):
        raise OCPActivationWindowError("unique timer list required")
    return {unit: bool(controller.is_active(unit)) for unit in timers}


def _restore_timers(
    controller: UserServiceController,
    timers: Mapping[str, bool],
) -> list[str]:
    failures: list[str] = []
    for unit, was_active in timers.items():
        if not was_active:
            continue
        try:
            if not controller.is_active(unit):
                controller.start(unit)
        except Exception as exc:
            failures.append(f"{unit}:{type(exc).__name__}")
    return failures


def _cleanup_ephemeral_env_files(state_root: str | Path) -> list[str]:
    failures: list[str] = []
    base = activation_window_path(state_root).parent
    if not base.exists():
        return failures
    for path in base.glob(".ocpv2-activation-*.env"):
        try:
            if path.is_symlink() or not path.is_file():
                failures.append(f"{path.name}:UNSAFE")
                continue
            path.unlink()
        except OSError as exc:
            failures.append(f"{path.name}:{type(exc).__name__}")
    return failures


def _finalize_window(
    *,
    record: Mapping[str, object],
    state_root: str | Path,
    controller: UserServiceController,
    now: datetime,
    outcome: str,
    successful_status: str,
) -> dict[str, object]:
    failures = _cleanup_ephemeral_env_files(state_root)
    failures.extend(_restore_timers(controller, record["timers"]))
    status = successful_status if not failures else "RECOVERY_REQUIRED"
    updated = _write_record(
        activation_window_path(state_root),
        {
            **record,
            "status": status,
            "closed_at": _iso(now),
            "outcome": outcome if not failures else f"{outcome}_CLEANUP_INCOMPLETE",
            "cleanup_failures": failures,
        },
    )
    if failures:
        raise OCPActivationWindowError("activation window cleanup incomplete")
    return updated


def open_activation_window(
    *,
    state_root: str | Path,
    env_file: str | Path,
    controller: UserServiceController | None = None,
    scheduler: RecoveryScheduler | None = None,
    timers: tuple[str, ...] = (DEFAULT_RECONCILE_TIMER, DEFAULT_OCP_TIMER),
    now: datetime | None = None,
    max_seconds: int = 300,
    window_id: str | None = None,
) -> dict[str, object]:
    if max_seconds <= 0 or max_seconds > 1800:
        raise OCPActivationWindowError("activation window max_seconds out of range")
    current = (now or _utc_now()).astimezone(timezone.utc)
    prior = load_activation_window(state_root)
    if prior is not None and prior["status"] in _LIVE_STATUSES:
        raise OCPActivationWindowError("unfinished activation window requires recovery")
    _validate_persistent_activation_baseline(env_file)
    stale_env_failures = _cleanup_ephemeral_env_files(state_root)
    if stale_env_failures:
        raise OCPActivationWindowError("stale ephemeral activation env cleanup failed")

    service = controller or SystemdUserServiceController()
    recovery = scheduler or SystemdTransientRecoveryScheduler()
    snapshot = _timer_snapshot(service, timers)
    identifier = window_id or f"OCP-ACT-{current.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
    marker = activation_window_path(state_root)
    record = _write_record(
        marker,
        {
            "schema_version": ACTIVATION_WINDOW_SCHEMA_V1,
            "window_id": identifier,
            "status": "OPEN",
            "opened_at": _iso(current),
            "expires_at": _iso(current + timedelta(seconds=max_seconds)),
            "persistent_activation_flag": "0",
            "timers": snapshot,
            "watchdog_unit": "",
            "poll_count": 0,
            "outcome": "PENDING",
            "cleanup_failures": [],
        },
    )
    try:
        watchdog = recovery.schedule(
            window_id=identifier,
            delay_seconds=max_seconds,
            state_root=Path(state_root).expanduser().absolute(),
            env_file=Path(env_file).expanduser().absolute(),
        )
        record = _write_record(marker, {**record, "watchdog_unit": watchdog})
        for unit, was_active in snapshot.items():
            if was_active:
                service.stop(unit)
        return _write_record(marker, {**record, "status": "ACTIVE"})
    except BaseException:
        try:
            _finalize_window(
                record=record,
                state_root=state_root,
                controller=service,
                now=_utc_now(),
                outcome="OPEN_FAILED",
                successful_status="CLOSED_AFTER_FAILURE",
            )
        finally:
            raise


def _ephemeral_activation_env(env_file: str | Path, target_dir: Path) -> Path:
    values = _validate_persistent_activation_baseline(env_file)
    lines = _read_env_lines(Path(env_file).expanduser().absolute())
    replaced = False
    rendered: list[str] = []
    for line in lines:
        if line.startswith(ACTIVATION_FLAG + "="):
            rendered.append(f"{ACTIVATION_FLAG}=1")
            replaced = True
        else:
            rendered.append(line)
    if not replaced:
        raise OCPActivationWindowError("activation flag missing")
    if values.get(ACTIVATION_FLAG) != "0":
        raise OCPActivationWindowError("persistent activation flag changed during window")
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ocpv2-activation-", suffix=".env", dir=target_dir)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(rendered) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def poll_activation_window_once(
    *,
    state_root: str | Path,
    env_file: str | Path,
    now: datetime | None = None,
    runner: Callable[[Path], tuple[int, str]] | None = None,
) -> dict[str, object]:
    current = (now or _utc_now()).astimezone(timezone.utc)
    record = load_activation_window(state_root)
    if record is None or record["status"] != "ACTIVE":
        raise OCPActivationWindowError("active activation window required")
    if current > _parse_time(record["expires_at"], "expires_at"):
        raise OCPActivationWindowError("activation window expired before poll")
    _validate_persistent_activation_baseline(env_file)

    temp_dir = activation_window_path(state_root).parent
    ephemeral = _ephemeral_activation_env(env_file, temp_dir)
    try:
        if runner is None:
            repo_root = Path(__file__).resolve().parents[2]
            process_env = dict(os.environ)
            process_env["PYTHONPATH"] = str(repo_root) + (
                os.pathsep + process_env["PYTHONPATH"]
                if process_env.get("PYTHONPATH") else ""
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.orchestrator.ocpv2_successor_stage_runtime",
                    "--env-file",
                    str(ephemeral),
                ],
                cwd=repo_root,
                env=process_env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            code, stdout = completed.returncode, completed.stdout.strip()
        else:
            code, stdout = runner(ephemeral)
        projection: dict[str, object] = {}
        if stdout:
            try:
                parsed = json.loads(stdout.splitlines()[-1])
                if isinstance(parsed, dict):
                    projection = parsed
            except json.JSONDecodeError:
                projection = {}
        updated = _write_record(
            activation_window_path(state_root),
            {
                **record,
                "last_poll_at": _iso(current),
                "poll_count": int(record.get("poll_count") or 0) + 1,
                "last_poll_exit_code": int(code),
                "last_poll_status": str(projection.get("status") or "UNKNOWN"),
                "last_poll_full_plan_activated": int(projection.get("full_plan_activated") or 0),
                "last_poll_blocked": int(projection.get("blocked") or 0),
                "outcome": "POLL_COMPLETED" if int(code) == 0 else "POLL_FAILED",
            },
        )
        if int(code) != 0:
            raise OCPActivationWindowError("OCP activation poll failed")
        return updated
    finally:
        ephemeral.unlink(missing_ok=True)


def close_activation_window(
    *,
    state_root: str | Path,
    env_file: str | Path,
    controller: UserServiceController | None = None,
    now: datetime | None = None,
    body_failed: bool = False,
) -> dict[str, object]:
    current = (now or _utc_now()).astimezone(timezone.utc)
    record = load_activation_window(state_root)
    if record is None:
        raise OCPActivationWindowError("activation window marker missing")
    if record["status"] in _CLOSED_STATUSES:
        return record
    _validate_persistent_activation_baseline(env_file)
    service = controller or SystemdUserServiceController()
    return _finalize_window(
        record=record,
        state_root=state_root,
        controller=service,
        now=current,
        outcome="BODY_FAILED_CLEANUP_COMPLETE" if body_failed else "SUCCESS",
        successful_status="CLOSED_AFTER_FAILURE" if body_failed else "CLOSED",
    )


def recover_activation_window(
    *,
    state_root: str | Path,
    env_file: str | Path,
    controller: UserServiceController | None = None,
    now: datetime | None = None,
    require_expired: bool = True,
) -> dict[str, object]:
    current = (now or _utc_now()).astimezone(timezone.utc)
    record = load_activation_window(state_root)
    if record is None:
        raise OCPActivationWindowError("activation window marker missing")
    if record["status"] in _CLOSED_STATUSES:
        return record
    if require_expired and current <= _parse_time(record["expires_at"], "expires_at"):
        raise OCPActivationWindowError("activation window is still live")
    _validate_persistent_activation_baseline(env_file)
    service = controller or SystemdUserServiceController()
    return _finalize_window(
        record=record,
        state_root=state_root,
        controller=service,
        now=current,
        outcome="STALE_WINDOW_RECOVERY",
        successful_status="RECOVERED",
    )


def run_controlled_activation_once(
    *,
    state_root: str | Path,
    env_file: str | Path,
    controller: UserServiceController | None = None,
    scheduler: RecoveryScheduler | None = None,
    now: datetime | None = None,
    max_seconds: int = 300,
    window_id: str | None = None,
    runner: Callable[[Path], tuple[int, str]] | None = None,
) -> dict[str, object]:
    """Open, poll exactly once, and close a bounded activation transaction.

    Persistent activation stays OFF.  The one OCP poll receives only an
    ephemeral activation-enabled environment; the normal OCP/reconcile timers
    are restored before this function returns.  A poll failure closes the
    window as failed before propagating the error.
    """
    service = controller or SystemdUserServiceController()
    opened = open_activation_window(
        state_root=state_root,
        env_file=env_file,
        controller=service,
        scheduler=scheduler,
        now=now,
        max_seconds=max_seconds,
        window_id=window_id,
    )
    try:
        poll_activation_window_once(
            state_root=state_root,
            env_file=env_file,
            now=now,
            runner=runner,
        )
    except BaseException:
        try:
            close_activation_window(
                state_root=state_root,
                env_file=env_file,
                controller=service,
                body_failed=True,
            )
        except BaseException as cleanup_exc:
            raise OCPActivationWindowError(
                "activation transaction failed and cleanup incomplete"
            ) from cleanup_exc
        raise
    return close_activation_window(
        state_root=state_root,
        env_file=env_file,
        controller=service,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or recover a controlled OCPv2 Full Plan activation window"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("open", "poll", "close", "recover", "run-once"):
        command = sub.add_parser(name)
        command.add_argument("--state-root", required=True)
        command.add_argument("--env-file", required=True)
        if name in {"open", "run-once"}:
            command.add_argument("--max-seconds", type=int, default=300)
        if name == "recover":
            command.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "open":
            result = open_activation_window(
                state_root=args.state_root,
                env_file=args.env_file,
                max_seconds=args.max_seconds,
            )
        elif args.command == "poll":
            result = poll_activation_window_once(
                state_root=args.state_root,
                env_file=args.env_file,
            )
        elif args.command == "close":
            result = close_activation_window(
                state_root=args.state_root,
                env_file=args.env_file,
            )
        elif args.command == "run-once":
            result = run_controlled_activation_once(
                state_root=args.state_root,
                env_file=args.env_file,
                max_seconds=args.max_seconds,
            )
        else:
            result = recover_activation_window(
                state_root=args.state_root,
                env_file=args.env_file,
                require_expired=not args.force,
            )
    except (OCPActivationWindowError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "OK", "window": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Systemd user-unit rendering/install for AI Office Dashboard V2 publisher."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .durable_io import DurableIOError, atomic_write_text

PUBLISH_SERVICE_UNIT = "global-gpt-harness-ai-office-dashboard-publisher.service"
PUBLISH_TIMER_UNIT = "global-gpt-harness-ai-office-dashboard-publisher.timer"
_HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class OperationsDashboardPublishBootError(ValueError):
    pass


def _safe_dir(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().absolute()
    if any(ch.isspace() for ch in str(path)):
        raise OperationsDashboardPublishBootError(
            f"{label} contains whitespace"
        )
    if path.is_symlink() or not path.is_dir():
        raise OperationsDashboardPublishBootError(
            f"{label} is unsafe"
        )
    return path.resolve()


def _safe_executable(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    if any(ch.isspace() for ch in str(path)):
        raise OperationsDashboardPublishBootError(
            "python executable contains whitespace"
        )
    if (
        path.is_symlink()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise OperationsDashboardPublishBootError(
            "python executable is invalid"
        )
    return path.resolve()


def render_publish_service(
    *,
    runtime_root: str | Path,
    state_root: str | Path,
    publisher_source_head: str,
    python_executable: str | Path = sys.executable,
) -> str:
    runtime = _safe_dir(runtime_root, "runtime root")
    state = _safe_dir(state_root, "state root")
    python = _safe_executable(python_executable)
    head = str(publisher_source_head or "").strip()
    if not _HEAD.fullmatch(head):
        raise OperationsDashboardPublishBootError(
            "publisher source HEAD invalid"
        )
    return (
        "[Unit]\n"
        "Description=Publish Global GPT Harness AI Office Dashboard V2 aggregate\n"
        "After=default.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={runtime}\n"
        f"Environment=PYTHONPATH={runtime}\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "NoNewPrivileges=true\n"
        f"ExecStart={python} -m runtime.orchestrator.operations_dashboard_publish_cli "
        f"--state-root {state} --publisher-source-head {head}\n"
    )


def render_publish_timer(
    *,
    interval_seconds: int = 60,
    initial_delay_seconds: int = 20,
) -> str:
    if interval_seconds < 30:
        raise OperationsDashboardPublishBootError(
            "publisher interval must be at least 30 seconds"
        )
    if initial_delay_seconds < 5:
        raise OperationsDashboardPublishBootError(
            "publisher initial delay must be at least 5 seconds"
        )
    return (
        "[Unit]\n"
        "Description=Publish AI Office Dashboard V2 aggregate periodically\n\n"
        "[Timer]\n"
        f"OnBootSec={initial_delay_seconds}s\n"
        f"OnUnitActiveSec={interval_seconds}s\n"
        "AccuracySec=10s\n"
        "Persistent=true\n"
        f"Unit={PUBLISH_SERVICE_UNIT}\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _systemd_env() -> dict[str, str]:
    uid = os.getuid()
    runtime_dir = (
        os.environ.get("XDG_RUNTIME_DIR")
        or f"/run/user/{uid}"
    )
    return {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": (
            os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or f"unix:path={runtime_dir}/bus"
        ),
    }


def _default_runner(
    argv: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
            check=False,
            shell=False,
            env=_systemd_env(),
        )
    except (
        OSError,
        subprocess.TimeoutExpired,
        UnicodeError,
    ) as exc:
        raise OperationsDashboardPublishBootError(
            "systemd command failed"
        ) from exc


def install_publish_units(
    *,
    runtime_root: str | Path,
    state_root: str | Path,
    publisher_source_head: str,
    python_executable: str | Path = sys.executable,
    unit_dir: str | Path | None = None,
    runner: Callable[[Sequence[str]], object] | None = None,
    enable_now: bool = True,
) -> tuple[Path, Path]:
    directory = (
        Path(unit_dir).expanduser().absolute()
        if unit_dir is not None
        else Path.home() / ".config" / "systemd" / "user"
    )
    if directory.exists() and directory.is_symlink():
        raise OperationsDashboardPublishBootError(
            "systemd unit directory is unsafe"
        )
    directory.mkdir(parents=True, exist_ok=True)
    service_path = directory / PUBLISH_SERVICE_UNIT
    timer_path = directory / PUBLISH_TIMER_UNIT
    if (
        service_path.exists()
        and service_path.is_symlink()
    ):
        raise OperationsDashboardPublishBootError(
            "publisher service unit is unsafe"
        )
    if (
        timer_path.exists()
        and timer_path.is_symlink()
    ):
        raise OperationsDashboardPublishBootError(
            "publisher timer unit is unsafe"
        )

    try:
        atomic_write_text(
            service_path,
            render_publish_service(
                runtime_root=runtime_root,
                state_root=state_root,
                publisher_source_head=publisher_source_head,
                python_executable=python_executable,
            ),
        )
        atomic_write_text(
            timer_path,
            render_publish_timer(),
        )
    except (DurableIOError, OSError) as exc:
        raise OperationsDashboardPublishBootError(
            "publisher unit write failed"
        ) from exc

    if enable_now:
        control = runner or _default_runner
        for command in (
            ("systemctl", "--user", "daemon-reload"),
            (
                "systemctl",
                "--user",
                "enable",
                "--now",
                PUBLISH_TIMER_UNIT,
            ),
        ):
            completed = control(command)
            if getattr(completed, "returncode", None) != 0:
                raise OperationsDashboardPublishBootError(
                    "publisher unit activation failed"
                )
    return service_path, timer_path

"""Bounded read-only observer for allowlisted systemd user services."""
from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Sequence

SERVICE_PROPERTIES = ("ActiveState", "SubState", "Result", "ExecMainStatus")
TIMER_PROPERTIES = ("ActiveState", "SubState", "Result", "LastTriggerUSec")
_SAFE_UNIT = re.compile(r"[A-Za-z0-9_.@:-]+\.(?:service|timer)\Z")


class UserServiceObserverError(ValueError):
    pass


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    uid = os.getuid()
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": (
            os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime_dir}/bus"
        ),
    }
    try:
        return subprocess.run(
            list(argv), capture_output=True, text=True, encoding="utf-8", errors="strict",
            shell=False, timeout=10, env=env, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise UserServiceObserverError("SERVICE_QUERY_FAILED") from exc


class UserServiceObserver:
    def __init__(
        self, *, allowed_units: frozenset[str],
        runner: Callable[[Sequence[str]], object] | None = None,
    ) -> None:
        if not isinstance(allowed_units, frozenset) or not allowed_units:
            raise UserServiceObserverError("UNIT_ALLOWLIST_INVALID")
        if any(not isinstance(unit, str) or not _SAFE_UNIT.fullmatch(unit) for unit in allowed_units):
            raise UserServiceObserverError("UNIT_ALLOWLIST_INVALID")
        self.allowed_units = allowed_units
        self.runner = runner or _default_runner

    def read(self, unit_id: str) -> dict[str, str]:
        if not isinstance(unit_id, str) or not _SAFE_UNIT.fullmatch(unit_id) or unit_id not in self.allowed_units:
            raise UserServiceObserverError("UNIT_NOT_ALLOWED")
        properties = TIMER_PROPERTIES if unit_id.endswith(".timer") else SERVICE_PROPERTIES
        command = ("systemctl", "--user", "show", unit_id, "--property=" + ",".join(properties))
        try:
            completed = self.runner(command)
        except UserServiceObserverError:
            raise
        except Exception as exc:
            raise UserServiceObserverError("SERVICE_QUERY_FAILED") from exc
        if getattr(completed, "returncode", None) != 0:
            raise UserServiceObserverError("SERVICE_QUERY_FAILED")
        stdout = getattr(completed, "stdout", None)
        if not isinstance(stdout, str):
            raise UserServiceObserverError("SERVICE_RESULT_INVALID")
        values: dict[str, str] = {}
        for line in stdout.splitlines():
            if not line or "=" not in line:
                raise UserServiceObserverError("SERVICE_RESULT_INVALID")
            key, value = line.split("=", 1)
            if key not in properties or key in values:
                raise UserServiceObserverError("SERVICE_RESULT_INVALID")
            values[key] = value
        if set(values) != set(properties):
            raise UserServiceObserverError("SERVICE_RESULT_INVALID")
        return {key: values[key] for key in properties}

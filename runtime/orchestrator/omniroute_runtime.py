"""Fail-closed local runtime contract for the non-authoritative OmniRoute gateway."""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

OMNIROUTE_VERSION = "3.8.50"
OMNIROUTE_NPM_INTEGRITY = "sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg=="
OMNIROUTE_HOST = "127.0.0.1"
OMNIROUTE_PORT = 20128


class OmniRouteRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class OmniRouteRuntimeConfig:
    runtime_prefix: Path
    data_dir: Path
    secret_file: Path
    host: str = OMNIROUTE_HOST
    port: int = OMNIROUTE_PORT
    version: str = OMNIROUTE_VERSION
    npm_integrity: str = OMNIROUTE_NPM_INTEGRITY


def build_omniroute_env(data_dir: Path, api_key: str) -> dict[str, str]:
    if not str(api_key).strip():
        raise OmniRouteRuntimeError("OmniRoute API key is required")
    return {
        "DATA_DIR": str(data_dir),
        "PORT": str(OMNIROUTE_PORT),        "OMNIROUTE_SERVER_HOST": OMNIROUTE_HOST,
        "REQUIRE_API_KEY": "true",
        "OMNIROUTE_API_KEY": str(api_key),
        "OMNIROUTE_EMERGENCY_FALLBACK": "false",
        "PROXY_AUTO_SELECT_ENABLED": "false",
        "OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK": "false",
        "OMNIROUTE_ENABLE_LIVE_WS": "false",
        "OMNIROUTE_DISABLE_BACKGROUND_SERVICES": "true",
    }


def _parse_node_version(value: str) -> tuple[int, int, int]:
    raw = str(value).strip().lstrip("v")
    parts = raw.split(".")
    if len(parts) < 3 or not all(part.isdigit() for part in parts[:3]):
        raise OmniRouteRuntimeError("Node version is invalid")
    return tuple(int(part) for part in parts[:3])


def _node_supported(value: str) -> bool:
    major, minor, patch = _parse_node_version(value)
    if major == 22:
        return (minor, patch) >= (22, 2)
    return 24 <= major < 27


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise OmniRouteRuntimeError(f"{label} path must not be a symlink")


def validate_omniroute_preflight(
    *,
    runtime_prefix: Path,
    data_dir: Path,
    secret_file: Path,
    node_version: str,
    port_in_use: bool,
    package_version: str,
    package_integrity: str,
) -> OmniRouteRuntimeConfig:
    runtime_prefix = Path(runtime_prefix)
    data_dir = Path(data_dir)
    secret_file = Path(secret_file)
    _reject_symlink(runtime_prefix, "runtime")
    _reject_symlink(data_dir, "data")
    _reject_symlink(secret_file, "secret")
    if not _node_supported(node_version):
        raise OmniRouteRuntimeError("Node version is unsupported")
    if bool(port_in_use):
        raise OmniRouteRuntimeError(f"OmniRoute port {OMNIROUTE_PORT} is already in use")
    if not secret_file.is_file():
        raise OmniRouteRuntimeError("secret file is missing")
    if stat.S_IMODE(secret_file.stat().st_mode) != 0o600:
        raise OmniRouteRuntimeError("secret file permissions must be 0600")
    if str(package_version).strip() != OMNIROUTE_VERSION:
        raise OmniRouteRuntimeError("OmniRoute package version mismatch")
    if str(package_integrity).strip() != OMNIROUTE_NPM_INTEGRITY:
        raise OmniRouteRuntimeError("OmniRoute package integrity mismatch")
    return OmniRouteRuntimeConfig(runtime_prefix, data_dir, secret_file)

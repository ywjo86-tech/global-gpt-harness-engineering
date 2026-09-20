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
        "OMNIROUTE_CLI_SKIP_REPO_ENV": "1",
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


@dataclass(frozen=True)
class OmniRouteReadiness:
    package_version: str
    executable_path: str
    listener_hosts: tuple[str, ...]
    listener_port: int
    auth_enforced: bool
    doctor_status: str
    data_dir: str
    config_sha256: str
    secret_file_path: str
    secret_file_mode: int
    api_key_present: bool
    ready: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_version": self.package_version,
            "executable_path": self.executable_path,
            "listener_hosts": list(self.listener_hosts),
            "listener_port": self.listener_port,
            "auth_enforced": self.auth_enforced,
            "doctor_status": self.doctor_status,
            "data_dir": self.data_dir,
            "config_sha256": self.config_sha256,            "secret_file_path": self.secret_file_path,
            "secret_file_mode": f"{self.secret_file_mode:04o}",
            "api_key_present": self.api_key_present,
            "ready": self.ready,
            "reasons": list(self.reasons),
        }


def probe_omniroute_runtime(
    *,
    package_version: str,
    executable_path: str,
    listener_hosts: tuple[str, ...],
    listener_port: int,
    auth_enforced: bool,
    doctor_status: str,
    data_dir: str,
    config_sha256: str,
    secret_file_path: str,
    secret_file_mode: int,
    api_key_present: bool,
) -> OmniRouteReadiness:
    reasons: list[str] = []
    hosts = tuple(str(host).strip() for host in listener_hosts if str(host).strip())
    if package_version != OMNIROUTE_VERSION:
        reasons.append("package_version_mismatch")
    if not executable_path:
        reasons.append("executable_missing")
    if not hosts or any(host != OMNIROUTE_HOST for host in hosts):
        reasons.append("non_loopback_listener")
    if int(listener_port) != OMNIROUTE_PORT:
        reasons.append("unexpected_listener_port")
    if not auth_enforced:
        reasons.append("api_key_not_enforced")
    if doctor_status not in {"PASS", "DEGRADED_NO_PROVIDER_CREDENTIALS"}:
        reasons.append("doctor_not_acceptable")
    if not data_dir:
        reasons.append("data_dir_missing")
    if len(str(config_sha256)) != 64:
        reasons.append("config_digest_invalid")
    if not secret_file_path:
        reasons.append("secret_file_missing")
    if int(secret_file_mode) != 0o600:
        reasons.append("secret_file_mode_invalid")
    if not api_key_present:
        reasons.append("api_key_missing")
    return OmniRouteReadiness(
        package_version=str(package_version), executable_path=str(executable_path),
        listener_hosts=hosts, listener_port=int(listener_port),
        auth_enforced=bool(auth_enforced), doctor_status=str(doctor_status),
        data_dir=str(data_dir), config_sha256=str(config_sha256),
        secret_file_path=str(secret_file_path), secret_file_mode=int(secret_file_mode),
        api_key_present=bool(api_key_present), ready=not reasons, reasons=tuple(reasons),
    )

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

REQUEST_SCHEMA = "orchestration.read-only-host-diagnostic-request.v1"
RESULT_SCHEMA = "orchestration.read-only-host-diagnostic-result.v1"
CONFIG_SCHEMA = "orchestration.read-only-host-diagnostic-config.v1"
READ_ONLY_DIAGNOSTIC_CAPABILITY = "read_only_host_diagnostic"
OPERATIONS = frozenset({"repo.snapshot", "project.file_range", "path.metadata", "user_service.properties"})
STATUSES = frozenset({"OK", "PARTIAL", "STALE", "UNAVAILABLE", "BLOCKED", "ERROR"})
DATA_CLASSES = frozenset({"DIAG_SUMMARY", "DIAG_CONTENT"})
MAX_POLICY_BYTES = 32768
MAX_POLICY_LINES = 400
MAX_POLICY_TIMEOUT_SECONDS = 15

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_SERVICE = re.compile(r"[A-Za-z0-9@_.:-]{1,180}\.(?:service|timer|socket|path)\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class DiagnosticContractError(ValueError):
    pass


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_id(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise DiagnosticContractError(f"unsafe {label}")
    return text


def _load_json_no_duplicates(path: Path) -> Mapping[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise DiagnosticContractError(f"duplicate config key: {key}")
            out[key] = value
        return out

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs_hook)
    except DiagnosticContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticContractError("diagnostic config is unreadable or malformed") from exc
    if not isinstance(value, Mapping):
        raise DiagnosticContractError("diagnostic config must be an object")
    return value


@dataclass(frozen=True, slots=True)
class ReadOnlyDiagnosticRequestV1:
    schema_version: str
    request_id: str
    operation: str
    root_id: str
    relative_path: str
    start_line: int
    line_count: int
    service_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReadOnlyDiagnosticRequestV1":
        if not isinstance(value, Mapping):
            raise DiagnosticContractError("diagnostic request must be an object")
        expected = {
            "schema_version", "request_id", "operation", "root_id", "relative_path",
            "start_line", "line_count", "service_id",
        }
        if set(value) != expected:
            raise DiagnosticContractError("diagnostic request fields mismatch")
        if value.get("schema_version") != REQUEST_SCHEMA:
            raise DiagnosticContractError("unsupported diagnostic request schema")
        operation = str(value.get("operation") or "")
        if operation not in OPERATIONS:
            raise DiagnosticContractError("unknown diagnostic operation")
        request_id = _safe_id(value.get("request_id"), "request ID")
        root_id = _safe_id(value.get("root_id"), "root ID", allow_empty=True)
        relative_path = str(value.get("relative_path") or "")
        service_id = str(value.get("service_id") or "")
        try:
            start_line = int(value.get("start_line"))
            line_count = int(value.get("line_count"))
        except (TypeError, ValueError) as exc:
            raise DiagnosticContractError("invalid diagnostic line range") from exc
        if isinstance(value.get("start_line"), bool) or isinstance(value.get("line_count"), bool):
            raise DiagnosticContractError("invalid diagnostic line range")
        if start_line < 0 or line_count < 0:
            raise DiagnosticContractError("invalid diagnostic line range")

        if operation == "repo.snapshot":
            if not root_id:
                raise DiagnosticContractError("root ID required")
            if relative_path or start_line or line_count or service_id:
                raise DiagnosticContractError("unused request field for repo.snapshot")
        elif operation == "project.file_range":
            if not root_id or not relative_path or start_line <= 0 or line_count <= 0 or service_id:
                raise DiagnosticContractError("unused request field or incomplete file range request")
        elif operation == "path.metadata":
            if not root_id or not relative_path or start_line or line_count or service_id:
                raise DiagnosticContractError("unused request field or incomplete metadata request")
        elif operation == "user_service.properties":
            if root_id or relative_path or start_line or line_count or not service_id:
                raise DiagnosticContractError("unused request field or incomplete service request")
            if not _SAFE_SERVICE.fullmatch(service_id) or ".." in service_id:
                raise DiagnosticContractError("unsafe service ID")

        return cls(
            schema_version=REQUEST_SCHEMA,
            request_id=request_id,
            operation=operation,
            root_id=root_id,
            relative_path=relative_path,
            start_line=start_line,
            line_count=line_count,
            service_id=service_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class DiagnosticPolicy:
    roots: Mapping[str, Path]
    user_services: tuple[str, ...]
    max_bytes: int
    max_lines: int
    timeout_seconds: int
    schema_version: str = CONFIG_SCHEMA

    @classmethod
    def load(cls, path: str | Path) -> "DiagnosticPolicy":
        config_path = Path(path)
        if not config_path.is_absolute():
            raise DiagnosticContractError("diagnostic config path must be absolute")
        if config_path.is_symlink():
            raise DiagnosticContractError("diagnostic config may not be a symlink")
        try:
            info = config_path.stat()
        except OSError as exc:
            raise DiagnosticContractError("diagnostic config missing") from exc
        if not stat.S_ISREG(info.st_mode):
            raise DiagnosticContractError("diagnostic config must be a regular file")
        if info.st_uid != os.getuid():
            raise DiagnosticContractError("diagnostic config owner mismatch")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise DiagnosticContractError("diagnostic config is group/world writable")

        value = _load_json_no_duplicates(config_path)
        if set(value) != {"schema_version", "roots", "user_services", "limits"}:
            raise DiagnosticContractError("diagnostic config fields mismatch")
        if value.get("schema_version") != CONFIG_SCHEMA:
            raise DiagnosticContractError("unsupported diagnostic config schema")

        roots_raw = value.get("roots")
        if not isinstance(roots_raw, Mapping) or not roots_raw:
            raise DiagnosticContractError("diagnostic roots must be a non-empty object")
        roots: dict[str, Path] = {}
        for raw_id, raw_path in roots_raw.items():
            root_id = _safe_id(raw_id, "root ID")
            if root_id in roots:
                raise DiagnosticContractError("duplicate root ID")
            root = Path(str(raw_path))
            if not root.is_absolute():
                raise DiagnosticContractError("registered root must be absolute")
            if root.is_symlink():
                raise DiagnosticContractError("registered root may not be a symlink")
            try:
                resolved = root.resolve(strict=True)
            except OSError as exc:
                raise DiagnosticContractError("registered root does not exist") from exc
            if not resolved.is_dir():
                raise DiagnosticContractError("registered root must be a directory")
            roots[root_id] = resolved

        services_raw = value.get("user_services")
        if not isinstance(services_raw, list) or any(not isinstance(item, str) for item in services_raw):
            raise DiagnosticContractError("user services must be a list of strings")
        if len(set(services_raw)) != len(services_raw):
            raise DiagnosticContractError("duplicate user service")
        services: list[str] = []
        for service in services_raw:
            if not _SAFE_SERVICE.fullmatch(service) or ".." in service:
                raise DiagnosticContractError("unsafe user service ID")
            services.append(service)

        limits = value.get("limits")
        if not isinstance(limits, Mapping) or set(limits) != {"max_bytes", "max_lines", "timeout_seconds"}:
            raise DiagnosticContractError("diagnostic limits fields mismatch")
        vals: dict[str, int] = {}
        for key in ("max_bytes", "max_lines", "timeout_seconds"):
            raw = limits.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise DiagnosticContractError(f"invalid {key}")
            vals[key] = raw
        if vals["max_bytes"] > MAX_POLICY_BYTES:
            raise DiagnosticContractError("max_bytes exceeds policy ceiling")
        if vals["max_lines"] > MAX_POLICY_LINES:
            raise DiagnosticContractError("max_lines exceeds policy ceiling")
        if vals["timeout_seconds"] > MAX_POLICY_TIMEOUT_SECONDS:
            raise DiagnosticContractError("timeout_seconds exceeds policy ceiling")

        return cls(
            roots=roots,
            user_services=tuple(services),
            max_bytes=vals["max_bytes"],
            max_lines=vals["max_lines"],
            timeout_seconds=vals["timeout_seconds"],
        )

    def root(self, root_id: str) -> Path:
        key = _safe_id(root_id, "root ID")
        try:
            return self.roots[key]
        except KeyError as exc:
            raise DiagnosticContractError("unregistered root ID") from exc


@dataclass(frozen=True, slots=True)
class ReadOnlyDiagnosticResultV1:
    request_id: str
    correlation_id: str
    project_id: str
    root_id: str
    execution_owner: str
    operation_id: str
    authorization_decision: str
    captured_at: str
    freshness: str
    source_sha: str
    runtime_sha: str
    data_class: str
    redaction_applied: bool
    truncated: bool
    payload_hash: str
    status: str
    error_class: str
    payload: Mapping[str, Any]
    schema_version: str = RESULT_SCHEMA

    @classmethod
    def build(
        cls,
        *,
        request_id: str,
        correlation_id: str,
        project_id: str,
        root_id: str,
        operation_id: str,
        authorization_decision: str,
        captured_at: str,
        freshness: str,
        source_sha: str,
        runtime_sha: str,
        data_class: str,
        redaction_applied: bool,
        truncated: bool,
        status: str,
        error_class: str,
        payload: Mapping[str, Any],
        execution_owner: str = "NONE",
    ) -> "ReadOnlyDiagnosticResultV1":
        if operation_id not in OPERATIONS or status not in STATUSES or data_class not in DATA_CLASSES:
            raise DiagnosticContractError("invalid diagnostic result classification")
        for value, label in (
            (request_id, "request ID"), (correlation_id, "correlation ID"),
            (project_id, "project ID"),
        ):
            _safe_id(value, label)
        if root_id:
            _safe_id(root_id, "root ID")
        if execution_owner != "NONE":
            raise DiagnosticContractError("diagnostic execution owner must be NONE")
        if not authorization_decision or not captured_at or not freshness:
            raise DiagnosticContractError("diagnostic result provenance incomplete")
        if not _SHA.fullmatch(source_sha) or not _SHA.fullmatch(runtime_sha):
            raise DiagnosticContractError("invalid source/runtime SHA")
        if not isinstance(payload, Mapping):
            raise DiagnosticContractError("diagnostic payload must be an object")
        payload_copy = dict(payload)
        payload_hash = hashlib.sha256(_canonical_json(payload_copy)).hexdigest()
        return cls(
            request_id=request_id,
            correlation_id=correlation_id,
            project_id=project_id,
            root_id=root_id,
            execution_owner="NONE",
            operation_id=operation_id,
            authorization_decision=str(authorization_decision),
            captured_at=str(captured_at),
            freshness=str(freshness),
            source_sha=source_sha,
            runtime_sha=runtime_sha,
            data_class=data_class,
            redaction_applied=bool(redaction_applied),
            truncated=bool(truncated),
            payload_hash=payload_hash,
            status=status,
            error_class=str(error_class or ""),
            payload=payload_copy,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["payload"] = dict(self.payload)
        return value


def diagnostic_feature_enabled(environment: Mapping[str, str]) -> bool:
    raw = str(environment.get("GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED", "false"))
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise DiagnosticContractError("diagnostic feature flag must be true or false")

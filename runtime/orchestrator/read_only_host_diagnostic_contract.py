"""Typed contracts for bounded, non-authoritative host diagnostics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
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

_REQUEST_FIELDS = {
    "schema_version", "request_id", "operation", "root_id", "relative_path",
    "start_line", "line_count", "service_id",
}
_CONFIG_FIELDS = {"schema_version", "roots", "user_services", "limits"}
_LIMIT_FIELDS = {"max_bytes", "max_lines", "timeout_seconds"}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_ROOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_SERVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class DiagnosticContractError(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_id(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise DiagnosticContractError(f"unsafe {label}")
    return text


def _safe_relative(value: object, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not text or "\\" in text:
        raise DiagnosticContractError("unsafe relative path")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != text:
        raise DiagnosticContractError("unsafe relative path")
    return text


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
        if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
            raise DiagnosticContractError("diagnostic request fields mismatch")
        if value.get("schema_version") != REQUEST_SCHEMA:
            raise DiagnosticContractError("diagnostic request schema mismatch")
        request_id = _safe_id(value.get("request_id"), "request ID")
        operation = str(value.get("operation") or "")
        if operation not in OPERATIONS:
            raise DiagnosticContractError("unknown diagnostic operation")
        try:
            start_line = int(value.get("start_line"))
            line_count = int(value.get("line_count"))
        except (TypeError, ValueError) as exc:
            raise DiagnosticContractError("invalid line range") from exc
        if isinstance(value.get("start_line"), bool) or isinstance(value.get("line_count"), bool):
            raise DiagnosticContractError("invalid line range")
        root_id = str(value.get("root_id") or "")
        relative_path = str(value.get("relative_path") or "")
        service_id = str(value.get("service_id") or "")
        if operation == "repo.snapshot":
            if not _SAFE_ROOT_ID.fullmatch(root_id):
                raise DiagnosticContractError("unsafe root ID")
            if relative_path or start_line or line_count or service_id:
                raise DiagnosticContractError("unused request field for repo.snapshot")
        elif operation == "project.file_range":
            if not _SAFE_ROOT_ID.fullmatch(root_id):
                raise DiagnosticContractError("unsafe root ID")
            relative_path = _safe_relative(relative_path)
            if start_line <= 0 or line_count <= 0:
                raise DiagnosticContractError("invalid line range")
            if service_id:
                raise DiagnosticContractError("unused request field for project.file_range")
        elif operation == "path.metadata":
            if not _SAFE_ROOT_ID.fullmatch(root_id):
                raise DiagnosticContractError("unsafe root ID")
            relative_path = _safe_relative(relative_path)
            if start_line or line_count or service_id:
                raise DiagnosticContractError("unused request field for path.metadata")
        else:
            if root_id or relative_path or start_line or line_count:
                raise DiagnosticContractError("unused request field for user_service.properties")
            if not _SAFE_SERVICE.fullmatch(service_id):
                raise DiagnosticContractError("unsafe service ID")
        return cls(REQUEST_SCHEMA, request_id, operation, root_id, relative_path, start_line, line_count, service_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


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
        cls, *, request_id: str, correlation_id: str, project_id: str, root_id: str,
        operation_id: str, authorization_decision: str, captured_at: str, freshness: str,
        source_sha: str, runtime_sha: str, data_class: str, redaction_applied: bool,
        truncated: bool, status: str, error_class: str, payload: Mapping[str, Any],
    ) -> "ReadOnlyDiagnosticResultV1":
        for value, label in ((request_id, "request ID"), (correlation_id, "correlation ID"),
                             (project_id, "project ID"), (operation_id, "operation ID")):
            _safe_id(value, label)
        if root_id and not _SAFE_ROOT_ID.fullmatch(root_id):
            raise DiagnosticContractError("unsafe root ID")
        if data_class not in DATA_CLASSES:
            raise DiagnosticContractError("unknown diagnostic data class")
        if status not in STATUSES:
            raise DiagnosticContractError("unknown diagnostic status")
        if not _SHA.fullmatch(source_sha):
            raise DiagnosticContractError("invalid source SHA")
        if not _SHA.fullmatch(runtime_sha):
            raise DiagnosticContractError("invalid runtime SHA")
        if not captured_at or not freshness or not authorization_decision:
            raise DiagnosticContractError("diagnostic result provenance is incomplete")
        if not isinstance(payload, Mapping):
            raise DiagnosticContractError("diagnostic payload must be a mapping")
        payload_copy = dict(payload)
        return cls(
            request_id=request_id, correlation_id=correlation_id, project_id=project_id,
            root_id=root_id, execution_owner="NONE", operation_id=operation_id,
            authorization_decision=authorization_decision, captured_at=captured_at,
            freshness=freshness, source_sha=source_sha, runtime_sha=runtime_sha,
            data_class=data_class, redaction_applied=bool(redaction_applied),
            truncated=bool(truncated), payload_hash=hashlib.sha256(_canonical_json_bytes(payload_copy)).hexdigest(),
            status=status, error_class=str(error_class or ""), payload=payload_copy,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiagnosticPolicy:
    roots: Mapping[str, Path]
    user_services: tuple[str, ...]
    max_bytes: int
    max_lines: int
    timeout_seconds: int

    @classmethod
    def load(cls, path: str | Path) -> "DiagnosticPolicy":
        config_path = Path(path)
        if not config_path.is_absolute():
            raise DiagnosticContractError("diagnostic config path must be absolute")
        try:
            lst = config_path.lstat()
        except OSError as exc:
            raise DiagnosticContractError("diagnostic config is unavailable") from exc
        if stat.S_ISLNK(lst.st_mode):
            raise DiagnosticContractError("diagnostic config may not be a symlink")
        if not stat.S_ISREG(lst.st_mode):
            raise DiagnosticContractError("diagnostic config must be a regular file")
        if lst.st_uid != os.getuid():
            raise DiagnosticContractError("diagnostic config owner mismatch")
        if lst.st_mode & 0o022:
            raise DiagnosticContractError("diagnostic config is group/world writable")
        try:
            value = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DiagnosticContractError("diagnostic config is unreadable or malformed") from exc
        if not isinstance(value, Mapping) or set(value) != _CONFIG_FIELDS or value.get("schema_version") != CONFIG_SCHEMA:
            raise DiagnosticContractError("diagnostic config fields/schema mismatch")
        raw_roots = value.get("roots")
        if not isinstance(raw_roots, Mapping) or not raw_roots:
            raise DiagnosticContractError("diagnostic roots are missing")
        roots: dict[str, Path] = {}
        for raw_id, raw_path in raw_roots.items():
            root_id = str(raw_id)
            if not _SAFE_ROOT_ID.fullmatch(root_id):
                raise DiagnosticContractError("unsafe root ID")
            root = Path(str(raw_path))
            if not root.is_absolute():
                raise DiagnosticContractError("registered root must be absolute")
            if root.is_symlink():
                raise DiagnosticContractError("registered root may not be a symlink")
            try:
                root_stat = root.stat()
            except OSError as exc:
                raise DiagnosticContractError("registered root is unavailable") from exc
            if not stat.S_ISDIR(root_stat.st_mode):
                raise DiagnosticContractError("registered root must be a directory")
            roots[root_id] = root.resolve(strict=True)
        services = value.get("user_services")
        if not isinstance(services, list) or any(not isinstance(item, str) or not _SAFE_SERVICE.fullmatch(item) for item in services):
            raise DiagnosticContractError("unsafe user service ID")
        if len(set(services)) != len(services):
            raise DiagnosticContractError("duplicate user service ID")
        limits = value.get("limits")
        if not isinstance(limits, Mapping) or set(limits) != _LIMIT_FIELDS:
            raise DiagnosticContractError("diagnostic limits mismatch")
        parsed: dict[str, int] = {}
        for key in _LIMIT_FIELDS:
            raw = limits.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise DiagnosticContractError("diagnostic limit must be a positive integer")
            parsed[key] = raw
        if parsed["max_bytes"] > MAX_POLICY_BYTES or parsed["max_lines"] > MAX_POLICY_LINES or parsed["timeout_seconds"] > MAX_POLICY_TIMEOUT_SECONDS:
            raise DiagnosticContractError("diagnostic limit exceeds hard maximum")
        return cls(roots=roots, user_services=tuple(services), max_bytes=parsed["max_bytes"],
                   max_lines=parsed["max_lines"], timeout_seconds=parsed["timeout_seconds"])


def diagnostic_feature_enabled(environment: Mapping[str, str]) -> bool:
    value = str(environment.get("GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED", "false"))
    if value == "true":
        return True
    if value == "false":
        return False
    raise DiagnosticContractError("invalid read-only diagnostic feature flag")

"""Durable downstream-only projection outbox for sanitized read-only diagnostics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .durable_io import DurableIOError, canonical_json_bytes, durable_json_load, durable_json_save, sha256_bytes
from .read_only_host_diagnostic_contract import RESULT_SCHEMA, ReadOnlyDiagnosticResultV1

_DIAGNOSTIC_PROJECTION_SCHEMA = "orchestration.remote-diagnostic-projection.v1"


class RemoteDiagnosticOutboxError(ValueError):
    pass


def _digest(value: str, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RemoteDiagnosticOutboxError(f"invalid {label}")
    return text


def _safe_id(value: str, label: str) -> str:
    text = str(value or "")
    if not text or "/" in text or "\\" in text or ".." in text:
        raise RemoteDiagnosticOutboxError(f"unsafe {label}")
    return text


def _result_from_mapping(value: Mapping[str, Any]) -> ReadOnlyDiagnosticResultV1:
    expected = {
        "request_id", "correlation_id", "project_id", "root_id", "execution_owner",
        "operation_id", "authorization_decision", "captured_at", "freshness", "source_sha",
        "runtime_sha", "data_class", "redaction_applied", "truncated", "payload_hash",
        "status", "error_class", "payload", "schema_version",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise RemoteDiagnosticOutboxError("diagnostic result fields mismatch")
    if value.get("schema_version") != RESULT_SCHEMA or value.get("execution_owner") != "NONE":
        raise RemoteDiagnosticOutboxError("diagnostic result contract mismatch")
    if not isinstance(value.get("payload"), Mapping):
        raise RemoteDiagnosticOutboxError("diagnostic payload must be a mapping")
    try:
        result = ReadOnlyDiagnosticResultV1.build(
            request_id=value["request_id"], correlation_id=value["correlation_id"],
            project_id=value["project_id"], root_id=value["root_id"], operation_id=value["operation_id"],
            authorization_decision=value["authorization_decision"], captured_at=value["captured_at"],
            freshness=value["freshness"], source_sha=value["source_sha"], runtime_sha=value["runtime_sha"],
            data_class=value["data_class"], redaction_applied=value["redaction_applied"],
            truncated=value["truncated"], status=value["status"], error_class=value["error_class"],
            payload=value["payload"],
        )
    except (TypeError, ValueError) as exc:
        raise RemoteDiagnosticOutboxError("diagnostic result invalid") from exc
    if result.payload_hash != value.get("payload_hash"):
        raise RemoteDiagnosticOutboxError("diagnostic payload hash mismatch")
    return result


@dataclass(frozen=True, slots=True)
class RemoteDiagnosticProjectionV1:
    projection_id: str
    message_id: str
    directive_digest: str
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    request_digest: str
    diagnostic_result: ReadOnlyDiagnosticResultV1
    projected_at: str
    schema_version: str = _DIAGNOSTIC_PROJECTION_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.projection_id, "projection ID"), (self.message_id, "message ID"),
            (self.project_id, "project ID"), (self.run_id, "run ID"),
            (self.gate_id, "gate ID"), (self.task_id, "task ID"),
        ):
            _safe_id(value, label)
        _digest(self.directive_digest, "directive digest")
        _digest(self.request_digest, "request digest")
        if not isinstance(self.diagnostic_result, ReadOnlyDiagnosticResultV1):
            raise RemoteDiagnosticOutboxError("diagnostic result type mismatch")
        if self.schema_version != _DIAGNOSTIC_PROJECTION_SCHEMA:
            raise RemoteDiagnosticOutboxError("projection schema mismatch")
        if self.diagnostic_result.project_id != self.project_id:
            raise RemoteDiagnosticOutboxError("diagnostic project identity mismatch")

    @property
    def projection_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["diagnostic_result"] = self.diagnostic_result.to_dict()
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteDiagnosticProjectionV1":
        expected = {
            "projection_id", "message_id", "directive_digest", "project_id", "run_id",
            "gate_id", "task_id", "request_digest", "diagnostic_result", "projected_at",
            "schema_version",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise RemoteDiagnosticOutboxError("projection fields mismatch")
        raw_result = value.get("diagnostic_result")
        if not isinstance(raw_result, Mapping):
            raise RemoteDiagnosticOutboxError("diagnostic result must be an object")
        result = _result_from_mapping(raw_result)
        return cls(
            projection_id=str(value["projection_id"]), message_id=str(value["message_id"]),
            directive_digest=str(value["directive_digest"]), project_id=str(value["project_id"]),
            run_id=str(value["run_id"]), gate_id=str(value["gate_id"]), task_id=str(value["task_id"]),
            request_digest=str(value["request_digest"]), diagnostic_result=result,
            projected_at=str(value["projected_at"]), schema_version=str(value["schema_version"]),
        )


class RemoteDiagnosticOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RemoteDiagnosticOutboxError("unsafe outbox root")
        self.pending_root = self.root / "pending"
        self.published_root = self.root / "published"
        for path in (self.root, self.pending_root, self.published_root):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise RemoteDiagnosticOutboxError("unsafe outbox path")
            path.mkdir(parents=True, exist_ok=True)

    def _path(self, root: Path, projection_id: str) -> Path:
        return root / f"{_safe_id(projection_id, 'projection ID')}.json"

    @staticmethod
    def _load(path: Path) -> RemoteDiagnosticProjectionV1 | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteDiagnosticOutboxError("outbox state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteDiagnosticOutboxError("outbox state invalid") from exc
        return RemoteDiagnosticProjectionV1.from_mapping(value)

    def enqueue(self, record: RemoteDiagnosticProjectionV1) -> None:
        if not isinstance(record, RemoteDiagnosticProjectionV1):
            raise RemoteDiagnosticOutboxError("projection type mismatch")
        pending = self._path(self.pending_root, record.projection_id)
        published = self._path(self.published_root, record.projection_id)
        for existing_path in (published, pending):
            existing = self._load(existing_path)
            if existing is None:
                continue
            if existing.projection_sha256 == record.projection_sha256:
                return
            raise RemoteDiagnosticOutboxError("conflicting projection ID")
        try:
            durable_json_save(pending, record.to_dict())
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteDiagnosticOutboxError("outbox enqueue failed") from exc

    def pending(self) -> tuple[RemoteDiagnosticProjectionV1, ...]:
        records: list[RemoteDiagnosticProjectionV1] = []
        for path in sorted(self.pending_root.glob("*.json")):
            if path.name.endswith(".prev"):
                continue
            record = self._load(path)
            if record is None:
                continue
            if self._load(self._path(self.published_root, record.projection_id)) is not None:
                continue
            records.append(record)
        return tuple(records)

    def mark_published(self, projection_id: str, projection_sha256: str) -> None:
        _digest(projection_sha256, "projection digest")
        pending_path = self._path(self.pending_root, projection_id)
        published_path = self._path(self.published_root, projection_id)
        published = self._load(published_path)
        if published is not None:
            if published.projection_sha256 != projection_sha256:
                raise RemoteDiagnosticOutboxError("projection digest mismatch")
            return
        record = self._load(pending_path)
        if record is None:
            raise RemoteDiagnosticOutboxError("pending projection missing")
        if record.projection_sha256 != projection_sha256:
            raise RemoteDiagnosticOutboxError("projection digest mismatch")
        try:
            durable_json_save(published_path, record.to_dict())
            if pending_path.exists():
                pending_path.unlink()
            previous = pending_path.with_suffix(pending_path.suffix + ".prev")
            if previous.exists():
                previous.unlink()
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteDiagnosticOutboxError("mark published failed") from exc

    def publish_pending(self, publisher: Callable[[RemoteDiagnosticProjectionV1], Any]) -> int:
        count = 0
        for record in self.pending():
            publisher(record)
            self.mark_published(record.projection_id, record.projection_sha256)
            count += 1
        return count

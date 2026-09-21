"""Durable downstream-only result projection outbox for OCPv2."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .durable_io import DurableIOError, canonical_json_bytes, durable_json_load, durable_json_save, sha256_bytes


_RESULT_SCHEMA = "orchestration.remote-result-projection.v1"
_COMPLETED = "CANONICAL_ACTION_COMPLETED"


class RemoteOperatorOutboxError(ValueError):
    pass


def _digest(value: str, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RemoteOperatorOutboxError(f"invalid {label}")
    return text


def _safe_id(value: str, label: str) -> str:
    text = str(value or "")
    if not text or "/" in text or "\\" in text or ".." in text:
        raise RemoteOperatorOutboxError(f"unsafe {label}")
    return text


@dataclass(frozen=True, slots=True)
class RemoteResultProjectionV1:
    projection_id: str
    message_id: str
    directive_digest: str
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    canonical_state_ref: str
    canonical_state_sha256: str
    effect_evidence_refs: tuple[str, ...]
    checkpoint_ref: str
    checkpoint_sha256: str
    migration_transaction_sha256: str
    result_class: str
    result_summary: str
    projected_at: str
    schema_version: str = _RESULT_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.projection_id, "projection ID"), (self.message_id, "message ID"),
            (self.project_id, "project ID"), (self.run_id, "run ID"),
            (self.gate_id, "gate ID"), (self.task_id, "task ID"),
        ):
            _safe_id(value, label)
        _digest(self.directive_digest, "directive digest")
        _digest(self.canonical_state_sha256, "canonical state digest", allow_empty=True)
        _digest(self.checkpoint_sha256, "checkpoint digest", allow_empty=True)
        _digest(self.migration_transaction_sha256, "migration transaction digest", allow_empty=True)
        if self.schema_version != _RESULT_SCHEMA:
            raise RemoteOperatorOutboxError("projection schema mismatch")
        if self.result_class == _COMPLETED:
            has_state = bool(self.canonical_state_ref and self.canonical_state_sha256)
            has_effect = bool(self.effect_evidence_refs)
            has_checkpoint = bool(self.checkpoint_ref and self.checkpoint_sha256)
            if not (has_state or has_effect or has_checkpoint):
                raise RemoteOperatorOutboxError("canonical evidence required for completed result")

    @property
    def projection_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effect_evidence_refs"] = list(self.effect_evidence_refs)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteResultProjectionV1":
        expected = {
            "projection_id", "message_id", "directive_digest", "project_id", "run_id", "gate_id",
            "task_id", "canonical_state_ref", "canonical_state_sha256", "effect_evidence_refs",
            "checkpoint_ref", "checkpoint_sha256", "migration_transaction_sha256", "result_class",
            "result_summary", "projected_at", "schema_version",
        }
        if set(value) != expected:
            raise RemoteOperatorOutboxError("projection fields mismatch")
        refs = value.get("effect_evidence_refs")
        if not isinstance(refs, list) or not all(isinstance(item, str) and item for item in refs):
            raise RemoteOperatorOutboxError("effect evidence refs invalid")
        return cls(
            projection_id=str(value["projection_id"]), message_id=str(value["message_id"]),
            directive_digest=str(value["directive_digest"]), project_id=str(value["project_id"]),
            run_id=str(value["run_id"]), gate_id=str(value["gate_id"]), task_id=str(value["task_id"]),
            canonical_state_ref=str(value["canonical_state_ref"]),
            canonical_state_sha256=str(value["canonical_state_sha256"]),
            effect_evidence_refs=tuple(refs), checkpoint_ref=str(value["checkpoint_ref"]),
            checkpoint_sha256=str(value["checkpoint_sha256"]),
            migration_transaction_sha256=str(value["migration_transaction_sha256"]),
            result_class=str(value["result_class"]), result_summary=str(value["result_summary"]),
            projected_at=str(value["projected_at"]), schema_version=str(value["schema_version"]),
        )


class RemoteResultOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RemoteOperatorOutboxError("unsafe outbox root")
        self.pending_root = self.root / "pending"
        self.published_root = self.root / "published"
        for path in (self.root, self.pending_root, self.published_root):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise RemoteOperatorOutboxError("unsafe outbox path")
            path.mkdir(parents=True, exist_ok=True)

    def _path(self, root: Path, projection_id: str) -> Path:
        return root / f"{_safe_id(projection_id, 'projection ID')}.json"

    @staticmethod
    def _load(path: Path) -> RemoteResultProjectionV1 | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteOperatorOutboxError("outbox state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorOutboxError("outbox state invalid") from exc
        return RemoteResultProjectionV1.from_mapping(value)

    def enqueue_projection(self, projection: RemoteResultProjectionV1) -> None:
        pending = self._path(self.pending_root, projection.projection_id)
        published = self._path(self.published_root, projection.projection_id)
        for existing_path in (published, pending):
            existing = self._load(existing_path)
            if existing is None:
                continue
            if existing.projection_sha256 == projection.projection_sha256:
                return
            raise RemoteOperatorOutboxError("conflicting projection ID")
        try:
            durable_json_save(pending, projection.to_dict())
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorOutboxError("outbox enqueue failed") from exc

    def pending(self) -> tuple[RemoteResultProjectionV1, ...]:
        result: list[RemoteResultProjectionV1] = []
        for path in sorted(self.pending_root.glob("*.json")):
            if path.name.endswith(".prev"):
                continue
            projection = self._load(path)
            if projection is None:
                continue
            if self._load(self._path(self.published_root, projection.projection_id)) is not None:
                continue
            result.append(projection)
        return tuple(result)

    def mark_published(self, projection_id: str, projection_sha256: str) -> None:
        _digest(projection_sha256, "projection digest")
        pending_path = self._path(self.pending_root, projection_id)
        published_path = self._path(self.published_root, projection_id)
        published = self._load(published_path)
        if published is not None:
            if published.projection_sha256 != projection_sha256:
                raise RemoteOperatorOutboxError("projection digest mismatch")
            return
        projection = self._load(pending_path)
        if projection is None:
            raise RemoteOperatorOutboxError("pending projection missing")
        if projection.projection_sha256 != projection_sha256:
            raise RemoteOperatorOutboxError("projection digest mismatch")
        try:
            durable_json_save(published_path, projection.to_dict())
            if pending_path.exists():
                pending_path.unlink()
            previous = pending_path.with_suffix(pending_path.suffix + ".prev")
            if previous.exists():
                previous.unlink()
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorOutboxError("mark published failed") from exc

    def publish_pending(self, publisher: Callable[[RemoteResultProjectionV1], Any]) -> int:
        count = 0
        for projection in self.pending():
            publisher(projection)
            self.mark_published(projection.projection_id, projection.projection_sha256)
            count += 1
        return count

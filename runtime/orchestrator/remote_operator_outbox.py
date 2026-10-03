"""Durable downstream-only result projection outbox for OCPv2."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .full_plan_activation import FullPlanActivationReceiptV1
from .host_inspection_contract import HostInspectionResultV1
from .plan_activation import PlanActivationReceiptV1

from .durable_io import DurableIOError, canonical_json_bytes, durable_json_load, durable_json_save, sha256_bytes


_RESULT_SCHEMA = "orchestration.remote-result-projection.v1"
_INSPECTION_RESULT_SCHEMA = "orchestration.remote-inspection-projection.v1"
_ACTIVATION_RESULT_SCHEMA = "orchestration.remote-activation-projection.v1"
_FULL_PLAN_ACTIVATION_RESULT_SCHEMA = "orchestration.remote-full-plan-activation-projection.v1"
_COMPLETED = "CANONICAL_ACTION_COMPLETED"
_INSPECTION_SECRET = re.compile(
    rb"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)"
)


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


@dataclass(frozen=True, slots=True)
class RemoteInspectionProjectionV1:
    projection_id: str
    message_id: str
    request_id: str
    correlation_id: str
    project_alias: str
    operation: str
    request_digest: str
    status: str
    data: Mapping[str, Any]
    error_code: str = ""
    schema_version: str = _INSPECTION_RESULT_SCHEMA

    def __post_init__(self) -> None:
        _safe_id(self.projection_id, "projection ID")
        _safe_id(self.message_id, "message ID")
        if self.schema_version != _INSPECTION_RESULT_SCHEMA:
            raise RemoteOperatorOutboxError("inspection projection schema mismatch")
        result = HostInspectionResultV1(
            schema_version="orchestration.host-inspection-result.v1",
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            project_alias=self.project_alias,
            operation=self.operation,
            request_digest=self.request_digest,
            status=self.status,
            data=self.data,
            error_code=self.error_code,
        )
        object.__setattr__(self, "data", result.data)

    @property
    def projection_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "project_alias": self.project_alias,
            "operation": self.operation,
            "request_digest": self.request_digest,
            "status": self.status,
            "data": dict(self.data),
            "error_code": self.error_code,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_result(cls, result: HostInspectionResultV1, *, message_id: str) -> "RemoteInspectionProjectionV1":
        _safe_id(message_id, "message ID")
        material = {"message_id": message_id, "result": result.to_dict()}
        projection_id = "INSP-" + sha256_bytes(canonical_json_bytes(material))[:32]
        return cls(
            projection_id=projection_id,
            message_id=message_id,
            request_id=result.request_id,
            correlation_id=result.correlation_id,
            project_alias=result.project_alias,
            operation=result.operation,
            request_digest=result.request_digest,
            status=result.status,
            data=result.data,
            error_code=result.error_code,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteInspectionProjectionV1":
        expected = {
            "projection_id", "message_id", "request_id", "correlation_id", "project_alias",
            "operation", "request_digest", "status", "data", "error_code", "schema_version",
        }
        if set(value) != expected or not isinstance(value.get("data"), Mapping):
            raise RemoteOperatorOutboxError("inspection projection fields mismatch")
        return cls(
            projection_id=str(value["projection_id"]),
            message_id=str(value["message_id"]),
            request_id=str(value["request_id"]),
            correlation_id=str(value["correlation_id"]),
            project_alias=str(value["project_alias"]),
            operation=str(value["operation"]),
            request_digest=str(value["request_digest"]),
            status=str(value["status"]),
            data=dict(value["data"]),
            error_code=str(value["error_code"]),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class RemoteActivationProjectionV1:
    projection_id: str
    message_id: str
    activation_request_id: str
    binding_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    activation_digest: str
    schema_version: str = _ACTIVATION_RESULT_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.projection_id, "projection ID"), (self.message_id, "message ID"),
            (self.activation_request_id, "activation request ID"), (self.run_id, "run ID"),
        ):
            _safe_id(value, label)
        for value, label in (
            (self.binding_digest, "binding digest"),
            (self.authority_digest, "authority digest"),
            (self.activation_digest, "activation digest"),
        ):
            _digest(value, label)
        if self.schema_version != _ACTIVATION_RESULT_SCHEMA:
            raise RemoteOperatorOutboxError("activation projection schema mismatch")
        if self.result_status not in {"REGISTERED", "ALREADY_REGISTERED"}:
            raise RemoteOperatorOutboxError("activation projection status invalid")
        if not self.canonical_job_path:
            raise RemoteOperatorOutboxError("activation canonical job path missing")

    @property
    def projection_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_receipt(cls, receipt: PlanActivationReceiptV1, *, message_id: str) -> "RemoteActivationProjectionV1":
        try:
            sealed = PlanActivationReceiptV1.from_mapping(receipt.to_dict())
        except ValueError as exc:
            raise RemoteOperatorOutboxError("activation receipt invalid") from exc
        material = {"message_id": message_id, "activation_digest": sealed.activation_digest}
        projection_id = "ACT-" + sha256_bytes(canonical_json_bytes(material))[:32]
        return cls(
            projection_id=projection_id, message_id=message_id,
            activation_request_id=sealed.activation_request_id, binding_digest=sealed.binding_digest,
            result_status=sealed.result_status, canonical_job_path=sealed.canonical_job_path,
            run_id=sealed.run_id, authority_digest=sealed.authority_digest,
            activation_digest=sealed.activation_digest,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteActivationProjectionV1":
        expected = {
            "projection_id", "message_id", "activation_request_id", "binding_digest",
            "result_status", "canonical_job_path", "run_id", "authority_digest",
            "activation_digest", "schema_version",
        }
        if set(value) != expected:
            raise RemoteOperatorOutboxError("activation projection fields mismatch")
        return cls(**{key: str(value[key]) for key in expected})


@dataclass(frozen=True, slots=True)
class RemoteFullPlanActivationProjectionV1:
    projection_id: str
    message_id: str
    activation_request_id: str
    activation_profile: str
    binding_digest: str
    executable_authority_bundle_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    activation_digest: str
    schema_version: str = _FULL_PLAN_ACTIVATION_RESULT_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.projection_id, "projection ID"), (self.message_id, "message ID"),
            (self.activation_request_id, "activation request ID"), (self.run_id, "run ID"),
        ):
            _safe_id(value, label)
        for value, label in (
            (self.binding_digest, "binding digest"),
            (self.executable_authority_bundle_digest, "executable authority bundle digest"),
            (self.authority_digest, "authority digest"),
            (self.activation_digest, "activation digest"),
        ):
            _digest(value, label)
        if self.schema_version != _FULL_PLAN_ACTIVATION_RESULT_SCHEMA:
            raise RemoteOperatorOutboxError("Full Plan activation projection schema mismatch")
        if self.activation_profile != "AUTO_RECONCILE_FULL_PLAN":
            raise RemoteOperatorOutboxError("Full Plan activation profile invalid")
        if self.result_status not in {"FULL_PLAN_REGISTERED", "FULL_PLAN_ALREADY_REGISTERED"}:
            raise RemoteOperatorOutboxError("Full Plan activation projection status invalid")
        if not self.canonical_job_path:
            raise RemoteOperatorOutboxError("Full Plan activation canonical job path missing")

    @property
    def projection_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_receipt(cls, receipt: FullPlanActivationReceiptV1, *, message_id: str) -> "RemoteFullPlanActivationProjectionV1":
        try:
            sealed = FullPlanActivationReceiptV1.from_mapping(receipt.to_dict())
        except ValueError as exc:
            raise RemoteOperatorOutboxError("Full Plan activation receipt invalid") from exc
        material = {"message_id": message_id, "activation_digest": sealed.activation_digest}
        projection_id = "FPA-" + sha256_bytes(canonical_json_bytes(material))[:32]
        return cls(
            projection_id=projection_id, message_id=message_id,
            activation_request_id=sealed.activation_request_id,
            activation_profile="AUTO_RECONCILE_FULL_PLAN",
            binding_digest=sealed.bundle_digest,
            executable_authority_bundle_digest=sealed.executable_authority_bundle_digest,
            result_status=sealed.result_status, canonical_job_path=sealed.canonical_job_path,
            run_id=sealed.run_id, authority_digest=sealed.authority_digest,
            activation_digest=sealed.activation_digest,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RemoteFullPlanActivationProjectionV1":
        expected = {
            "projection_id", "message_id", "activation_request_id", "activation_profile",
            "binding_digest", "executable_authority_bundle_digest", "result_status",
            "canonical_job_path", "run_id", "authority_digest", "activation_digest", "schema_version",
        }
        if set(value) != expected:
            raise RemoteOperatorOutboxError("Full Plan activation projection fields mismatch")
        return cls(**{key: str(value[key]) for key in expected})


RemoteProjectionV1 = RemoteResultProjectionV1 | RemoteInspectionProjectionV1 | RemoteActivationProjectionV1 | RemoteFullPlanActivationProjectionV1


def parse_remote_projection(value: Mapping[str, Any]) -> RemoteProjectionV1:
    schema = value.get("schema_version")
    if schema == _RESULT_SCHEMA:
        return RemoteResultProjectionV1.from_mapping(value)
    if schema == _INSPECTION_RESULT_SCHEMA:
        return RemoteInspectionProjectionV1.from_mapping(value)
    if schema == _ACTIVATION_RESULT_SCHEMA:
        return RemoteActivationProjectionV1.from_mapping(value)
    if schema == _FULL_PLAN_ACTIVATION_RESULT_SCHEMA:
        return RemoteFullPlanActivationProjectionV1.from_mapping(value)
    raise RemoteOperatorOutboxError("projection schema mismatch")


def _secret_like_inspection(projection: RemoteProjectionV1) -> bool:
    return isinstance(projection, RemoteInspectionProjectionV1) and bool(
        _INSPECTION_SECRET.search(canonical_json_bytes(projection.to_dict()))
    )


class RemoteResultOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RemoteOperatorOutboxError("unsafe outbox root")
        self.pending_root = self.root / "pending"
        self.published_root = self.root / "published"
        self.quarantined_root = self.root / "quarantined"
        for path in (self.root, self.pending_root, self.published_root, self.quarantined_root):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise RemoteOperatorOutboxError("unsafe outbox path")
            path.mkdir(parents=True, exist_ok=True)

    def _path(self, root: Path, projection_id: str) -> Path:
        return root / f"{_safe_id(projection_id, 'projection ID')}.json"

    @staticmethod
    def _load(path: Path) -> RemoteProjectionV1 | None:
        previous = path.with_suffix(path.suffix + ".prev")
        if path.is_symlink() or previous.is_symlink():
            raise RemoteOperatorOutboxError("outbox state is a symlink")
        if not path.exists() and not previous.exists():
            return None
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorOutboxError("outbox state invalid") from exc
        return parse_remote_projection(value)

    def _quarantine(self, projection: RemoteInspectionProjectionV1, *, pending_path: Path | None = None) -> None:
        quarantine_path = self._path(self.quarantined_root, projection.projection_id)
        existing = self._load(quarantine_path)
        if existing is not None and existing.projection_sha256 != projection.projection_sha256:
            raise RemoteOperatorOutboxError("conflicting quarantined projection ID")
        try:
            if existing is None:
                durable_json_save(quarantine_path, projection.to_dict())
            if pending_path is not None and pending_path.exists():
                pending_path.unlink()
            if pending_path is not None:
                previous = pending_path.with_suffix(pending_path.suffix + ".prev")
                if previous.exists():
                    previous.unlink()
        except (DurableIOError, OSError, ValueError) as exc:
            raise RemoteOperatorOutboxError("projection quarantine failed") from exc

    def enqueue_projection(self, projection: RemoteProjectionV1) -> None:
        if _secret_like_inspection(projection):
            self._quarantine(projection)
            raise RemoteOperatorOutboxError("SECRET_LIKE_PROJECTION")
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

    def pending(self) -> tuple[RemoteProjectionV1, ...]:
        result: list[RemoteProjectionV1] = []
        for path in sorted(self.pending_root.glob("*.json")):
            if path.name.endswith(".prev"):
                continue
            projection = self._load(path)
            if projection is None:
                continue
            if self._load(self._path(self.published_root, projection.projection_id)) is not None:
                continue
            if _secret_like_inspection(projection):
                self._quarantine(projection, pending_path=path)
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

    def publish_pending(self, publisher: Callable[[RemoteProjectionV1], Any]) -> int:
        count = 0
        for projection in self.pending():
            publisher(projection)
            self.mark_published(projection.projection_id, projection.projection_sha256)
            count += 1
        return count

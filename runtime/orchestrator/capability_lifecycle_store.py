"""Durable local registry for external capability lifecycle records."""
from __future__ import annotations

import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path

from .capability_lifecycle import (
    CapabilityLifecycleError,
    CapabilityLifecycleRecordV1,
    transition_capability_lifecycle,
)
from .durable_io import DurableIOError, atomic_write_json, durable_json_load


class CapabilityLifecycleStoreError(ValueError):
    pass


def _safe_contract_filename(contract_id: str) -> str:
    raw = str(contract_id)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)
    if not safe:
        raise CapabilityLifecycleStoreError("unsafe contract id")

    if safe == raw:
        if len(safe) > 180:
            raise CapabilityLifecycleStoreError("unsafe contract id")
        return safe + ".json"

    stem = safe[:150].rstrip("_") or "contract"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{stem}-{digest}.json"


def _legacy_contract_filename(contract_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(contract_id))
    if not safe or len(safe) > 180:
        raise CapabilityLifecycleStoreError("unsafe contract id")
    return safe + ".json"


class CapabilityLifecycleStore:
    def __init__(self, root: str | Path) -> None:
        base = Path(root).resolve()
        if base.is_symlink():
            raise CapabilityLifecycleStoreError("unsafe lifecycle root")
        self.root = base / "capability-lifecycle"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, contract_id: str) -> Path:
        return self.root / _safe_contract_filename(contract_id)

    def _read_path(self, contract_id: str) -> Path:
        path = self._path(contract_id)
        if path.exists():
            return path
        legacy_path = self.root / _legacy_contract_filename(contract_id)
        if legacy_path.exists():
            return legacy_path
        return path

    @contextmanager
    def _contract_lock(self, contract_id: str):
        lock_path = self.root / (_safe_contract_filename(contract_id) + ".lock")
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def put(self, record: CapabilityLifecycleRecordV1) -> Path:
        if not isinstance(record, CapabilityLifecycleRecordV1) or not record.valid():
            raise CapabilityLifecycleStoreError("lifecycle record digest mismatch")
        try:
            return atomic_write_json(
                self._path(record.contract.contract_id), record.to_dict()
            )
        except DurableIOError as exc:
            raise CapabilityLifecycleStoreError(str(exc)) from exc

    def get(self, contract_id: str) -> CapabilityLifecycleRecordV1:
        path = self._read_path(contract_id)
        try:
            payload, _ = durable_json_load(path)
            record = CapabilityLifecycleRecordV1.from_mapping(payload)
        except FileNotFoundError:
            raise
        except (DurableIOError, CapabilityLifecycleError) as exc:
            message = (
                "lifecycle record digest mismatch"
                if "digest" in str(exc).lower()
                else str(exc)
            )
            raise CapabilityLifecycleStoreError(message) from exc
        if record.contract.contract_id != contract_id:
            raise CapabilityLifecycleStoreError("lifecycle record identity mismatch")
        if not record.valid():
            raise CapabilityLifecycleStoreError("lifecycle record digest mismatch")
        return record

    def acquire_dependency(self, contract_id: str, task_execution_id: str) -> CapabilityLifecycleRecordV1:
        with self._contract_lock(contract_id):
            record = self.get(contract_id)
            if record.state in {"DISABLE_NEW_ASSIGNMENT", "DRAINING", "SUPERSEDED", "DEPRECATED", "RETIRED"}:
                raise CapabilityLifecycleStoreError("new assignment disabled")
            ids = tuple(sorted(set(record.active_dependency_ids) | {str(task_execution_id)}))
            updated = record.with_dependencies(ids)
            self.put(updated)
            return updated

    def release_dependency(self, contract_id: str, task_execution_id: str) -> CapabilityLifecycleRecordV1:
        with self._contract_lock(contract_id):
            record = self.get(contract_id)
            ids = tuple(item for item in record.active_dependency_ids if item != str(task_execution_id))
            updated = record.with_dependencies(ids)
            self.put(updated)
            return updated

    def begin_drain(self, contract_id: str, *, evidence_ref: str) -> CapabilityLifecycleRecordV1:
        with self._contract_lock(contract_id):
            record = self.get(contract_id)
            if record.state not in {"ACTIVE", "DEGRADED", "QUARANTINED"}:
                raise CapabilityLifecycleStoreError("capability cannot enter drain from current state")
            try:
                disabled = transition_capability_lifecycle(record, "DISABLE_NEW_ASSIGNMENT", (evidence_ref,))
                draining = transition_capability_lifecycle(disabled, "DRAINING", (evidence_ref,))
            except CapabilityLifecycleError as exc:
                raise CapabilityLifecycleStoreError(str(exc)) from exc
            self.put(draining)
            return draining

    def list_records(self) -> tuple[CapabilityLifecycleRecordV1, ...]:
        records: list[CapabilityLifecycleRecordV1] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload, _ = durable_json_load(path)
                record = CapabilityLifecycleRecordV1.from_mapping(payload)
            except (DurableIOError, CapabilityLifecycleError, FileNotFoundError) as exc:
                raise CapabilityLifecycleStoreError(
                    f"invalid lifecycle record: {path.name}"
                ) from exc
            if not record.valid():
                raise CapabilityLifecycleStoreError("lifecycle record digest mismatch")
            records.append(record)
        return tuple(records)

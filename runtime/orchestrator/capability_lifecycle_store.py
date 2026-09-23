"""Durable local registry for external capability lifecycle records."""
from __future__ import annotations

from pathlib import Path

from .capability_lifecycle import (
    CapabilityLifecycleError,
    CapabilityLifecycleRecordV1,
)
from .durable_io import DurableIOError, atomic_write_json, durable_json_load


class CapabilityLifecycleStoreError(ValueError):
    pass


def _safe_contract_filename(contract_id: str) -> str:
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
        path = self._path(contract_id)
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

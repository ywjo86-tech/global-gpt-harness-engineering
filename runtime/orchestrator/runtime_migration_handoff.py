"""Durable, authority-bounded runtime migration transaction state."""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json, canonical_json_bytes, sha256_bytes

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40_64 = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MIGRATION_SCHEMA_V1 = "orchestration.runtime-migration.v1"
MIGRATION_SCHEMA_V2 = "orchestration.runtime-migration.v2"


class MigrationHandoffError(ValueError):
    pass


class MigrationPhase(str, Enum):
    PREPARED = "PREPARED"
    PREDECESSOR_QUIESCED = "PREDECESSOR_QUIESCED"
    RUNTIME_ACTIVATED = "RUNTIME_ACTIVATED"
    SUCCESSOR_REGISTERED = "SUCCESSOR_REGISTERED"
    SUCCESSOR_VERIFIED = "SUCCESSOR_VERIFIED"
    ACTIVE_RUNTIME_QUALIFICATION = "ACTIVE_RUNTIME_QUALIFICATION"
    PREDECESSOR_CLOSED = "PREDECESSOR_CLOSED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"


_FORWARD_V1 = {
    MigrationPhase.PREPARED: MigrationPhase.PREDECESSOR_QUIESCED,
    MigrationPhase.PREDECESSOR_QUIESCED: MigrationPhase.RUNTIME_ACTIVATED,
    MigrationPhase.RUNTIME_ACTIVATED: MigrationPhase.SUCCESSOR_REGISTERED,
    MigrationPhase.SUCCESSOR_REGISTERED: MigrationPhase.SUCCESSOR_VERIFIED,
    MigrationPhase.SUCCESSOR_VERIFIED: MigrationPhase.PREDECESSOR_CLOSED,
}
_FORWARD_V2 = {
    MigrationPhase.PREPARED: MigrationPhase.PREDECESSOR_QUIESCED,
    MigrationPhase.PREDECESSOR_QUIESCED: MigrationPhase.RUNTIME_ACTIVATED,
    MigrationPhase.RUNTIME_ACTIVATED: MigrationPhase.SUCCESSOR_REGISTERED,
    MigrationPhase.SUCCESSOR_REGISTERED: MigrationPhase.SUCCESSOR_VERIFIED,
    MigrationPhase.SUCCESSOR_VERIFIED: MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION,
    MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION: MigrationPhase.PREDECESSOR_CLOSED,
}
_BINDING_FIELDS = {
    "migration_id", "project_id", "predecessor_run_id", "successor_run_id", "current_gate", "resume_gate",
    "approved_plan_sha256", "approved_spec_sha256", "authority_core_sha256", "predecessor_state_sha256",
    "source_head", "target_release_head", "target_manifest_sha256", "successor_job_spec_sha256",
}
_V2_BINDING_FIELDS = _BINDING_FIELDS | {"source_tree", "source_manifest_sha256"}
_V1_SERIALIZED_FIELDS = _BINDING_FIELDS | {
    "phase", "created_at", "updated_at", "quiesced_state_sha256", "block_reason", "rollback_reason", "transaction_sha256",
}
_V2_SERIALIZED_FIELDS = _V1_SERIALIZED_FIELDS | {
    "schema_version", "source_tree", "source_manifest_sha256", "qualification_evidence_sha256", "restored_runtime_evidence_sha256",
}


@dataclass(frozen=True, slots=True)
class RuntimeMigrationTransaction:
    migration_id: str
    project_id: str
    predecessor_run_id: str
    successor_run_id: str
    current_gate: str
    resume_gate: str
    approved_plan_sha256: str
    approved_spec_sha256: str
    authority_core_sha256: str
    predecessor_state_sha256: str
    source_head: str
    target_release_head: str
    target_manifest_sha256: str
    successor_job_spec_sha256: str
    phase: MigrationPhase
    created_at: str
    updated_at: str
    quiesced_state_sha256: str = ""
    block_reason: str = ""
    rollback_reason: str = ""
    schema_version: str = MIGRATION_SCHEMA_V1
    source_tree: str = ""
    source_manifest_sha256: str = ""
    qualification_evidence_sha256: str = ""
    restored_runtime_evidence_sha256: str = ""
    transaction_sha256: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _payload(tx: RuntimeMigrationTransaction, *, signed: bool = True) -> dict[str, Any]:
    data = asdict(tx)
    data["phase"] = tx.phase.value
    if tx.schema_version == MIGRATION_SCHEMA_V1:
        data = {key: data[key] for key in _V1_SERIALIZED_FIELDS}
    elif tx.schema_version == MIGRATION_SCHEMA_V2:
        data = {key: data[key] for key in _V2_SERIALIZED_FIELDS}
    else:
        raise MigrationHandoffError("migration schema version invalid")
    if not signed:
        data.pop("transaction_sha256", None)
    return data


def _sign(tx: RuntimeMigrationTransaction) -> RuntimeMigrationTransaction:
    digest = sha256_bytes(canonical_json_bytes(_payload(tx, signed=False)))
    return replace(tx, transaction_sha256=digest)


def _validate(tx: RuntimeMigrationTransaction) -> None:
    if tx.schema_version not in {MIGRATION_SCHEMA_V1, MIGRATION_SCHEMA_V2}:
        raise MigrationHandoffError("migration schema version invalid")
    for name in ("migration_id", "project_id", "predecessor_run_id", "successor_run_id", "current_gate", "resume_gate"):
        if not _SAFE_ID.fullmatch(str(getattr(tx, name))):
            raise MigrationHandoffError(f"unsafe {name}")
    for name in (
        "approved_plan_sha256", "approved_spec_sha256", "authority_core_sha256", "predecessor_state_sha256",
        "target_manifest_sha256", "successor_job_spec_sha256",
    ):
        if not _SHA256.fullmatch(str(getattr(tx, name))):
            raise MigrationHandoffError(f"invalid {name}")
    for name in ("source_head", "target_release_head"):
        if not _SHA40_64.fullmatch(str(getattr(tx, name))):
            raise MigrationHandoffError(f"invalid {name}")
    if tx.schema_version == MIGRATION_SCHEMA_V1:
        if any((tx.source_tree, tx.source_manifest_sha256, tx.qualification_evidence_sha256, tx.restored_runtime_evidence_sha256)):
            raise MigrationHandoffError("v1 migration contains v2-only evidence")
        if tx.phase == MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION:
            raise MigrationHandoffError("v1 migration cannot enter active runtime qualification")
    else:
        if not _SHA40_64.fullmatch(tx.source_tree):
            raise MigrationHandoffError("invalid source_tree")
        if not _SHA256.fullmatch(tx.source_manifest_sha256):
            raise MigrationHandoffError("invalid source_manifest_sha256")
        if tx.qualification_evidence_sha256 and not _SHA256.fullmatch(tx.qualification_evidence_sha256):
            raise MigrationHandoffError("invalid qualification evidence")
        if tx.restored_runtime_evidence_sha256 and not _SHA256.fullmatch(tx.restored_runtime_evidence_sha256):
            raise MigrationHandoffError("invalid restored runtime evidence")
        if tx.phase in {MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION, MigrationPhase.PREDECESSOR_CLOSED} and not tx.qualification_evidence_sha256:
            raise MigrationHandoffError("active runtime qualification evidence is required")
    if tx.quiesced_state_sha256 and not _SHA256.fullmatch(tx.quiesced_state_sha256):
        raise MigrationHandoffError("invalid quiesced_state_sha256")
    if tx.phase in {
        MigrationPhase.PREDECESSOR_QUIESCED, MigrationPhase.RUNTIME_ACTIVATED,
        MigrationPhase.SUCCESSOR_REGISTERED, MigrationPhase.SUCCESSOR_VERIFIED,
        MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION, MigrationPhase.PREDECESSOR_CLOSED,
    } and not tx.quiesced_state_sha256:
        raise MigrationHandoffError("quiesced predecessor state binding missing")
    if not tx.created_at or not tx.updated_at:
        raise MigrationHandoffError("transaction timestamps missing")
    expected = sha256_bytes(canonical_json_bytes(_payload(tx, signed=False)))
    if tx.transaction_sha256 != expected:
        raise MigrationHandoffError("transaction SHA mismatch")


class MigrationStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise MigrationHandoffError("unsafe migration store root")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise MigrationHandoffError("unsafe migration store root")

    def path(self, migration_id: str) -> Path:
        if not _SAFE_ID.fullmatch(str(migration_id)):
            raise MigrationHandoffError("unsafe migration id")
        return self.root / f"{migration_id}.json"

    def _create(self, spec: Mapping[str, Any], *, schema_version: str) -> RuntimeMigrationTransaction:
        expected = _BINDING_FIELDS if schema_version == MIGRATION_SCHEMA_V1 else _V2_BINDING_FIELDS
        if set(spec) != expected:
            raise MigrationHandoffError("migration specification fields mismatch")
        now = _now()
        values = {key: str(spec[key]) for key in expected}
        tx = RuntimeMigrationTransaction(
            **{key: values[key] for key in _BINDING_FIELDS},
            phase=MigrationPhase.PREPARED, created_at=now, updated_at=now,
            schema_version=schema_version,
            source_tree=values.get("source_tree", ""), source_manifest_sha256=values.get("source_manifest_sha256", ""),
        )
        tx = _sign(tx); _validate(tx)
        lock_path = self.root / ".create.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise MigrationHandoffError("migration create lock is unsafe")
            fcntl.flock(fd, fcntl.LOCK_EX)
            for existing_path in sorted(self.root.glob("*.json")):
                existing = self.load(existing_path.stem)
                if (existing.project_id == tx.project_id and existing.predecessor_run_id == tx.predecessor_run_id
                        and existing.phase != MigrationPhase.ROLLED_BACK):
                    raise MigrationHandoffError("predecessor migration already exists")
            path = self.path(tx.migration_id)
            if path.exists():
                raise MigrationHandoffError("migration transaction already exists")
            atomic_write_json(path, _payload(tx))
            return tx
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def create(self, spec: Mapping[str, Any]) -> RuntimeMigrationTransaction:
        return self._create(spec, schema_version=MIGRATION_SCHEMA_V1)

    def create_v2(self, spec: Mapping[str, Any]) -> RuntimeMigrationTransaction:
        return self._create(spec, schema_version=MIGRATION_SCHEMA_V2)

    def load(self, migration_id: str) -> RuntimeMigrationTransaction:
        path = self.path(migration_id)
        if path.is_symlink() or not path.is_file():
            raise MigrationHandoffError("migration transaction missing or unsafe")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MigrationHandoffError("migration transaction malformed") from exc
        if not isinstance(raw, dict):
            raise MigrationHandoffError("migration transaction fields mismatch")
        if set(raw) == _V1_SERIALIZED_FIELDS:
            normalized = dict(raw)
            normalized["schema_version"] = MIGRATION_SCHEMA_V1
            normalized["source_tree"] = ""
            normalized["source_manifest_sha256"] = ""
            normalized["qualification_evidence_sha256"] = ""
            normalized["restored_runtime_evidence_sha256"] = ""
        elif set(raw) == _V2_SERIALIZED_FIELDS and raw.get("schema_version") == MIGRATION_SCHEMA_V2:
            normalized = dict(raw)
        else:
            raise MigrationHandoffError("migration transaction fields mismatch")
        try:
            normalized["phase"] = MigrationPhase(str(normalized["phase"]))
            tx = RuntimeMigrationTransaction(**normalized)
        except Exception as exc:
            raise MigrationHandoffError("migration transaction values invalid") from exc
        _validate(tx)
        return tx

    def _save(self, tx: RuntimeMigrationTransaction) -> RuntimeMigrationTransaction:
        tx = _sign(replace(tx, updated_at=_now()))
        _validate(tx)
        atomic_write_json(self.path(tx.migration_id), _payload(tx))
        return tx

    def advance(self, migration_id: str, phase: MigrationPhase, *, updates: Mapping[str, Any] | None = None) -> RuntimeMigrationTransaction:
        tx = self.load(migration_id); phase = MigrationPhase(phase)
        forward = _FORWARD_V2 if tx.schema_version == MIGRATION_SCHEMA_V2 else _FORWARD_V1
        if forward.get(tx.phase) != phase:
            if tx.schema_version == MIGRATION_SCHEMA_V2 and tx.phase == MigrationPhase.SUCCESSOR_VERIFIED and phase == MigrationPhase.PREDECESSOR_CLOSED:
                raise MigrationHandoffError("active runtime qualification is required before predecessor close")
            raise MigrationHandoffError("illegal migration phase transition")
        changes = dict(updates or {})
        immutable = _V2_BINDING_FIELDS if tx.schema_version == MIGRATION_SCHEMA_V2 else _BINDING_FIELDS
        if any(key in immutable for key in changes):
            raise MigrationHandoffError("migration authority/identity binding is immutable")
        if phase == MigrationPhase.PREDECESSOR_QUIESCED:
            if set(changes) != {"quiesced_state_sha256"}:
                raise MigrationHandoffError("quiesced predecessor state binding is required")
            qsha = str(changes["quiesced_state_sha256"])
            if tx.quiesced_state_sha256 or not _SHA256.fullmatch(qsha):
                raise MigrationHandoffError("invalid quiesced predecessor state binding")
            tx = replace(tx, quiesced_state_sha256=qsha)
        elif phase == MigrationPhase.ACTIVE_RUNTIME_QUALIFICATION:
            if tx.schema_version != MIGRATION_SCHEMA_V2 or set(changes) != {"qualification_evidence_sha256"}:
                raise MigrationHandoffError("active runtime qualification evidence is required")
            digest = str(changes["qualification_evidence_sha256"])
            if tx.qualification_evidence_sha256 or not _SHA256.fullmatch(digest):
                raise MigrationHandoffError("invalid active runtime qualification evidence")
            tx = replace(tx, qualification_evidence_sha256=digest)
        elif changes:
            raise MigrationHandoffError("unsupported migration transition update")
        return self._save(replace(tx, phase=phase, block_reason="", rollback_reason=""))

    def record_restored_runtime_evidence(self, migration_id: str, evidence_sha256: str) -> RuntimeMigrationTransaction:
        tx = self.load(migration_id)
        if tx.schema_version != MIGRATION_SCHEMA_V2:
            raise MigrationHandoffError("restored runtime evidence requires migration v2")
        digest = str(evidence_sha256 or "")
        if tx.phase in {MigrationPhase.PREDECESSOR_CLOSED, MigrationPhase.ROLLED_BACK} or not _SHA256.fullmatch(digest):
            raise MigrationHandoffError("restored runtime evidence is not legal")
        if tx.restored_runtime_evidence_sha256 and tx.restored_runtime_evidence_sha256 != digest:
            raise MigrationHandoffError("conflicting restored runtime evidence")
        return self._save(replace(tx, restored_runtime_evidence_sha256=digest))

    def block(self, migration_id: str, reason: str) -> RuntimeMigrationTransaction:
        tx = self.load(migration_id)
        if tx.phase in {MigrationPhase.PREDECESSOR_CLOSED, MigrationPhase.ROLLED_BACK}:
            raise MigrationHandoffError("terminal migration cannot be blocked")
        if not str(reason).strip():
            raise MigrationHandoffError("block reason required")
        return self._save(replace(tx, phase=MigrationPhase.BLOCKED, block_reason=str(reason).strip()))

    def rollback(self, migration_id: str, reason: str) -> RuntimeMigrationTransaction:
        tx = self.load(migration_id)
        if tx.phase in {MigrationPhase.PREDECESSOR_CLOSED, MigrationPhase.ROLLED_BACK}:
            raise MigrationHandoffError("migration rollback is no longer legal")
        if not str(reason).strip():
            raise MigrationHandoffError("rollback reason required")
        return self._save(replace(tx, phase=MigrationPhase.ROLLED_BACK, rollback_reason=str(reason).strip()))


def migration_store_root(harness_root: str | Path, project_id: str) -> Path:
    if not _SAFE_ID.fullmatch(str(project_id or "")):
        raise MigrationHandoffError("unsafe migration project id")
    return Path(harness_root).resolve() / "_workspace" / "runtime-migrations" / str(project_id)


def discover_predecessor_transactions(harness_root: str | Path, project_id: str, run_id: str) -> tuple[RuntimeMigrationTransaction, ...]:
    root = migration_store_root(harness_root, project_id)
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise MigrationHandoffError("unsafe migration store root")
    store = MigrationStore(root)
    found: list[RuntimeMigrationTransaction] = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise MigrationHandoffError("unsafe migration transaction file")
        tx = store.load(path.stem)
        if tx.project_id == project_id and tx.predecessor_run_id == run_id:
            found.append(tx)
    return tuple(found)

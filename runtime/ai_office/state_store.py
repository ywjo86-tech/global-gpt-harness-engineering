from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    AIOfficeContractError,
    OFFICE_STATE_SNAPSHOT_SCHEMA_V1,
    OFFICE_STATE_TRANSITION_SCHEMA_V1,
    OfficeStateSnapshotV1,
    OfficeStateTransitionV1,
    canonical_digest,
)

JOURNAL_RECORD_SCHEMA_V1 = "ai-office.state-journal-record.v1"


class AIOfficeStateStoreError(ValueError):
    pass
def _safe_component(value: str, label: str) -> str:
    item = str(value).strip()
    if not item or len(item) > 160 or "/" in item or "\\" in item or ".." in item:
        raise AIOfficeStateStoreError(f"unsafe {label}")
    return item


class AIOfficeStateStore:
    def __init__(self, workspace_root: str | Path, *, project_id: str, run_id: str):
        root = Path(workspace_root).resolve()
        if root.is_symlink():
            raise AIOfficeStateStoreError("unsafe workspace root")
        self.project_id = _safe_component(project_id, "project_id")
        self.run_id = _safe_component(run_id, "run_id")
        self.root = root / "_workspace" / "ai-office" / f"{self.project_id}--{self.run_id}"
        self.snapshot_path = self.root / "snapshot.json"
        self.journal_path = self.root / "transitions.jsonl"
        self.lock_path = self.root / "state.lock"

    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        handle = os.fdopen(fd, "a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle
    @staticmethod
    def _unlock(handle: Any) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temp_name, path)
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    def initialize(self, *, approved_plan_ref: str, baseline_ref: str,
                   workflow_state: str = "NEW") -> OfficeStateSnapshotV1:
        handle = self._lock()
        try:
            if self.snapshot_path.exists() or self.journal_path.exists():
                raise AIOfficeStateStoreError("AI Office run identity already exists")
            snapshot = OfficeStateSnapshotV1(
                OFFICE_STATE_SNAPSHOT_SCHEMA_V1, self.project_id, self.run_id, 0,
                workflow_state, approved_plan_ref, baseline_ref,
            )
            self.journal_path.touch(mode=0o600, exist_ok=False)
            self._atomic_json(self.snapshot_path, snapshot.to_dict())
            return snapshot
        except (OSError, AIOfficeContractError) as exc:
            if isinstance(exc, AIOfficeStateStoreError):
                raise
            raise AIOfficeStateStoreError(str(exc)) from exc
        finally:
            self._unlock(handle)

    def _read_snapshot(self) -> OfficeStateSnapshotV1:
        if self.snapshot_path.is_symlink() or not self.snapshot_path.is_file():
            raise AIOfficeStateStoreError("state snapshot missing or unsafe")
        try:
            value = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            snapshot = OfficeStateSnapshotV1.from_mapping(value)
        except (OSError, UnicodeError, json.JSONDecodeError, AIOfficeContractError, TypeError, ValueError) as exc:
            raise AIOfficeStateStoreError("state snapshot corrupt") from exc
        if snapshot.project_id != self.project_id or snapshot.run_id != self.run_id:
            raise AIOfficeStateStoreError("state snapshot identity mismatch")
        return snapshot

    def _read_journal(self) -> tuple[OfficeStateSnapshotV1 | None, str]:
        if self.journal_path.is_symlink() or not self.journal_path.is_file():
            raise AIOfficeStateStoreError("state journal missing or unsafe")
        previous_record_digest = ""
        previous_snapshot: OfficeStateSnapshotV1 | None = None
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise AIOfficeStateStoreError("state journal unreadable") from exc
        for index, raw in enumerate(lines, 1):
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AIOfficeStateStoreError("state journal corrupt") from exc
            expected = {"schema_version", "transition", "snapshot", "previous_record_digest", "record_digest"}
            if not isinstance(record, dict) or set(record) != expected or record["schema_version"] != JOURNAL_RECORD_SCHEMA_V1:
                raise AIOfficeStateStoreError("state journal shape mismatch")
            unsigned = {key: record[key] for key in record if key != "record_digest"}
            if str(record["record_digest"]) != canonical_digest(unsigned):
                raise AIOfficeStateStoreError("state journal record digest mismatch")
            if str(record["previous_record_digest"]) != previous_record_digest:
                raise AIOfficeStateStoreError("state journal digest chain mismatch")
            try:
                snapshot = OfficeStateSnapshotV1.from_mapping(record["snapshot"])
                data = record["transition"]
                transition = OfficeStateTransitionV1(
                    str(data["schema_version"]), str(data["project_id"]), str(data["run_id"]),
                    int(data["sequence"]), int(data["from_revision"]), int(data["to_revision"]),
                    str(data["from_state"]), str(data["to_state"]), str(data["reason_ref"]),
                    str(data["previous_transition_digest"]),
                )
            except (KeyError, TypeError, ValueError, AIOfficeContractError) as exc:
                raise AIOfficeStateStoreError("state journal transition invalid") from exc
            if data.get("transition_digest") != transition.transition_digest:
                raise AIOfficeStateStoreError("transition digest mismatch")
            if transition.sequence != index or transition.project_id != self.project_id or transition.run_id != self.run_id:
                raise AIOfficeStateStoreError("transition identity mismatch")
            if snapshot.revision != transition.to_revision or snapshot.workflow_state != transition.to_state:
                raise AIOfficeStateStoreError("transition result binding mismatch")
            if snapshot.last_transition_digest != transition.transition_digest:
                raise AIOfficeStateStoreError("snapshot transition binding mismatch")
            if previous_snapshot is not None:
                if (transition.from_revision != previous_snapshot.revision or
                        transition.from_state != previous_snapshot.workflow_state or
                        transition.previous_transition_digest != previous_snapshot.last_transition_digest):
                    raise AIOfficeStateStoreError("transition predecessor mismatch")
            elif transition.from_revision != 0 or transition.previous_transition_digest:
                raise AIOfficeStateStoreError("first transition predecessor mismatch")
            previous_snapshot = snapshot
            previous_record_digest = str(record["record_digest"])
        return previous_snapshot, previous_record_digest
    def load(self) -> OfficeStateSnapshotV1:
        snapshot = self._read_snapshot()
        journal_snapshot, _ = self._read_journal()
        if journal_snapshot is None:
            if snapshot.revision != 0 or snapshot.last_transition_digest:
                raise AIOfficeStateStoreError("snapshot/journal revision mismatch")
            return snapshot
        if snapshot.to_dict() != journal_snapshot.to_dict():
            raise AIOfficeStateStoreError("snapshot/journal final-state mismatch")
        return snapshot

    def transition(self, *, to_state: str, reason_ref: str,
                   workflow_refs: tuple[str, ...] | None = None,
                   pending_approval_ref: str | None = None,
                   pending_manual_action_ref: str | None = None) -> OfficeStateSnapshotV1:
        handle = self._lock()
        try:
            current = self.load()
            revision = current.revision + 1
            transition = OfficeStateTransitionV1(
                OFFICE_STATE_TRANSITION_SCHEMA_V1, self.project_id, self.run_id,
                revision, current.revision, revision, current.workflow_state, to_state,
                reason_ref, current.last_transition_digest,
            )
            snapshot = OfficeStateSnapshotV1(
                OFFICE_STATE_SNAPSHOT_SCHEMA_V1, self.project_id, self.run_id, revision, to_state,
                current.approved_plan_ref, current.baseline_ref,
                current.workflow_refs if workflow_refs is None else tuple(workflow_refs),
                current.pending_approval_ref if pending_approval_ref is None else pending_approval_ref,
                current.pending_manual_action_ref if pending_manual_action_ref is None else pending_manual_action_ref,
                transition.transition_digest,
            )
            _, previous_record_digest = self._read_journal()
            record = {
                "schema_version": JOURNAL_RECORD_SCHEMA_V1,
                "transition": transition.to_dict(),
                "snapshot": snapshot.to_dict(),
                "previous_record_digest": previous_record_digest,
            }
            record["record_digest"] = canonical_digest(record)
            data = (json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
            fd = os.open(str(self.journal_path), os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._atomic_json(self.snapshot_path, snapshot.to_dict())
            return self.load()
        except (OSError, AIOfficeContractError, json.JSONDecodeError) as exc:
            if isinstance(exc, AIOfficeStateStoreError):
                raise
            raise AIOfficeStateStoreError(str(exc)) from exc
        finally:
            self._unlock(handle)

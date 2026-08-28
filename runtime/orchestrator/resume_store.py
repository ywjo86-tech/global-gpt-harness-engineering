from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


class ResumeStoreError(ValueError):
    pass


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LIFECYCLE = ("PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION", "CHECKPOINT", "EXIT", "HANDOFF")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _check_sha(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ResumeStoreError(f"invalid {field} SHA-256")


@dataclass(frozen=True)
class RunBinding:
    project_id: str
    gate_id: str
    lv_id: str
    run_id: str
    requirements_sha256: str
    plan_sha256: str
    branch: str
    head: str
    artifact_sha256: str
    owned_content_sha256: Mapping[str, str]

    def validate(self) -> None:
        for field in ("project_id", "gate_id", "lv_id", "run_id"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise ResumeStoreError(f"unsafe {field}")
        for field in ("requirements_sha256", "plan_sha256", "artifact_sha256"):
            _check_sha(getattr(self, field), field)
        if not self.branch or not re.fullmatch(r"[A-Za-z0-9._/-]+", self.branch) or ".." in self.branch:
            raise ResumeStoreError("unsafe branch")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.head):
            raise ResumeStoreError("invalid HEAD")
        if not self.owned_content_sha256:
            raise ResumeStoreError("owned-content binding is empty")
        for path, digest in self.owned_content_sha256.items():
            candidate = Path(path)
            if not path or candidate.is_absolute() or ".." in candidate.parts or "\\" in path:
                raise ResumeStoreError("unsafe owned-file path")
            _check_sha(digest, f"owned content {path}")

    def payload(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        value["owned_content_sha256"] = dict(sorted(self.owned_content_sha256.items()))
        return value


class ResumeStore:
    """Append-only, hash-chained persistent lifecycle store for one bound run."""

    def __init__(self, root: str | Path, binding: RunBinding):
        binding.validate()
        base = Path(root)
        if base.exists() and base.is_symlink():
            raise ResumeStoreError("resume root must not be a symlink")
        self.binding = binding
        self.run_root = base / binding.project_id / binding.gate_id / binding.lv_id / binding.run_id
        self.events = self.run_root / "events"

    def _event_paths(self) -> list[Path]:
        if not self.events.exists():
            return []
        if self.events.is_symlink():
            raise ResumeStoreError("event directory must not be a symlink")
        paths = sorted(self.events.glob("*.json"))
        if [path.name for path in paths] != [f"{index:06d}.json" for index in range(1, len(paths) + 1)]:
            raise ResumeStoreError("event sequence is missing, duplicated, or reordered")
        return paths

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise ResumeStoreError("immutable event must not be a symlink")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResumeStoreError("immutable event is unreadable") from exc
        if not isinstance(value, dict):
            raise ResumeStoreError("immutable event is not an object")
        return value

    def verify(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        prior = None
        expected_binding = self.binding.payload()
        for index, path in enumerate(self._event_paths(), 1):
            record = self._read(path)
            seal = record.get("event_sha256")
            unsigned = {key: value for key, value in record.items() if key != "event_sha256"}
            if seal != _hash(unsigned):
                raise ResumeStoreError("event SHA drift detected")
            if record.get("sequence") != index or record.get("previous_event_sha256") != prior:
                raise ResumeStoreError("event hash lineage drift detected")
            if record.get("binding") != expected_binding:
                raise ResumeStoreError("run binding drift detected")
            if record.get("lifecycle") not in _LIFECYCLE:
                raise ResumeStoreError("unknown lifecycle stage")
            prior = seal
            records.append(record)
        return records

    def append(
        self,
        lifecycle: str,
        evidence_sha256: str,
        *,
        checkpoint: bool = False,
        remediation_lineage: Mapping[str, Any] | None = None,
        owned_content_sha256: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if lifecycle not in _LIFECYCLE:
            raise ResumeStoreError("unknown lifecycle stage")
        _check_sha(evidence_sha256, "evidence")
        records = self.verify()
        current_owned = dict(owned_content_sha256 or self.binding.owned_content_sha256)
        for path, digest in current_owned.items():
            _check_sha(digest, f"owned content {path}")
        remediation = dict(remediation_lineage or {})
        if lifecycle == "REMEDIATION":
            required = {"parent_event_sha256", "before_owned_sha256", "after_owned_sha256"}
            if set(remediation) != required:
                raise ResumeStoreError("remediation lineage field mismatch")
            if not records or remediation["parent_event_sha256"] != records[-1]["event_sha256"]:
                raise ResumeStoreError("remediation parent lineage mismatch")
            if remediation["before_owned_sha256"] == remediation["after_owned_sha256"]:
                raise ResumeStoreError("remediation did not bind changed owned content")
            _check_sha(remediation["before_owned_sha256"], "remediation before-owned")
            _check_sha(remediation["after_owned_sha256"], "remediation after-owned")
        elif remediation:
            raise ResumeStoreError("remediation lineage is only valid for REMEDIATION")
        record: dict[str, Any] = {
            "schema_version": "orchestration.resume.event.v1",
            "sequence": len(records) + 1,
            "binding": self.binding.payload(),
            "lifecycle": lifecycle,
            "evidence_sha256": evidence_sha256,
            "owned_content_sha256": dict(sorted(current_owned.items())),
            "checkpoint": bool(checkpoint),
            "remediation_lineage": remediation or None,
            "previous_event_sha256": records[-1]["event_sha256"] if records else None,
        }
        record["event_sha256"] = _hash(record)
        self.events.mkdir(parents=True, exist_ok=True)
        target = self.events / f"{record['sequence']:06d}.json"
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(_canonical(record))
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ResumeStoreError("immutable event already exists") from exc
        return record

    def resume(self, observed: RunBinding, observed_owned_content_sha256: Mapping[str, str]) -> dict[str, Any]:
        if observed.payload() != self.binding.payload():
            raise ResumeStoreError("branch/HEAD/requirements/plan/artifact run binding drift detected")
        records = self.verify()
        if not records:
            raise ResumeStoreError("no persistent checkpoint exists")
        checkpoints = [record for record in records if record["checkpoint"]]
        if not checkpoints:
            raise ResumeStoreError("no persistent checkpoint exists")
        latest = checkpoints[-1]
        if dict(observed_owned_content_sha256) != latest["owned_content_sha256"]:
            raise ResumeStoreError("owned-file content drift detected")
        return {
            "status": "RESUME_READY",
            "checkpoint": latest,
            "next_sequence": len(records) + 1,
            "last_event_sha256": records[-1]["event_sha256"],
            "hard_stop": True,
        }

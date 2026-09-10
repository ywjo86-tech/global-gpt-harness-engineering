from __future__ import annotations

import hashlib
import json
import os
import re
import fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


class ResumeStoreError(ValueError):
    pass


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LIFECYCLE = ("PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION", "CHECKPOINT", "EXIT", "HANDOFF")
_CAPABILITY_RESUME_STAGES = (
    "REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "DISCOVERY_COMPLETED",
    "RAW_CANDIDATE", "CONTENT_RESOLVED", "IMMUTABLE_PROVENANCE_VERIFIED",
    "EVALUATED", "ADOPTION_DECIDED", "INSTALL_AUTHORIZED", "INSTALL_COMPLETED",
    "ATTESTED", "USE_AUTHORIZED", "USED_ASSET_BOUND", "RUNTIME_SELECTION_READY",
)
_CAPABILITY_ROUTE_STAGES = {
    "NO_REQUIREMENT": ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"),
    "DECLARED_NONE": ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"),
    "EXISTING_PROJECT": ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"),
    "EXISTING_GLOBAL": ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"),
    "EXISTING_AGENT": ("REQUIREMENT_DERIVED", "INVENTORY_CHECKED", "RUNTIME_SELECTION_READY"),
    "DISCOVERED_PROJECT_INSTALL": _CAPABILITY_RESUME_STAGES,
}


def allowed_capability_transition(route: str, previous_stage: str | None, next_stage: str) -> bool:
    """Return whether a capability checkpoint transition is valid for route."""
    stages = _CAPABILITY_ROUTE_STAGES.get(route)
    if stages is None or next_stage not in stages:
        return False
    if previous_stage is None:
        return next_stage == stages[0]
    try:
        index = stages.index(previous_stage)
    except ValueError:
        return False
    return index + 1 < len(stages) and stages[index + 1] == next_stage


# Short compatibility spelling used by the orchestration contract.
allowed_transition = allowed_capability_transition


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

    @contextmanager
    def run_lease(self):
        """Acquire the exclusive lease for this persisted run."""
        self.run_root.mkdir(parents=True, exist_ok=True)
        path = self.run_root / ".run.lock"
        handle = path.open("a+")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ResumeStoreError("run lease unavailable") from exc
            yield self
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

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
        stage_payload: Mapping[str, Any] | None = None,
        checkpoint_payload: Mapping[str, Any] | None = None,
        expected_previous_event_digest: str | None = None,
    ) -> dict[str, Any]:
        if lifecycle not in _LIFECYCLE:
            raise ResumeStoreError("unknown lifecycle stage")
        _check_sha(evidence_sha256, "evidence")
        records = self.verify()
        current_previous = records[-1]["event_sha256"] if records else None
        if expected_previous_event_digest is not None and expected_previous_event_digest != current_previous:
            raise ResumeStoreError("stale expected previous event digest; reload required")
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
            "stage_payload": dict(stage_payload or {}),
            "checkpoint_payload": dict(checkpoint_payload or {}) if checkpoint else None,
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

    def append_effect_intent(self, *, effect_id: str, stage: str, target: str,
                             requirement_digest: str, evidence_sha256: str) -> dict[str, Any]:
        """Record a mutating effect intent in the canonical event chain."""
        _check_sha(effect_id, "effect")
        _check_sha(requirement_digest, "capability requirement")
        _check_sha(evidence_sha256, "effect evidence")
        for record in self.verify():
            payload = record.get("stage_payload")
            if isinstance(payload, dict) and payload.get("effect", {}).get("effect_id") == effect_id:
                return record
        payload = {"effect": {"state": "EFFECT_INTENT", "effect_id": effect_id,
                               "stage": stage, "target": target,
                               "requirement_digest": requirement_digest}}
        return self.append("WORKER", evidence_sha256, stage_payload=payload)

    def append_effect_receipt(self, *, effect_id: str, stage: str, target: str,
                              requirement_digest: str, evidence_sha256: str,
                              receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Record an applied-effect receipt; duplicate receipts are read-idempotent."""
        _check_sha(effect_id, "effect")
        _check_sha(requirement_digest, "capability requirement")
        _check_sha(evidence_sha256, "effect evidence")
        if not isinstance(receipt, Mapping):
            raise ResumeStoreError("effect receipt is malformed")
        for record in self.verify():
            payload = record.get("stage_payload")
            effect = payload.get("effect") if isinstance(payload, dict) else None
            if isinstance(effect, dict) and effect.get("effect_id") == effect_id and effect.get("state") == "EFFECT_RECEIPT":
                return record
        payload = {"effect": {"state": "EFFECT_RECEIPT", "effect_id": effect_id,
                               "stage": stage, "target": target,
                               "requirement_digest": requirement_digest,
                               "receipt": dict(receipt)}}
        return self.append("WORKER", evidence_sha256, stage_payload=payload)

    def effect_records(self, effect_id: str) -> list[dict[str, Any]]:
        _check_sha(effect_id, "effect")
        result = []
        for record in self.verify():
            payload = record.get("stage_payload")
            effect = payload.get("effect") if isinstance(payload, dict) else None
            if isinstance(effect, dict) and effect.get("effect_id") == effect_id:
                result.append(record)
        return result

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
            "checkpoint_payload": latest.get("checkpoint_payload") or {},
            "hard_stop": True,
        }

    def append_capability_checkpoint(
        self,
        stage: str,
        *,
        requirement_digest: str,
        evidence_sha256: str,
        evidence_references: Mapping[str, str] | None = None,
        projection: Mapping[str, Any] | None = None,
        stage_record: Mapping[str, Any] | None = None,
        route: str = "DISCOVERED_PROJECT_INSTALL",
        contract_version: str = "v1",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Persist a capability checkpoint in the canonical run event chain.

        Capability stages are payload metadata on the existing WORKER event
        namespace; no parallel capability store is created.  The run binding
        remains authoritative for project/Gate/LV/plan identity.
        """
        if route not in _CAPABILITY_ROUTE_STAGES or stage not in _CAPABILITY_ROUTE_STAGES[route]:
            raise ResumeStoreError("unknown capability resume stage")
        if contract_version != "v1":
            raise ResumeStoreError("unsupported capability checkpoint contract version")
        _check_sha(requirement_digest, "capability requirement")
        _check_sha(evidence_sha256, "capability evidence")
        refs = dict(evidence_references or {})
        if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in refs.items()):
            raise ResumeStoreError("capability evidence references are malformed")
        records = self.verify()
        stages = _CAPABILITY_ROUTE_STAGES[route]
        payload = {
            "schema_version": "orchestration.capability-resume.v1",
            "reader_min_version": "v1",
            "stage": stage,
            "next_stage": stages[stages.index(stage) + 1] if stages.index(stage) + 1 < len(stages) else None,
            "route": route,
            "project_id": self.binding.project_id,
            "gate_id": self.binding.gate_id,
            "lv_id": self.binding.lv_id,
            "run_id": self.binding.run_id,
            "canonical_plan_sha256": self.binding.plan_sha256,
            "requirement_digest": requirement_digest,
            "stage_evidence_sha256": evidence_sha256,
            "evidence_references": dict(sorted(refs.items())),
            "artifact_refs": dict(sorted(refs.items())),
            "previous_event_digest": records[-1]["event_sha256"] if records else None,
            "contract_version": contract_version,
            "timestamp": timestamp or "",
        }
        if projection is not None:
            payload["projection"] = dict(projection)
        if stage_record is not None:
            payload["stage_record"] = dict(stage_record)
        payload["checkpoint_digest"] = _hash(payload)
        existing = [record for record in self.verify()
                    if isinstance(record.get("checkpoint_payload"), dict)
                    and record["checkpoint_payload"].get("schema_version") == "orchestration.capability-resume.v1"
                    and record["checkpoint_payload"].get("stage") == stage]
        if existing:
            prior = existing[-1].get("checkpoint_payload")
            comparable = lambda value: {key: item for key, item in value.items()
                                        if key not in {"previous_event_digest", "checkpoint_digest"}}
            if not isinstance(prior, dict) or comparable(prior) != comparable(payload):
                raise ResumeStoreError("duplicate capability checkpoint conflicts with sealed evidence")
            return existing[-1]
        return self.append(
            "WORKER", evidence_sha256, checkpoint=True,
            stage_payload={"capability_checkpoint": payload},
            checkpoint_payload=payload,
        )

    def resume_capability(
        self,
        observed: RunBinding,
        observed_owned_content_sha256: Mapping[str, str],
        *,
        requirement_digest: str,
        stage: str | None = None,
        route: str | None = None,
    ) -> dict[str, Any]:
        """Load and revalidate the latest capability checkpoint after restart."""
        resumed = self.resume(observed, observed_owned_content_sha256)
        payload = resumed.get("checkpoint_payload") or {}
        if not isinstance(payload, dict) or payload.get("schema_version") != "orchestration.capability-resume.v1":
            raise ResumeStoreError("capability checkpoint is missing or malformed")
        if payload.get("reader_min_version") != "v1":
            raise ResumeStoreError("unsupported capability checkpoint reader version")
        if stage is not None and payload.get("stage") != stage:
            raise ResumeStoreError("capability checkpoint stage mismatch")
        if route is not None and payload.get("route") != route:
            raise ResumeStoreError("capability checkpoint route mismatch")
        if payload.get("requirement_digest") != requirement_digest:
            raise ResumeStoreError("capability requirement drift detected")
        unsigned = {key: value for key, value in payload.items() if key != "checkpoint_digest"}
        if payload.get("checkpoint_digest") != _hash(unsigned):
            raise ResumeStoreError("capability checkpoint digest drift detected")
        return resumed

    def capability_checkpoints(self) -> list[dict[str, Any]]:
        """Return the verified capability stage chain, rejecting gaps."""
        records = self.verify()
        checkpoints = []
        for record in records:
            payload = record.get("checkpoint_payload")
            if isinstance(payload, dict) and payload.get("schema_version") == "orchestration.capability-resume.v1":
                checkpoints.append(payload)
        route = None
        previous = None
        for payload in checkpoints:
            payload_route = payload.get("route")
            if route is None:
                route = payload_route
            if payload_route != route or not isinstance(payload_route, str):
                raise ResumeStoreError("capability checkpoint route mismatch")
            stage = payload.get("stage")
            if payload.get("reader_min_version") != "v1" or payload.get("contract_version") != "v1":
                raise ResumeStoreError("unsupported capability checkpoint version")
            if not allowed_capability_transition(payload_route, previous, stage):
                raise ResumeStoreError("capability checkpoint stage dependency mismatch")
            stages = _CAPABILITY_ROUTE_STAGES[payload_route]
            expected_next = stages[stages.index(stage) + 1] if stages.index(stage) + 1 < len(stages) else None
            if payload.get("next_stage") != expected_next:
                raise ResumeStoreError("capability checkpoint next-stage mismatch")
            unsigned = {key: value for key, value in payload.items() if key != "checkpoint_digest"}
            if payload.get("checkpoint_digest") != _hash(unsigned):
                raise ResumeStoreError("capability checkpoint digest drift detected")
            previous = stage
            if (payload.get("project_id") != self.binding.project_id or payload.get("gate_id") != self.binding.gate_id
                    or payload.get("lv_id") != self.binding.lv_id or payload.get("run_id") != self.binding.run_id
                    or payload.get("canonical_plan_sha256") != self.binding.plan_sha256):
                raise ResumeStoreError("capability checkpoint binding drift detected")
        return checkpoints

    def capability_resume_cursor(self) -> dict[str, Any] | None:
        """Return the last verified stage and its continuation target."""
        checkpoints = self.capability_checkpoints()
        if not checkpoints:
            return None
        latest = checkpoints[-1]
        return {
            "route": latest["route"],
            "stage": latest["stage"],
            "next_stage": latest.get("next_stage"),
            "requirement_digest": latest["requirement_digest"],
            "projection": latest.get("projection"),
            "checkpoint_digest": latest["checkpoint_digest"],
        }

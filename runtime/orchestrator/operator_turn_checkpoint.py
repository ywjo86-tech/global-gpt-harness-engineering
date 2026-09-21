"""Immutable evidence-only checkpoints for safe GPT Operator turn yield."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .durable_io import atomic_write_json

SCHEMA_VERSION = "orchestration.operator-turn-checkpoint.v1"
POINTER_SCHEMA = "orchestration.operator-turn-checkpoint-pointer.v1"
CONTROL_AUTHORITY = "NONE"
CHECKPOINT_KINDS = frozenset({"AUTONOMOUS_OWNER_BOUND", "OPERATOR_HANDOFF_CHECKPOINT"})
OWNER_KINDS = frozenset({"FULL_PLAN", "DCC", "RECONCILER", "OPERATOR_HANDOFF"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,179}\Z")


class OperatorTurnCheckpointError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if _SAFE_ID.fullmatch(text) is None:
        raise OperatorTurnCheckpointError(f"invalid {label}")
    return text


def _sha(value: object, label: str) -> str:
    text = str(value or "")
    if _SHA256.fullmatch(text) is None:
        raise OperatorTurnCheckpointError(f"invalid {label}")
    return text


def _timestamp(value: object, label: str) -> str:
    text = str(value or "")
    try:
        observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OperatorTurnCheckpointError(f"invalid {label}") from exc
    if observed.tzinfo is None:
        raise OperatorTurnCheckpointError(f"invalid {label}")
    return observed.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class OperatorTurnCheckpoint:
    schema_version: str
    project_id: str
    run_id: str
    gate_id_or_stage: str
    authority_core_sha256: str
    checkpoint_kind: str
    owner_kind: str
    owner_ref: str
    resume_contract_sha256: str
    last_semantic_progress_at: str
    created_at: str
    control_authority: str
    checkpoint_sha256: str

    @classmethod
    def create(
        cls, *, project_id: str, run_id: str, gate_id_or_stage: str,
        authority_core_sha256: str, checkpoint_kind: str, owner_kind: str,
        owner_ref: str, resume_contract_sha256: str,
        last_semantic_progress_at: str, created_at: str | None = None,
    ) -> "OperatorTurnCheckpoint":
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "project_id": _safe_id(project_id, "project ID"),
            "run_id": _safe_id(run_id, "run ID"),
            "gate_id_or_stage": _safe_id(gate_id_or_stage, "Gate/stage ID"),
            "authority_core_sha256": _sha(authority_core_sha256, "authority digest"),
            "checkpoint_kind": str(checkpoint_kind),
            "owner_kind": str(owner_kind),
            "owner_ref": str(owner_ref or "").strip(),
            "resume_contract_sha256": _sha(resume_contract_sha256, "resume contract digest"),
            "last_semantic_progress_at": _timestamp(last_semantic_progress_at, "semantic progress timestamp"),
            "created_at": _timestamp(created_at or _now(), "created timestamp"),
            "control_authority": CONTROL_AUTHORITY,
        }
        if unsigned["checkpoint_kind"] not in CHECKPOINT_KINDS:
            raise OperatorTurnCheckpointError("unsupported checkpoint kind")
        if unsigned["owner_kind"] not in OWNER_KINDS:
            raise OperatorTurnCheckpointError("unsupported checkpoint owner")
        if not unsigned["owner_ref"] or len(unsigned["owner_ref"]) > 512 or "\n" in unsigned["owner_ref"]:
            raise OperatorTurnCheckpointError("invalid checkpoint owner ref")
        if (unsigned["checkpoint_kind"] == "OPERATOR_HANDOFF_CHECKPOINT"
                and unsigned["owner_kind"] != "OPERATOR_HANDOFF"):
            raise OperatorTurnCheckpointError("operator handoff checkpoint requires operator handoff owner")
        if (unsigned["checkpoint_kind"] == "AUTONOMOUS_OWNER_BOUND"
                and unsigned["owner_kind"] not in {"FULL_PLAN", "DCC", "RECONCILER"}):
            raise OperatorTurnCheckpointError("autonomous checkpoint requires autonomous owner")
        return cls(**unsigned, checkpoint_sha256=_digest(unsigned))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperatorTurnCheckpoint":
        if not isinstance(value, Mapping):
            raise OperatorTurnCheckpointError("checkpoint object required")
        fields = {
            "schema_version", "project_id", "run_id", "gate_id_or_stage",
            "authority_core_sha256", "checkpoint_kind", "owner_kind", "owner_ref",
            "resume_contract_sha256", "last_semantic_progress_at", "created_at",
            "control_authority", "checkpoint_sha256",
        }
        if set(value) != fields:
            raise OperatorTurnCheckpointError("checkpoint fields mismatch")
        checkpoint = cls(**{name: str(value[name]) for name in fields})
        checkpoint.validate()
        return checkpoint

    def unsigned_dict(self) -> dict[str, str]:
        value = asdict(self)
        value.pop("checkpoint_sha256")
        return value

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.control_authority != CONTROL_AUTHORITY:
            raise OperatorTurnCheckpointError("checkpoint schema/authority mismatch")
        _safe_id(self.project_id, "project ID")
        _safe_id(self.run_id, "run ID")
        _safe_id(self.gate_id_or_stage, "Gate/stage ID")
        _sha(self.authority_core_sha256, "authority digest")
        _sha(self.resume_contract_sha256, "resume contract digest")
        _timestamp(self.last_semantic_progress_at, "semantic progress timestamp")
        _timestamp(self.created_at, "created timestamp")
        if self.checkpoint_kind not in CHECKPOINT_KINDS or self.owner_kind not in OWNER_KINDS:
            raise OperatorTurnCheckpointError("checkpoint kind/owner mismatch")
        if not self.owner_ref or len(self.owner_ref) > 512 or "\n" in self.owner_ref:
            raise OperatorTurnCheckpointError("invalid checkpoint owner ref")
        if self.checkpoint_kind == "OPERATOR_HANDOFF_CHECKPOINT" and self.owner_kind != "OPERATOR_HANDOFF":
            raise OperatorTurnCheckpointError("operator handoff checkpoint owner mismatch")
        if self.checkpoint_kind == "AUTONOMOUS_OWNER_BOUND" and self.owner_kind not in {"FULL_PLAN", "DCC", "RECONCILER"}:
            raise OperatorTurnCheckpointError("autonomous checkpoint owner mismatch")
        if self.checkpoint_sha256 != _digest(self.unsigned_dict()):
            raise OperatorTurnCheckpointError("checkpoint digest mismatch")


class OperatorTurnCheckpointStore:
    def __init__(self, state_root: str | Path, *, project_id: str, run_id: str) -> None:
        root = Path(state_root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise OperatorTurnCheckpointError("checkpoint state root is unsafe")
        self.project_id = _safe_id(project_id, "project ID")
        self.run_id = _safe_id(run_id, "run ID")
        self.base = root / "operator-turn-checkpoints" / self.project_id / self.run_id

    def save(self, checkpoint: OperatorTurnCheckpoint) -> OperatorTurnCheckpoint:
        checkpoint.validate()
        if checkpoint.project_id != self.project_id or checkpoint.run_id != self.run_id:
            raise OperatorTurnCheckpointError("checkpoint store identity mismatch")
        self.base.mkdir(parents=True, exist_ok=True)
        if self.base.is_symlink():
            raise OperatorTurnCheckpointError("checkpoint store is unsafe")
        path = self.base / f"{checkpoint.checkpoint_sha256}.json"
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise OperatorTurnCheckpointError("checkpoint path is unsafe")
            existing = self._load_file(path)
            if existing != checkpoint:
                raise OperatorTurnCheckpointError("checkpoint digest collision")
        else:
            atomic_write_json(path, checkpoint.to_dict())
        pointer = {
            "schema_version": POINTER_SCHEMA,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "checkpoint_file": path.name,
            "control_authority": CONTROL_AUTHORITY,
        }
        pointer["pointer_sha256"] = _digest(pointer)
        atomic_write_json(self.base / "latest.json", pointer)
        return checkpoint

    def _load_file(self, path: Path) -> OperatorTurnCheckpoint:
        if path.is_symlink() or not path.is_file():
            raise OperatorTurnCheckpointError("checkpoint file is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorTurnCheckpointError("checkpoint file is malformed") from exc
        return OperatorTurnCheckpoint.from_dict(value)

    def load_latest(self) -> OperatorTurnCheckpoint:
        pointer_path = self.base / "latest.json"
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise OperatorTurnCheckpointError("latest checkpoint pointer is unavailable")
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorTurnCheckpointError("latest checkpoint pointer is malformed") from exc
        if not isinstance(pointer, dict) or pointer.get("schema_version") != POINTER_SCHEMA:
            raise OperatorTurnCheckpointError("latest checkpoint pointer schema mismatch")
        expected = str(pointer.get("pointer_sha256") or "")
        unsigned = {k: v for k, v in pointer.items() if k != "pointer_sha256"}
        if expected != _digest(unsigned) or pointer.get("control_authority") != CONTROL_AUTHORITY:
            raise OperatorTurnCheckpointError("latest checkpoint pointer digest mismatch")
        if pointer.get("project_id") != self.project_id or pointer.get("run_id") != self.run_id:
            raise OperatorTurnCheckpointError("latest checkpoint pointer identity mismatch")
        name = str(pointer.get("checkpoint_file") or "")
        if not name or Path(name).name != name:
            raise OperatorTurnCheckpointError("latest checkpoint pointer path is invalid")
        checkpoint = self._load_file(self.base / name)
        if checkpoint.checkpoint_sha256 != pointer.get("checkpoint_sha256"):
            raise OperatorTurnCheckpointError("latest checkpoint pointer binding mismatch")
        return checkpoint

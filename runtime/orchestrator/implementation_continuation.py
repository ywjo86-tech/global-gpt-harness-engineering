"""Durable TDD continuation overlay for approved Full Plan implementation work.

This module owns no worker, router, effect, approval, or OCP authority.  It
persists intent/evidence and derives the next *eligible* TDD phase only after
callers revalidate canonical source, approval, authority and environment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

from .durable_io import DurableIOError, durable_json_load, durable_json_save


CONTRACT_SCHEMA = "orchestration.expected-red-contract.v1"
OBSERVATION_SCHEMA = "orchestration.tdd-failure-observation.v1"
CHECKPOINT_SCHEMA = "orchestration.tdd-continuation-checkpoint.v1"
POINTER_SCHEMA = "orchestration.tdd-continuation-pointer.v1"

LEGACY = "LEGACY"
TDD_V1 = "TDD_V1"
CONTINUATION_MODES = frozenset({LEGACY, TDD_V1})
FOCUSED_TDD = "FOCUSED_TDD"

PHASES = frozenset({
    "RED_ARMED", "RED_RUNNING", "GREEN_READY", "GREEN_RUNNING",
    "FOCUSED_VALIDATION", "REGRESSION_VALIDATION", "COMPLETED", "BLOCKED",
})
SAFE_EFFECT_RECONCILIATION = frozenset({"NO_EFFECT", "RECONCILED"})
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,179}\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class TDDContinuationError(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if _SAFE_ID.fullmatch(text) is None:
        raise TDDContinuationError(f"invalid {label}")
    return text


def _sha(value: object, label: str, *, git: bool = False) -> str:
    text = str(value or "")
    pattern = _SHA if git else _SHA256
    if pattern.fullmatch(text) is None:
        raise TDDContinuationError(f"invalid {label}")
    return text


def _timestamp(value: object, label: str) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise TDDContinuationError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise TDDContinuationError(f"invalid {label}")
    return parsed.astimezone(timezone.utc)


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_scope(value: object) -> str:
    text = str(value or "")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "\\" in text or text.startswith("./"):
        raise TDDContinuationError("invalid remediation scope")
    return text


def _scope_contains(scope: str, path: str) -> bool:
    base = scope.rstrip("/")
    return path == base or path.startswith(base + "/")


@dataclass(frozen=True, slots=True)
class ExpectedRedContractV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    tdd_cycle_id: str
    source_sha: str
    authority_digest: str
    test_kind: str
    test_selector: str
    test_command_digest: str
    dependency_environment_digest: str
    expected_failure_semantic_signature: str
    expected_failure_count: int
    allowed_error_count: int
    valid_until: str
    allowed_change_paths: tuple[str, ...]
    max_remediation_attempts: int
    contract_digest: str

    @classmethod
    def create(
        cls, *, project_id: str, run_id: str, task_id: str, tdd_cycle_id: str,
        source_sha: str, authority_digest: str, test_kind: str, test_selector: str,
        test_command_digest: str, dependency_environment_digest: str,
        expected_failure_semantic_signature: str, expected_failure_count: int,
        allowed_error_count: int, valid_until: str,
        allowed_change_paths: Sequence[str], max_remediation_attempts: int,
    ) -> "ExpectedRedContractV1":
        if test_kind != FOCUSED_TDD:
            raise TDDContinuationError("Expected RED is limited to focused TDD")
        selector = str(test_selector or "").strip()
        if not selector or "\n" in selector:
            raise TDDContinuationError("invalid test selector")
        failures = int(expected_failure_count)
        errors = int(allowed_error_count)
        remediation = int(max_remediation_attempts)
        if failures < 1 or errors < 0 or remediation < 0:
            raise TDDContinuationError("invalid TDD count boundary")
        expiry = _timestamp(valid_until, "validity boundary")
        scopes = tuple(_safe_scope(item) for item in allowed_change_paths)
        if not scopes or len(set(scopes)) != len(scopes):
            raise TDDContinuationError("invalid remediation scope")
        unsigned = {
            "schema_version": CONTRACT_SCHEMA,
            "project_id": _safe_id(project_id, "project_id"),
            "run_id": _safe_id(run_id, "run_id"),
            "task_id": _safe_id(task_id, "task_id"),
            "tdd_cycle_id": _safe_id(tdd_cycle_id, "tdd_cycle_id"),
            "source_sha": _sha(source_sha, "source_sha", git=True),
            "authority_digest": _sha(authority_digest, "authority_digest"),
            "test_kind": FOCUSED_TDD,
            "test_selector": selector,
            "test_command_digest": _sha(test_command_digest, "test_command_digest"),
            "dependency_environment_digest": _sha(
                dependency_environment_digest, "dependency_environment_digest"),
            "expected_failure_semantic_signature": _sha(
                expected_failure_semantic_signature, "expected_failure_semantic_signature"),
            "expected_failure_count": failures,
            "allowed_error_count": errors,
            "valid_until": _canonical_timestamp(expiry),
            "allowed_change_paths": scopes,
            "max_remediation_attempts": remediation,
        }
        digest = _digest({**unsigned, "allowed_change_paths": list(scopes)})
        return cls(**unsigned, contract_digest=digest)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExpectedRedContractV1":
        if not isinstance(value, Mapping):
            raise TDDContinuationError("Expected RED contract object required")
        fields = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != fields:
            raise TDDContinuationError("Expected RED contract fields mismatch")
        try:
            rebuilt = cls.create(
                project_id=str(value["project_id"]), run_id=str(value["run_id"]),
                task_id=str(value["task_id"]), tdd_cycle_id=str(value["tdd_cycle_id"]),
                source_sha=str(value["source_sha"]), authority_digest=str(value["authority_digest"]),
                test_kind=str(value["test_kind"]), test_selector=str(value["test_selector"]),
                test_command_digest=str(value["test_command_digest"]),
                dependency_environment_digest=str(value["dependency_environment_digest"]),
                expected_failure_semantic_signature=str(value["expected_failure_semantic_signature"]),
                expected_failure_count=int(value["expected_failure_count"]),
                allowed_error_count=int(value["allowed_error_count"]),
                valid_until=str(value["valid_until"]),
                allowed_change_paths=tuple(value["allowed_change_paths"]),
                max_remediation_attempts=int(value["max_remediation_attempts"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TDDContinuationError("Expected RED contract malformed") from exc
        if value.get("schema_version") != CONTRACT_SCHEMA or rebuilt.contract_digest != value.get("contract_digest"):
            raise TDDContinuationError("Expected RED contract digest mismatch")
        return rebuilt

    def unsigned_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("contract_digest")
        value["allowed_change_paths"] = list(self.allowed_change_paths)
        return value

    def to_mapping(self) -> dict[str, Any]:
        return {**self.unsigned_mapping(), "contract_digest": self.contract_digest}

    def validate(self, *, now: datetime | None = None) -> None:
        rebuilt = ExpectedRedContractV1.create(
            project_id=self.project_id, run_id=self.run_id, task_id=self.task_id,
            tdd_cycle_id=self.tdd_cycle_id, source_sha=self.source_sha,
            authority_digest=self.authority_digest, test_kind=self.test_kind,
            test_selector=self.test_selector, test_command_digest=self.test_command_digest,
            dependency_environment_digest=self.dependency_environment_digest,
            expected_failure_semantic_signature=self.expected_failure_semantic_signature,
            expected_failure_count=self.expected_failure_count,
            allowed_error_count=self.allowed_error_count, valid_until=self.valid_until,
            allowed_change_paths=self.allowed_change_paths,
            max_remediation_attempts=self.max_remediation_attempts,
        )
        if rebuilt.contract_digest != self.contract_digest:
            raise TDDContinuationError("Expected RED contract digest mismatch")
        if now is not None and now.astimezone(timezone.utc) >= _timestamp(self.valid_until, "validity boundary"):
            raise TDDContinuationError("Expected RED contract expired")


@dataclass(frozen=True, slots=True)
class FailureObservationV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    tdd_cycle_id: str
    source_sha: str
    authority_digest: str
    test_kind: str
    test_selector: str
    test_command_digest: str
    dependency_environment_digest: str
    outcome: str
    failure_semantic_signature: str
    failure_count: int
    error_count: int
    receipt_digest: str

    @classmethod
    def create(
        cls, *, project_id: str, run_id: str, task_id: str, tdd_cycle_id: str,
        source_sha: str, authority_digest: str, test_kind: str, test_selector: str,
        test_command_digest: str, dependency_environment_digest: str, outcome: str,
        failure_semantic_signature: str, failure_count: int, error_count: int,
        receipt_digest: str,
    ) -> "FailureObservationV1":
        selector = str(test_selector or "").strip()
        if not selector or "\n" in selector:
            raise TDDContinuationError("invalid test selector")
        if outcome not in {"FAILED", "PASSED", "TIMEOUT", "INFRA_ERROR", "CANCELLED"}:
            raise TDDContinuationError("invalid RED observation outcome")
        failures = int(failure_count); errors = int(error_count)
        if failures < 0 or errors < 0:
            raise TDDContinuationError("invalid RED observation counts")
        return cls(
            schema_version=OBSERVATION_SCHEMA,
            project_id=_safe_id(project_id, "project_id"), run_id=_safe_id(run_id, "run_id"),
            task_id=_safe_id(task_id, "task_id"), tdd_cycle_id=_safe_id(tdd_cycle_id, "tdd_cycle_id"),
            source_sha=_sha(source_sha, "source_sha", git=True),
            authority_digest=_sha(authority_digest, "authority_digest"),
            test_kind=str(test_kind), test_selector=selector,
            test_command_digest=_sha(test_command_digest, "test_command_digest"),
            dependency_environment_digest=_sha(
                dependency_environment_digest, "dependency_environment_digest"),
            outcome=outcome,
            failure_semantic_signature=_sha(failure_semantic_signature, "failure_semantic_signature"),
            failure_count=failures, error_count=errors,
            receipt_digest=_sha(receipt_digest, "receipt_digest"),
        )


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class TDDContinuationCheckpointV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    tdd_cycle_id: str
    contract_digest: str
    phase: str
    revision: int
    authority_digest: str
    source_sha: str
    dependency_environment_digest: str
    next_action: str
    latest_test_receipt_digest: str
    latest_effect_receipt_digest: str
    effect_step_id: str
    remediation_attempts: int
    block_reason: str
    checkpoint_digest: str

    def unsigned_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("checkpoint_digest")
        return value

    def validate(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA or self.phase not in PHASES:
            raise TDDContinuationError("checkpoint schema/phase mismatch")
        _safe_id(self.project_id, "project_id"); _safe_id(self.run_id, "run_id")
        _safe_id(self.task_id, "task_id"); _safe_id(self.tdd_cycle_id, "tdd_cycle_id")
        _sha(self.contract_digest, "contract_digest")
        _sha(self.authority_digest, "authority_digest")
        _sha(self.source_sha, "source_sha", git=True)
        _sha(self.dependency_environment_digest, "dependency_environment_digest")
        if self.revision < 1 or self.remediation_attempts < 0:
            raise TDDContinuationError("checkpoint counters invalid")
        for value, label in (
            (self.latest_test_receipt_digest, "latest_test_receipt_digest"),
            (self.latest_effect_receipt_digest, "latest_effect_receipt_digest"),
            (self.effect_step_id, "effect_step_id"),
        ):
            if value:
                _sha(value, label)
        if self.checkpoint_digest != _digest(self.unsigned_mapping()):
            raise TDDContinuationError("checkpoint digest mismatch")


class TDDContinuationStore:
    def __init__(self, state_root: str | Path, *, project_id: str, run_id: str) -> None:
        root = Path(state_root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise TDDContinuationError("continuation state root is unsafe")
        self.root = root
        self.project_id = _safe_id(project_id, "project_id")
        self.run_id = _safe_id(run_id, "run_id")
        self.base = root / "_workspace" / "full-plan-tdd-continuation" / self.project_id / self.run_id

    def _path(self, task_id: str, cycle_id: str) -> Path:
        return self.base / _safe_id(task_id, "task_id") / f"{_safe_id(cycle_id, 'tdd_cycle_id')}.json"

    def contract_path(self, task_id: str, cycle_id: str) -> Path:
        return self.base / _safe_id(task_id, "task_id") / f"{_safe_id(cycle_id, 'tdd_cycle_id')}.contract.json"

    @property
    def pointer_path(self) -> Path:
        return self.base / "latest.json"

    def _seal(self, payload: Mapping[str, Any]) -> TDDContinuationCheckpointV1:
        unsigned = dict(payload)
        unsigned["checkpoint_digest"] = _digest(unsigned)
        checkpoint = TDDContinuationCheckpointV1(**unsigned)
        checkpoint.validate()
        return checkpoint

    def _write(self, checkpoint: TDDContinuationCheckpointV1) -> TDDContinuationCheckpointV1:
        checkpoint.validate()
        path = self._path(checkpoint.task_id, checkpoint.tdd_cycle_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or self.base.is_symlink():
            raise TDDContinuationError("continuation checkpoint root is unsafe")
        try:
            durable_json_save(path, asdict(checkpoint))
            pointer = {
                "schema_version": POINTER_SCHEMA,
                "project_id": self.project_id,
                "run_id": self.run_id,
                "task_id": checkpoint.task_id,
                "tdd_cycle_id": checkpoint.tdd_cycle_id,
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "checkpoint_file": str(path.relative_to(self.base)),
            }
            pointer["pointer_digest"] = _digest(pointer)
            durable_json_save(self.pointer_path, pointer)
        except (DurableIOError, OSError, ValueError) as exc:
            raise TDDContinuationError("continuation checkpoint write failed") from exc
        return checkpoint

    def _load_checkpoint_path(self, path: Path) -> TDDContinuationCheckpointV1:
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, FileNotFoundError, OSError, ValueError) as exc:
            raise TDDContinuationError("continuation checkpoint unavailable") from exc
        try:
            checkpoint = TDDContinuationCheckpointV1(**value)
        except TypeError as exc:
            raise TDDContinuationError("continuation checkpoint fields mismatch") from exc
        checkpoint.validate()
        if checkpoint.project_id != self.project_id or checkpoint.run_id != self.run_id:
            raise TDDContinuationError("continuation checkpoint identity mismatch")
        return checkpoint

    def load(self) -> TDDContinuationCheckpointV1:
        try:
            pointer, _ = durable_json_load(self.pointer_path)
        except (DurableIOError, FileNotFoundError, OSError, ValueError) as exc:
            raise TDDContinuationError("continuation pointer unavailable") from exc
        digest = str(pointer.get("pointer_digest") or "")
        unsigned = {key: value for key, value in pointer.items() if key != "pointer_digest"}
        if (pointer.get("schema_version") != POINTER_SCHEMA
                or pointer.get("project_id") != self.project_id
                or pointer.get("run_id") != self.run_id
                or digest != _digest(unsigned)):
            raise TDDContinuationError("continuation pointer invalid")
        rel = str(pointer.get("checkpoint_file") or "")
        candidate = (self.base / rel).resolve()
        if not rel or candidate == self.base or self.base not in candidate.parents:
            raise TDDContinuationError("continuation pointer path invalid")
        checkpoint = self._load_checkpoint_path(candidate)
        if checkpoint.checkpoint_digest != pointer.get("checkpoint_digest"):
            raise TDDContinuationError("continuation pointer binding mismatch")
        return checkpoint

    def _transition(self, current: TDDContinuationCheckpointV1, *, phase: str,
                    next_action: str, block_reason: str = "",
                    latest_test_receipt_digest: str | None = None,
                    latest_effect_receipt_digest: str | None = None,
                    effect_step_id: str | None = None,
                    remediation_attempts: int | None = None) -> TDDContinuationCheckpointV1:
        if phase not in PHASES:
            raise TDDContinuationError("invalid continuation phase")
        payload = current.unsigned_mapping()
        payload.update(
            phase=phase, revision=current.revision + 1, next_action=next_action,
            block_reason=block_reason,
        )
        if latest_test_receipt_digest is not None:
            payload["latest_test_receipt_digest"] = latest_test_receipt_digest
        if latest_effect_receipt_digest is not None:
            payload["latest_effect_receipt_digest"] = latest_effect_receipt_digest
        if effect_step_id is not None:
            payload["effect_step_id"] = effect_step_id
        if remediation_attempts is not None:
            payload["remediation_attempts"] = remediation_attempts
        return self._write(self._seal(payload))

    def _persist_contract(self, contract: ExpectedRedContractV1) -> None:
        path = self.contract_path(contract.task_id, contract.tdd_cycle_id)
        if path.exists() or path.with_suffix(path.suffix + ".prev").exists():
            existing = self._load_contract_path(path)
            if existing.contract_digest != contract.contract_digest:
                raise TDDContinuationError("conflicting Expected RED contract")
            return
        try:
            durable_json_save(path, contract.to_mapping())
        except (DurableIOError, OSError, ValueError) as exc:
            raise TDDContinuationError("Expected RED contract write failed") from exc

    def _load_contract_path(self, path: Path) -> ExpectedRedContractV1:
        try:
            value, _ = durable_json_load(path)
        except (DurableIOError, FileNotFoundError, OSError, ValueError) as exc:
            raise TDDContinuationError("Expected RED contract unavailable") from exc
        return ExpectedRedContractV1.from_mapping(value)

    def load_contract(self) -> ExpectedRedContractV1:
        current = self.load()
        contract = self._load_contract_path(self.contract_path(current.task_id, current.tdd_cycle_id))
        if contract.contract_digest != current.contract_digest:
            raise TDDContinuationError("Expected RED contract/checkpoint binding mismatch")
        return contract

    def arm(self, contract: ExpectedRedContractV1) -> TDDContinuationCheckpointV1:
        contract.validate()
        if contract.project_id != self.project_id or contract.run_id != self.run_id:
            raise TDDContinuationError("Expected RED store identity mismatch")
        self._persist_contract(contract)
        path = self._path(contract.task_id, contract.tdd_cycle_id)
        if path.exists() or path.with_suffix(path.suffix + ".prev").exists():
            existing = self._load_checkpoint_path(path)
            if existing.contract_digest != contract.contract_digest:
                raise TDDContinuationError("conflicting Expected RED contract")
            return existing
        payload = {
            "schema_version": CHECKPOINT_SCHEMA,
            "project_id": contract.project_id, "run_id": contract.run_id,
            "task_id": contract.task_id, "tdd_cycle_id": contract.tdd_cycle_id,
            "contract_digest": contract.contract_digest,
            "phase": "RED_ARMED", "revision": 1,
            "authority_digest": contract.authority_digest,
            "source_sha": contract.source_sha,
            "dependency_environment_digest": contract.dependency_environment_digest,
            "next_action": "RUN_RED",
            "latest_test_receipt_digest": "", "latest_effect_receipt_digest": "",
            "effect_step_id": "", "remediation_attempts": 0, "block_reason": "",
        }
        return self._write(self._seal(payload))

    def begin_red(self, contract_digest: str) -> TDDContinuationCheckpointV1:
        current = self.load()
        if current.contract_digest != _sha(contract_digest, "contract_digest"):
            raise TDDContinuationError("Expected RED contract binding mismatch")
        if current.phase == "RED_RUNNING":
            return current
        if current.phase != "RED_ARMED":
            raise TDDContinuationError("RED may start only from RED_ARMED")
        return self._transition(current, phase="RED_RUNNING", next_action="RUN_RED")

    @staticmethod
    def _observation_is_expected(contract: ExpectedRedContractV1,
                                 observation: FailureObservationV1) -> bool:
        exact = (
            observation.project_id == contract.project_id
            and observation.run_id == contract.run_id
            and observation.task_id == contract.task_id
            and observation.tdd_cycle_id == contract.tdd_cycle_id
            and observation.source_sha == contract.source_sha
            and observation.authority_digest == contract.authority_digest
            and observation.test_kind == contract.test_kind == FOCUSED_TDD
            and observation.test_selector == contract.test_selector
            and observation.test_command_digest == contract.test_command_digest
            and observation.dependency_environment_digest == contract.dependency_environment_digest
            and observation.outcome == "FAILED"
            and observation.failure_semantic_signature == contract.expected_failure_semantic_signature
            and observation.failure_count == contract.expected_failure_count
            and observation.error_count <= contract.allowed_error_count
        )
        return bool(exact)

    def record_red_observation(self, contract: ExpectedRedContractV1,
                               observation: FailureObservationV1, *, now: datetime) -> TDDContinuationCheckpointV1:
        contract.validate(now=now)
        current = self.load()
        if current.phase != "RED_RUNNING" or current.contract_digest != contract.contract_digest:
            raise TDDContinuationError("RED observation checkpoint mismatch")
        if self._observation_is_expected(contract, observation):
            return self._transition(
                current, phase="GREEN_READY", next_action="RUN_GREEN",
                latest_test_receipt_digest=observation.receipt_digest,
            )
        return self._transition(
            current, phase="BLOCKED", next_action="NONE", block_reason="UNEXPECTED_FAILURE",
            latest_test_receipt_digest=observation.receipt_digest,
        )

    def resume(self, contract: ExpectedRedContractV1, *, current_source_sha: str,
               current_authority_digest: str, current_dependency_environment_digest: str,
               approval_valid: bool, now: datetime) -> ContinuationDecision:
        try:
            contract.validate(now=now)
        except TDDContinuationError as exc:
            return ContinuationDecision("BLOCKED", str(exc))
        current = self.load()
        if current.contract_digest != contract.contract_digest:
            return ContinuationDecision("BLOCKED", "CONTRACT_BINDING_MISMATCH")
        if not approval_valid:
            return ContinuationDecision("BLOCKED", "APPROVAL_REVALIDATION_FAILED")
        if current_source_sha != contract.source_sha:
            return ContinuationDecision("BLOCKED", "SOURCE_DRIFT")
        if current_authority_digest != contract.authority_digest:
            return ContinuationDecision("BLOCKED", "AUTHORITY_DRIFT")
        if current_dependency_environment_digest != contract.dependency_environment_digest:
            return ContinuationDecision("BLOCKED", "DEPENDENCY_ENVIRONMENT_DRIFT")
        actions = {
            "RED_ARMED": "RUN_RED",
            "RED_RUNNING": "RUN_RED",
            "GREEN_READY": "RUN_GREEN",
            "FOCUSED_VALIDATION": "RUN_FOCUSED_VALIDATION",
            "REGRESSION_VALIDATION": "RUN_REGRESSION_VALIDATION",
            "COMPLETED": "NOOP",
            "BLOCKED": "BLOCKED",
        }
        if current.phase == "GREEN_RUNNING":
            return ContinuationDecision("BLOCKED_RECONCILIATION_REQUIRED", "GREEN_EFFECT_RECEIPT_REQUIRED")
        return ContinuationDecision(actions[current.phase], "CHECKPOINT_REVALIDATED")

    def begin_green(self, contract: ExpectedRedContractV1) -> TDDContinuationCheckpointV1:
        contract.validate()
        current = self.load()
        if current.contract_digest != contract.contract_digest:
            raise TDDContinuationError("GREEN contract binding mismatch")
        if current.phase == "GREEN_RUNNING":
            raise TDDContinuationError("GREEN effect reconciliation is required before retry")
        if current.phase != "GREEN_READY":
            raise TDDContinuationError("GREEN may start only from GREEN_READY")
        step_id = _digest({
            "project_id": contract.project_id, "run_id": contract.run_id,
            "task_id": contract.task_id, "tdd_cycle_id": contract.tdd_cycle_id,
            "contract_digest": contract.contract_digest,
            "remediation_attempt": current.remediation_attempts,
            "phase": "GREEN",
        })
        return self._transition(
            current, phase="GREEN_RUNNING", next_action="AWAIT_EFFECT_RECEIPT",
            effect_step_id=step_id, latest_effect_receipt_digest="",
        )

    def reconcile_green_effect(self, contract: ExpectedRedContractV1, *, effect_step_id: str,
                               canonical_receipt_digest: str,
                               effect_reconciliation: str) -> TDDContinuationCheckpointV1:
        contract.validate()
        current = self.load()
        if current.phase != "GREEN_RUNNING" or current.contract_digest != contract.contract_digest:
            raise TDDContinuationError("GREEN reconciliation checkpoint mismatch")
        if current.effect_step_id != _sha(effect_step_id, "effect_step_id"):
            raise TDDContinuationError("GREEN effect step binding mismatch")
        receipt = _sha(canonical_receipt_digest, "canonical_receipt_digest")
        if effect_reconciliation not in SAFE_EFFECT_RECONCILIATION:
            raise TDDContinuationError("GREEN effect reconciliation is unsafe")
        return self._transition(
            current, phase="FOCUSED_VALIDATION", next_action="RUN_FOCUSED_VALIDATION",
            latest_effect_receipt_digest=receipt,
        )

    def record_focused_validation(self, *, passed: bool,
                                  receipt_digest: str) -> TDDContinuationCheckpointV1:
        current = self.load()
        if current.phase != "FOCUSED_VALIDATION":
            raise TDDContinuationError("focused validation phase mismatch")
        receipt = _sha(receipt_digest, "focused validation receipt")
        if passed:
            return self._transition(
                current, phase="REGRESSION_VALIDATION", next_action="RUN_REGRESSION_VALIDATION",
                latest_test_receipt_digest=receipt,
            )
        return self._transition(
            current, phase="BLOCKED", next_action="NONE",
            block_reason="FOCUSED_VALIDATION_FAILED", latest_test_receipt_digest=receipt,
        )

    def record_regression_validation(self, *, passed: bool, receipt_digest: str,
                                     regression_delta_current_only: int) -> TDDContinuationCheckpointV1:
        current = self.load()
        if current.phase != "REGRESSION_VALIDATION":
            raise TDDContinuationError("regression validation phase mismatch")
        receipt = _sha(receipt_digest, "regression receipt")
        current_only = int(regression_delta_current_only)
        if passed and current_only == 0:
            return self._transition(
                current, phase="COMPLETED", next_action="NONE",
                latest_test_receipt_digest=receipt,
            )
        return self._transition(
            current, phase="BLOCKED", next_action="NONE",
            block_reason="REGRESSION_VALIDATION_FAILED", latest_test_receipt_digest=receipt,
        )

    def request_bounded_remediation(self, contract: ExpectedRedContractV1, *,
                                    changed_paths: Sequence[str], failure_class: str) -> TDDContinuationCheckpointV1:
        contract.validate()
        current = self.load()
        if (current.phase != "BLOCKED" or current.block_reason != "FOCUSED_VALIDATION_FAILED"
                or current.contract_digest != contract.contract_digest):
            raise TDDContinuationError("bounded remediation is not eligible")
        if failure_class != "IMPLEMENTATION_TEST_FAILURE":
            raise TDDContinuationError("bounded remediation failure class is not eligible")
        if current.remediation_attempts >= contract.max_remediation_attempts:
            raise TDDContinuationError("bounded remediation budget exhausted")
        paths = tuple(_safe_scope(path) for path in changed_paths)
        if not paths or any(not any(_scope_contains(scope, path) for scope in contract.allowed_change_paths)
                            for path in paths):
            raise TDDContinuationError("bounded remediation scope exceeded")
        return self._transition(
            current, phase="GREEN_READY", next_action="RUN_GREEN", block_reason="",
            latest_effect_receipt_digest="", effect_step_id="",
            remediation_attempts=current.remediation_attempts + 1,
        )

"""Durable operator dispatch for activation-bound Harness Lifecycle V2.

This module creates no approval, provider/model, completion, or effect authority.
It records and reconciles the handoff of an already-approved V2 Gate to the
logical GPT_OPERATOR. Legacy operator execution remains in operator_plan_execution.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durable_io import atomic_write_json
from .execution_lifecycle_v2 import (
    ExecutionLifecycleV2Error,
    resolve_lifecycle_binding,
    validate_execution_authority_bundle,
)
from .harness_state_root import job_state_root
from .operator_plan_execution import (
    OperatorPlanExecutionError,
    OperatorPlanReceiptStore,
    _validate_receipt_for_job,
    validate_operator_plan_job,
)

DISPATCH_SCHEMA = "orchestration.operator-dispatch.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,180}\Z")
_SHA40_64 = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class OperatorDispatchError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text):
        raise OperatorDispatchError(f"unsafe {label}")
    return text


def _gate_for_job(job: Mapping[str, Any], gate_id: str) -> Mapping[str, Any]:
    gates = job.get("gates")
    if not isinstance(gates, list):
        raise OperatorDispatchError("V2 job Gate list is malformed")
    matches = [item for item in gates if isinstance(item, Mapping) and str(item.get("gate_id") or "") == gate_id]
    if len(matches) != 1:
        raise OperatorDispatchError("Task is outside approved V2 operator plan")
    return matches[0]


def _dispatch_binding(job: Mapping[str, Any], gate_id: str) -> dict[str, str]:
    try:
        validate_operator_plan_job(job)
        binding = resolve_lifecycle_binding(job)
        if binding.get("lifecycle_mode") != "V2" or binding.get("bound_at_activation") is not True:
            raise OperatorDispatchError("durable dispatch requires activation-bound V2 lifecycle")
        bundle = validate_execution_authority_bundle(job)
    except (OperatorPlanExecutionError, ExecutionLifecycleV2Error) as exc:
        raise OperatorDispatchError(str(exc)) from exc
    gate = _gate_for_job(job, gate_id)
    source_head = str(gate.get("head") or "")
    if not _SHA40_64.fullmatch(source_head):
        raise OperatorDispatchError("V2 dispatch source head is invalid")
    bundle_sha = str(bundle.get("bundle_sha256") or "")
    if not _SHA256.fullmatch(bundle_sha):
        raise OperatorDispatchError("V2 authority bundle digest is invalid")
    lifecycle_sha = _digest(binding)
    return {
        "project_id": _safe_id(job.get("project_id"), "project ID"),
        "run_id": _safe_id(job.get("run_id"), "run ID"),
        "gate_id": _safe_id(gate_id, "Gate ID"),
        "source_head": source_head,
        "plan_sha256": str(job.get("approved_plan_sha256") or ""),
        "spec_sha256": str(job.get("approved_spec_sha256") or ""),
        "lifecycle_binding_sha256": lifecycle_sha,
        "authority_bundle_sha256": bundle_sha,
    }


class OperatorDispatchStore:
    def __init__(self, harness_root: str | Path, *, project_id: str, run_id: str) -> None:
        self.root = Path(harness_root).resolve()
        self.project_id = _safe_id(project_id, "project ID")
        self.run_id = _safe_id(run_id, "run ID")
        self.base = self.root / "_workspace" / "operator-dispatch-v2" / self.project_id / self.run_id

    def _path(self, gate_id: str) -> Path:
        return self.base / f"{_safe_id(gate_id, 'Gate ID')}.json"

    def load(self, gate_id: str) -> dict[str, Any] | None:
        path = self._path(gate_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise OperatorDispatchError("operator dispatch record is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorDispatchError("operator dispatch record is malformed") from exc
        if not isinstance(value, dict) or value.get("schema_version") != DISPATCH_SCHEMA:
            raise OperatorDispatchError("operator dispatch schema mismatch")
        expected = str(value.get("record_sha256") or "")
        unsigned = {key: item for key, item in value.items() if key != "record_sha256"}
        if expected != _digest(unsigned):
            raise OperatorDispatchError("operator dispatch digest mismatch")
        if value.get("project_id") != self.project_id or value.get("run_id") != self.run_id:
            raise OperatorDispatchError("operator dispatch identity mismatch")
        return value

    def prepare(self, job: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
        core = _dispatch_binding(job, gate_id)
        if core["project_id"] != self.project_id or core["run_id"] != self.run_id:
            raise OperatorDispatchError("operator dispatch store/job identity mismatch")
        dispatch_id = f"DSP-{_digest(core)[:32]}"
        existing = self.load(gate_id)
        if existing is not None:
            comparable = {
                key: existing.get(key)
                for key in (
                    "project_id", "run_id", "gate_id", "source_head", "plan_sha256", "spec_sha256",
                    "lifecycle_binding_sha256", "authority_bundle_sha256", "dispatch_id",
                )
            }
            expected = {**core, "dispatch_id": dispatch_id}
            if comparable != expected:
                raise OperatorDispatchError("conflicting operator dispatch already exists")
            return existing
        payload: dict[str, Any] = {
            "schema_version": DISPATCH_SCHEMA,
            **core,
            "dispatch_id": dispatch_id,
            "state": "DISPATCH_PREPARED",
            "created_at": _now(),
            "updated_at": _now(),
        }
        payload["record_sha256"] = _digest(payload)
        path = self._path(gate_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise OperatorDispatchError("operator dispatch root is unsafe")
        atomic_write_json(path, payload)
        return payload

    def _transition(self, gate_id: str, *, expected: str, target: str, also_accept: tuple[str, ...] = ()) -> dict[str, Any]:
        current = self.load(gate_id)
        if current is None:
            raise OperatorDispatchError("operator dispatch is missing")
        state = str(current.get("state") or "")
        if state == target or state in also_accept:
            return current
        if state != expected:
            raise OperatorDispatchError(f"operator dispatch transition rejected: {state}->{target}")
        payload = {key: value for key, value in current.items() if key != "record_sha256"}
        payload["state"] = target
        payload["updated_at"] = _now()
        payload["record_sha256"] = _digest(payload)
        atomic_write_json(self._path(gate_id), payload)
        return payload

    def mark_dispatched(self, gate_id: str) -> dict[str, Any]:
        return self._transition(
            gate_id,
            expected="DISPATCH_PREPARED",
            target="OPERATOR_DISPATCHED",
            also_accept=("OPERATOR_ACKNOWLEDGED",),
        )

    def acknowledge(self, gate_id: str) -> dict[str, Any]:
        return self._transition(
            gate_id,
            expected="OPERATOR_DISPATCHED",
            target="OPERATOR_ACKNOWLEDGED",
        )


def ensure_v2_dispatch(
    job: Mapping[str, Any],
    gate_id: str,
    *,
    dispatch_store: OperatorDispatchStore | None = None,
) -> dict[str, Any]:
    store = dispatch_store or OperatorDispatchStore(
        str(job_state_root(job)), project_id=str(job["project_id"]), run_id=str(job["run_id"])
    )
    prepared = store.prepare(job, gate_id)
    if prepared.get("state") == "DISPATCH_PREPARED":
        return store.mark_dispatched(gate_id)
    return prepared


def build_v2_operator_plan_executor(
    job: Mapping[str, Any],
    *,
    receipt_store: OperatorPlanReceiptStore | None = None,
    dispatch_store: OperatorDispatchStore | None = None,
):
    """V2-only executor seam; the legacy executor remains completely unchanged."""
    try:
        validate_operator_plan_job(job)
        binding = resolve_lifecycle_binding(job)
        if binding.get("lifecycle_mode") != "V2":
            raise OperatorDispatchError("V2 executor requires V2 lifecycle binding")
        validate_execution_authority_bundle(job)
    except (OperatorPlanExecutionError, ExecutionLifecycleV2Error) as exc:
        raise OperatorDispatchError(str(exc)) from exc
    receipts = receipt_store or OperatorPlanReceiptStore(
        str(job_state_root(job)), project_id=str(job["project_id"]), run_id=str(job["run_id"])
    )
    dispatches = dispatch_store or OperatorDispatchStore(
        str(job_state_root(job)), project_id=str(job["project_id"]), run_id=str(job["run_id"])
    )

    def execute(gate_id: str, gate_run_id: str, resume: bool) -> Mapping[str, Any]:
        del gate_run_id, resume
        dispatch = ensure_v2_dispatch(job, gate_id, dispatch_store=dispatches)
        if dispatch.get("state") != "OPERATOR_ACKNOWLEDGED":
            return {"status": "WAITING_RESOURCE", "reason": "OPERATOR_DISPATCH_ACK_PENDING"}
        receipt = receipts.load(gate_id)
        if receipt is None:
            return {"status": "WAITING_RESOURCE", "reason": "OPERATOR_TASK_RECEIPT_PENDING"}
        try:
            _validate_receipt_for_job(job, gate_id, receipt)
        except OperatorPlanExecutionError as exc:
            raise OperatorDispatchError(str(exc)) from exc
        return {
            "status": "GATE_EXIT",
            "receipt_sha256": str(receipt["receipt_sha256"]),
            "next": {"action": "SYSTEM_TRANSITION", "automatic": True},
        }

    return execute

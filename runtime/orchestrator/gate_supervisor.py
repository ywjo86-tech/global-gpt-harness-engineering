"""Persistent, generic parent supervisor for unattended Gate lifecycles."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .lv_execution_package import canonical_json_bytes


class GateSupervisorError(ValueError):
    pass


STAGES = ("PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION", "CHECKPOINT", "EXIT", "GATE_EXIT")
TERMINAL = frozenset({"USER_APPROVAL_REQUIRED", "COMPLETED", "HARD_STOP"})


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or ".." in value:
        raise GateSupervisorError(f"unsafe {label}")
    return value


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(payload)
    if path.exists() and path.is_symlink(): raise GateSupervisorError("supervisor checkpoint is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@dataclass
class SupervisorResult:
    status: str
    state: dict[str, Any]
    invocations: int
    mutation_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "state": self.state, "invocations": self.invocations,
                "mutation_performed": self.mutation_performed, "hard_stop": True}


class PersistentGateSupervisor:
    """Owns parent re-invocation and persists every transition before returning."""

    def __init__(self, harness_root: str | Path, *, project_id: str, run_id: str,
                 gate_id: str, mode: str, lv_order: Sequence[str], retry_budget: int = 2):
        self.root = Path(harness_root).resolve()
        if not self.root.is_dir() or self.root.is_symlink(): raise GateSupervisorError("unsafe harness root")
        self.project_id = _safe_id(project_id, "project ID"); self.run_id = _safe_id(run_id, "run ID")
        self.gate_id = _safe_id(gate_id, "Gate ID")
        if mode not in {"GATE_BY_GATE", "FULL_PLAN"}: raise GateSupervisorError("invalid supervisor mode")
        self.mode = mode
        self.lv_order = tuple(_safe_id(item, "LV ID") for item in lv_order)
        if not self.lv_order or len(set(self.lv_order)) != len(self.lv_order): raise GateSupervisorError("LV order is not canonical")
        if retry_budget < 0: raise GateSupervisorError("invalid retry budget")
        self.retry_budget = retry_budget
        base = self.root / "_workspace" / "global-gate-supervisor" / self.project_id
        self.state_path = base / f"{self.run_id}.state.json"; self.event_path = base / f"{self.run_id}.events.jsonl"; self.lock_path = base / f"{self.run_id}.lock"

    def _lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close(); raise GateSupervisorError("duplicate supervisor is active") from exc
        return handle

    def _initial(self) -> dict[str, Any]:
        state = {"schema_version":"orchestration.global-gate-supervisor.v1", "project_id":self.project_id,
                 "gate_id":self.gate_id, "run_id":self.run_id, "mode":self.mode, "lv_order":list(self.lv_order),
                 "current_lv":self.lv_order[0], "stage":"PACKAGE", "completed_lvs":[], "retry_budget":self.retry_budget,
                 "retries":{}, "retry_signatures":{}, "metrics":{"child_invocations":0,"model_invocations":0,"deterministic_transitions":0},
                 "terminal":False, "hard_stop":True}
        state["state_sha256"] = _sha(state); return state

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists(): return self._initial()
        if self.state_path.is_symlink(): raise GateSupervisorError("supervisor state is a symlink")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        digest = state.get("state_sha256")
        if digest != _sha({k:v for k,v in state.items() if k != "state_sha256"}): raise GateSupervisorError("supervisor state hash mismatch")
        if state.get("project_id") != self.project_id or state.get("gate_id") != self.gate_id or state.get("run_id") != self.run_id or state.get("mode") != self.mode or tuple(state.get("lv_order", [])) != self.lv_order:
            raise GateSupervisorError("supervisor state binding mismatch")
        if state.get("stage") not in STAGES and state.get("status") not in TERMINAL: raise GateSupervisorError("supervisor stage invalid")
        return state

    def _persist(self, state: dict[str, Any], event: Mapping[str, Any]) -> None:
        unsigned = {k:v for k,v in state.items() if k != "state_sha256"}; state["state_sha256"] = _sha(unsigned)
        _write_atomic(self.state_path, state)
        line = dict(event); line.update({"state_sha256":state["state_sha256"], "event_sha256":_sha(line)})
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_path.open("ab") as handle:
            handle.write(canonical_json_bytes(line) + b"\n"); handle.flush(); os.fsync(handle.fileno())

    def run(self, transition: Callable[[dict[str, Any]], Mapping[str, Any]], *, max_steps: int = 128) -> SupervisorResult:
        handle = self._lock(); invocations = 0; mutation = False
        try:
            state = self.load()
            if state.get("terminal") or state.get("status") in TERMINAL:
                return SupervisorResult(str(state.get("status", "COMPLETED")), state, 0, False)
            while invocations < max_steps:
                if state.get("stage") not in STAGES: raise GateSupervisorError("supervisor stage invalid")
                invocations += 1
                state.setdefault("metrics", {}).update({"child_invocations":int(state.get("metrics", {}).get("child_invocations", 0)) + 1,
                                                         "deterministic_transitions":int(state.get("metrics", {}).get("deterministic_transitions", 0)) + 1})
                outcome = dict(transition(dict(state)))
                status = str(outcome.get("status", "")); next_stage = outcome.get("next_stage", state["stage"])
                if next_stage not in STAGES and next_stage not in TERMINAL: raise GateSupervisorError("illegal supervisor transition")
                error = outcome.get("error_signature")
                if status in {"FAIL", "BLOCKED"}:
                    signature = str(error or status); progress = str(outcome.get("progress_digest", "")); retries = dict(state.get("retries", {})); count = int(retries.get(signature, 0))
                    signatures = dict(state.get("retry_signatures", {}))
                    if progress and signatures.get(signature) == progress:
                        state.update({"status":"HARD_STOP", "terminal":True, "hard_stop":True})
                        self._persist(state, {"event":"HARD_STOP", "reason":"NO_PROGRESS_RETRY", "error_signature":signature}); return SupervisorResult("HARD_STOP", state, invocations, True)
                    signatures[signature] = progress; state["retry_signatures"] = signatures
                    if count >= self.retry_budget:
                        state.update({"status":"HARD_STOP", "terminal":True, "hard_stop":True})
                        self._persist(state, {"event":"HARD_STOP", "reason":"RETRY_BUDGET_EXHAUSTED", "error_signature":signature}); mutation = True
                        return SupervisorResult("HARD_STOP", state, invocations, mutation)
                    retries[signature] = count + 1; state["retries"] = retries; state["stage"] = "REMEDIATION"; mutation = True
                    self._persist(state, {"event":"RETRY", "error_signature":signature, "retry":count + 1}); continue
                if status not in {"PASS", "COMPLETE", "READY", "CONSUMED", "EXITED", "SEALED"}:
                    raise GateSupervisorError("unknown supervisor transition status")
                state.update({k:v for k,v in outcome.items() if k not in {"status", "next_stage", "error_signature"}})
                if next_stage == "GATE_EXIT":
                    if self.mode == "GATE_BY_GATE":
                        state.update({"status":"USER_APPROVAL_REQUIRED", "terminal":True}); self._persist(state, {"event":"GATE_EXIT", "next":"USER_APPROVAL_REQUIRED"}); mutation = True
                        return SupervisorResult("USER_APPROVAL_REQUIRED", state, invocations, mutation)
                    if len(state.get("completed_lvs", [])) == len(self.lv_order):
                        state.update({"status":"COMPLETED", "terminal":True}); self._persist(state, {"event":"GATE_EXIT", "next":"COMPLETED"}); mutation = True
                        return SupervisorResult("COMPLETED", state, invocations, mutation)
                    state["stage"] = "PACKAGE"; state["current_lv"] = self.lv_order[len(state.get("completed_lvs", []))]
                elif next_stage == "EXIT":
                    current = state["current_lv"]
                    completed = list(state.get("completed_lvs", []))
                    if current not in completed: completed.append(current)
                    state["completed_lvs"] = completed; state["stage"] = "GATE_EXIT" if len(completed) == len(self.lv_order) else "PACKAGE"
                    if state["stage"] == "PACKAGE": state["current_lv"] = self.lv_order[len(completed)]
                else: state["stage"] = next_stage
                self._persist(state, {"event":"TRANSITION", "status":status, "stage":state["stage"], "lv_id":state["current_lv"]}); mutation = True
            state.update({"status":"GATE_EXECUTION_RESUME_REQUIRED", "terminal":False}); self._persist(state, {"event":"PAUSE", "reason":"STEP_BUDGET_EXHAUSTED"}); return SupervisorResult("GATE_EXECUTION_RESUME_REQUIRED", state, invocations, True)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN); handle.close()

    def run_lifecycle(self, handlers: Mapping[str, Callable[[dict[str, Any]], Mapping[str, Any]]], *, max_steps: int = 128) -> SupervisorResult:
        """Drive the canonical lifecycle without returning control between stages."""
        required = set(STAGES) - {"GATE_EXIT"}
        if not required.issubset(handlers):
            raise GateSupervisorError("lifecycle handlers are incomplete")
        def transition(state: dict[str, Any]) -> Mapping[str, Any]:
            stage = state["stage"]
            if stage == "GATE_EXIT": return {"status":"PASS", "next_stage":"GATE_EXIT"}
            outcome = dict(handlers[stage](dict(state)))
            status = str(outcome.get("status", ""))
            if status == "FAIL" and stage == "REVIEW":
                return {**outcome, "next_stage":"REMEDIATION"}
            if status == "PASS" and stage == "REMEDIATION":
                return {**outcome, "next_stage":"REVIEW"}
            if status in {"FAIL", "BLOCKED"}: return outcome
            order = {"PACKAGE":"PREFLIGHT", "PREFLIGHT":"WORKER", "WORKER":"REVIEW",
                     "REVIEW":"CHECKPOINT", "REMEDIATION":"REVIEW", "CHECKPOINT":"EXIT", "EXIT":"GATE_EXIT"}
            return {**outcome, "next_stage":outcome.get("next_stage", order[stage])}
        return self.run(transition, max_steps=max_steps)

    @staticmethod
    def select_worker_asset(manifests: Sequence[Mapping[str, Any]], *, capabilities: set[str],
                            permissions: set[str], owned_files: Sequence[str]) -> dict[str, Any]:
        """Select an existing registry asset using exact capability/scope matching."""
        from .project_isolation import AssetManifest, route_assets
        parsed = [AssetManifest.from_mapping(item) for item in manifests]
        result = route_assets(parsed, capabilities=set(capabilities), permissions=set(permissions), owned_files=list(owned_files))
        if len(result["selected"]) != 1:
            raise GateSupervisorError("worker registry selection is ambiguous or unavailable")
        return {**result, "registry_sha256": _sha(manifests), "hard_stop": True}

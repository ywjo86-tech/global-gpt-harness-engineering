"""Durable single-invocation runner from the first incomplete LV to Gate boundary."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from .canonical_paths import canonical_run_root


class ProductionGateRunnerError(ValueError):
    pass


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_bytes(value)); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class ProductionGateRunner:
    def __init__(self, harness_root: str | Path, *, project_id: str, gate_id: str, run_id: str,
                 mode: str, canonical_lvs: Sequence[str], inherited_completed_lvs: Sequence[str]):
        if mode != "GATE_BY_GATE":
            raise ProductionGateRunnerError("single-Gate runner requires GATE_BY_GATE authorization")
        self.lvs = tuple(canonical_lvs); inherited = tuple(inherited_completed_lvs)
        if not self.lvs or len(set(self.lvs)) != len(self.lvs):
            raise ProductionGateRunnerError("canonical LV order is invalid")
        if inherited != self.lvs[:len(inherited)]:
            raise ProductionGateRunnerError("completed LV inheritance is out of order")
        self.project_id=project_id; self.gate_id=gate_id; self.run_id=run_id; self.mode=mode
        self.initial_completed=inherited
        base=Path(harness_root).resolve()/"_workspace"/"production-gate-runner"/project_id
        self.state_path=base/f"{run_id}.state.json"; self.events_path=base/f"{run_id}.events.jsonl"
        active_lv = self.lvs[len(inherited)] if len(inherited) < len(self.lvs) else self.lvs[-1]
        self.run_root=canonical_run_root(harness_root, run_id=run_id, lv_id=active_lv)
        self.startup_path=self.run_root/"RUN_STARTED.json"
        self.startup_failure_path=self.run_root/"STARTUP_FAILURE.json"

    def _initial(self) -> dict[str, Any]:
        value={"schema_version":"orchestration.production-gate-runner.v1","project_id":self.project_id,
               "gate_id":self.gate_id,"run_id":self.run_id,"mode":self.mode,"canonical_lvs":list(self.lvs),
               "completed_lvs":list(self.initial_completed),"stage":"LV_LOOP","terminal":False,
               "external_supervisor_invocations":1,"user_resume_requests":0,"user_lv_approval_requests":0,
               "worker_invocations":{},"hard_stop":True}
        value["state_sha256"]=_sha(value); return value

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists(): return self._initial()
        if self.state_path.is_symlink(): raise ProductionGateRunnerError("runner state is unsafe")
        value=json.loads(self.state_path.read_text(encoding="utf-8")); digest=value.pop("state_sha256",None)
        if digest != _sha(value): raise ProductionGateRunnerError("runner state hash mismatch")
        value["state_sha256"]=digest
        if tuple(value.get("canonical_lvs",())) != self.lvs or value.get("run_id") != self.run_id:
            raise ProductionGateRunnerError("runner state binding mismatch")
        completed=tuple(value.get("completed_lvs",()))
        if completed != self.lvs[:len(completed)]: raise ProductionGateRunnerError("runner LV order mismatch")
        return value

    def _persist(self, state: dict[str, Any], event: Mapping[str, Any]) -> None:
        unsigned={k:v for k,v in state.items() if k!="state_sha256"}; state["state_sha256"]=_sha(unsigned)
        _atomic(self.state_path,state)
        row=dict(event); row["state_sha256"]=state["state_sha256"]; row["event_sha256"]=_sha(row)
        self.events_path.parent.mkdir(parents=True,exist_ok=True)
        with self.events_path.open("ab") as handle: handle.write(_bytes(row)+b"\n"); handle.flush(); os.fsync(handle.fileno())

    def record_bootstrap(self, lv_id: str, **markers: str) -> None:
        """Persist bounded package instrumentation outside package diagnostics."""
        if lv_id not in self.lvs:
            raise ProductionGateRunnerError("bootstrap LV binding mismatch")
        allowed = {"issue065_package_branch_entered", "issue065_writer_constructed",
                   "issue065_write_attempted", "issue065_write_succeeded",
                   "issue065_writer_binding", "issue065_throw_order"}
        if set(markers) - allowed or any(not isinstance(value, str) for value in markers.values()):
            raise ProductionGateRunnerError("bootstrap marker schema is invalid")
        state = self.load()
        state.setdefault("issue065_bootstrap", {}).setdefault(lv_id, {}).update(markers)
        self._persist(state, {"event": "ISSUE065_BOOTSTRAP", "lv_id": lv_id,
                              "markers": dict(markers)})

    def ensure_started(self) -> None:
        """Create the runner root and durable startup event before validation."""
        self.run_root.mkdir(parents=True, exist_ok=True)
        if not self.startup_path.exists():
            _atomic(self.startup_path, {
                "schema_version": "orchestration.run-start.v1",
                "run_id": self.run_id, "project_id": self.project_id,
                "gate_id": self.gate_id, "stage": "RUN_STARTED", "hard_stop": True,
            })
        state = self.load()
        if not self.state_path.exists():
            self._persist(state, {"event": "RUN_STARTED", "run_id": self.run_id})

    def record_startup_failure(self, *, stage: str, category: str,
                               authorization_failure_source: str = "UNKNOWN",
                               authorization_reason_presence: str = "UNKNOWN",
                               authorization_reason_mapping: str = "UNKNOWN",
                               governance_branch_id: str = "UNKNOWN",
                               governance_reason_origin: str = "UNKNOWN",
                               authorization_branch_id: str | None = None,
                               authorization_reason_origin: str | None = None,
                               authorization_helper_id: str = "UNKNOWN",
                               authorization_entry_id: str = "AUTHORIZE_PRODUCTION_DESCENDANT",
                               authorization_call_phase: str = "UNKNOWN",
                               authorization_exception_bucket: str = "UNKNOWN",
                               authorization_post_return_check_id: str = "UNKNOWN",
                               authorization_post_return_check_count: int = 0,
                               authorization_return_semantics: str = "UNKNOWN",
                               authorization_post_return_reason_presence: str = "UNKNOWN",
                               authorization_post_return_decision_source: str = "UNKNOWN",
                               package_transition_check_id: str = "UNKNOWN",
                               package_transition_check_count: int = 0,
                               package_transition_semantics: str = "UNKNOWN",
                               package_transition_phase: str = "UNKNOWN",
                               package_transition_reason_presence: str = "UNKNOWN",
                               package_dispatch_call_phase: str = "UNKNOWN",
                               decision_to_package_bridge_id: str = "UNKNOWN",
                               decision_to_package_bridge_phase: str = "UNKNOWN",
                               decision_to_package_bridge_semantics: str = "UNKNOWN",
                               decision_to_package_bridge_reason_presence: str = "UNKNOWN",
                               package_adapter_call_intent: str = "UNKNOWN",
                               decision_to_package_bridge_step_count: int = 0,
                               package_preentry_last_completed_step: str = "UNKNOWN",
                               package_preentry_failure_step: str = "NONE",
                               package_preentry_exception_bucket: str = "NONE",
                               auth_validation_last_entered_check: str = "NONE",
                               auth_validation_last_successful_check: str = "NONE",
                               auth_validation_failure_check: str = "NONE",
                               auth_validation_failure_mode: str = "NONE",
                               lifecycle_last_entered_stage: str = "NONE",
                               lifecycle_last_successful_stage: str = "NONE",
                               lifecycle_failure_stage: str = "NONE",
                               lifecycle_failure_mode: str = "NONE",
                               lifecycle_failure_check_id: str = "NONE",
                               lifecycle_failure_reason_presence: str = "UNKNOWN",
                               dispatch_preinvoke_last_completed_step: str = "NONE",
                               dispatch_preinvoke_failure_step: str = "NONE",
                               dispatch_preinvoke_exception_bucket: str = "NONE",
                               post_context_last_evaluated_edge: str = "NONE",
                               post_context_last_completed_edge: str = "NONE",
                               post_context_taken_branch: str = "UNKNOWN",
                               post_context_exit_kind: str = "UNKNOWN",
                               post_context_failure_edge: str = "NONE",
                               post_context_failure_mode: str = "NONE",
                               worker_verification_last_entered_step: str = "NONE",
                               worker_verification_last_successful_step: str = "NONE",
                               worker_verification_failure_step: str = "NONE",
                               worker_verification_failure_category: str = "NONE",
                               worker_verification_exception_bucket: str = "NONE",
                               evidence_origin: str = "INTERNAL") -> None:
        """Persist bounded pre-PACKAGE failure evidence after startup."""
        stages = {"APPROVAL", "AUTHORIZATION", "REQUEST_BINDING", "RESUME_VALIDATION",
                  "HOST_GATEWAY", "LIFECYCLE_BOOTSTRAP", "PACKAGE_DISPATCH", "UNKNOWN"}
        categories = {"STALE_APPROVAL", "APPROVAL_INVALID", "APPROVAL_SCOPE_MISMATCH",
                      "APPROVAL_LINEAGE_MISMATCH", "APPROVAL_RECORD_MISSING",
                      "GOVERNANCE_MISMATCH", "BASELINE_MISMATCH", "RESUME_AUTHORIZATION_BLOCK",
                      "AUTHORIZATION_BLOCK", "REQUEST_BINDING_BLOCK", "RESUME_STATE_BLOCK",
                      "HOST_GATEWAY_BLOCK", "CALLBACK_FAILURE", "OTHER", "UNKNOWN"}
        if stage not in stages or category not in categories:
            raise ProductionGateRunnerError("startup failure evidence schema is invalid")
        sources = {"APPROVAL", "RESUME", "DESCENDANT", "GOVERNANCE", "BASELINE", "CONTROLLER", "OTHER", "UNKNOWN"}
        presence = {"PRESENT", "ABSENT", "UNKNOWN"}; mapping = {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"}
        if authorization_failure_source not in sources or authorization_reason_presence not in presence or authorization_reason_mapping not in mapping:
            raise ProductionGateRunnerError("authorization failure evidence schema is invalid")
        branch_ids = {"GOVERNANCE_PRECONDITION_CONTEXT", "GOVERNANCE_PRECONDITION_DESCENDANT",
                      "GOVERNANCE_BASELINE_VALIDATION", "GOVERNANCE_RECORD_VALIDATION",
                      "GOVERNANCE_TRANSITION_VALIDATION", "GOVERNANCE_AUTHORIZATION_VALIDATION", "OTHER", "UNKNOWN"}
        helper_ids = {"VERIFY_PRODUCTION_TRANSITION_DESCENDANT",
                      "VERIFY_SAME_RUN_GOVERNED_DESCENDANT",
                      "VERIFY_PRODUCTION_RECOVERY_DESCENDANT", "OTHER", "UNKNOWN"}
        entry_ids = {"AUTHORIZE_PRODUCTION_DESCENDANT", "UNKNOWN"}
        call_phases = {"NOT_STARTED", "ENTERED", "RETURNED", "RAISED", "UNKNOWN"}
        exception_buckets = {"GOVERNANCE_BRANCH_ERROR", "GATE_CONTROLLER_ERROR", "VALUE_ERROR",
                             "TYPE_ERROR", "KEY_ERROR", "OTHER", "NONE", "UNKNOWN"}
        post_return_checks = {"CANONICAL_GATE_STATE_VALIDATION", "RESUME_BRIDGE_VALIDATION",
                              "PRODUCTION_DECISION_BUILD", "UNKNOWN"}
        return_semantics = {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"}
        post_return_presence = {"PRESENT", "ABSENT", "UNKNOWN"}
        decision_sources = {"AUTHORIZER_RESULT", "CLI_VALIDATION", "RUNNER_VALIDATION", "CONTROLLER_VALIDATION",
                            "OTHER", "UNKNOWN"}
        package_checks = {"LV_EXECUTION_PACKAGE_ADAPTER", "UNKNOWN"}
        package_semantics = {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"}
        package_phases = {"DECISION_READY", "PRECONDITION", "DISPATCH_READY", "DISPATCH_ENTERED", "UNKNOWN"}
        package_presence = {"PRESENT", "ABSENT", "UNKNOWN"}
        package_call_phases = {"NOT_STARTED", "ENTERED", "RETURNED", "RAISED", "UNKNOWN"}
        bridge_ids = {"POST_DECISION_GATE_BRANCH", "POST_DECISION_RECOVERY_SCAN",
                      "POST_DECISION_AUTHORIZATION_CONTEXT", "POST_DECISION_CONTEXT_BUILD",
                      "POST_DECISION_TRANSITION_REHYDRATION", "POST_DECISION_ADAPTER_CONSTRUCTION",
                      "POST_DECISION_RUNNER_CONSTRUCTION", "PACKAGE_DISPATCH_PREP",
                      "PACKAGE_ADAPTER_CALL", "PACKAGE_LIFECYCLE_DISPATCH", "UNKNOWN"}
        bridge_phases = {"ENTERED", "VALIDATING", "READY", "BLOCKED", "RETURNED", "RAISED", "UNKNOWN"}
        bridge_semantics = {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"}
        bridge_presence = {"PRESENT", "ABSENT", "UNKNOWN"}
        adapter_intents = {"YES", "NO", "UNKNOWN"}
        evidence_origins = {"TOP_LEVEL_BLOCK_FINALIZER", "INTERNAL", "UNKNOWN"}
        preentry_steps = {"NONE", "ADAPTER_OBJECT_RESOLUTION", "ADAPTER_RESOLVED",
                          "LIFECYCLE_ENTRY", "AUTHORIZATION_VALIDATION", "TRANSITION_ACTIVATION",
                          "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}
        preentry_failures = {"NONE", "ADAPTER_OBJECT_RESOLUTION", "LIFECYCLE_ENTRY",
                             "AUTHORIZATION_VALIDATION", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING",
                             "DISPATCH_READY", "UNKNOWN"}
        preentry_exceptions = {"ATTRIBUTE", "TYPE", "KEY", "VALUE", "STATE", "VALIDATION",
                               "OTHER", "NONE", "UNKNOWN"}
        auth_checks = {"NONE", "REQUIRED_CONTEXT_FIELDS", "APPROVAL_AUTHORIZATION",
                       "DESCENDANT_AUTHORIZATION", "DESCENDANT_SCOPE_GUARD",
                       "CANONICAL_GATE_STATE_VALIDATION", "UNKNOWN"}
        auth_modes = {"BLOCK", "RAISED", "INVALID", "MISSING", "NONE", "UNKNOWN"}
        lifecycle_stages = {"NONE", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}
        lifecycle_modes = {"BLOCK", "RAISED", "INVALID", "MISSING", "NONE", "UNKNOWN"}
        lifecycle_presence = {"PRESENT", "ABSENT", "UNKNOWN"}
        dispatch_steps = {"NONE", "CALLABLE_RESOLUTION", "CONTEXT_EXTRACTION", "LIFECYCLE_SEAL",
                          "ARTIFACT_PUBLISH", "INVOCATION", "UNKNOWN"}
        dispatch_exceptions = {"ATTRIBUTE", "KEY", "TYPE", "VALUE", "STATE", "CALLABLE", "VALIDATION", "OTHER", "NONE", "UNKNOWN"}
        context_edges = {"NONE", "LIFECYCLE_BINDING_CONDITION", "LIFECYCLE_SEAL_PRODUCE_CONSUME",
                         "ARTIFACT_PUBLISH_CONDITION", "PACKAGE_INVOCATION_GATE", "UNKNOWN"}
        context_branches = {"TRUE", "FALSE", "CONTINUE", "RETURN", "UNKNOWN"}
        context_exits = {"TO_NEXT_EDGE", "TO_LIFECYCLE_SEAL", "TO_ARTIFACT_PUBLISH", "TO_INVOCATION",
                         "BLOCK_RETURN", "BYPASS", "UNKNOWN"}
        context_modes = {"BLOCK", "RAISED", "INVALID", "NONE", "UNKNOWN"}
        worker_steps = {"NONE", "FOCUSED_TEST_EXECUTION", "FULL_TEST_EXECUTION",
                        "COMPILE_EXECUTION", "DIFF_CHECK_EXECUTION", "UNKNOWN"}
        worker_categories = {"NONE", "INPUT_BINDING", "COMMAND_BUILD", "EXECUTION_CONTEXT",
                             "SPAWN", "TIMEOUT", "NONZERO_EXIT", "OUTPUT_FORMAT", "RESULT_SCHEMA",
                             "SECURITY", "EXPECTATION_MISMATCH", "ARTIFACT_BINDING", "OTHER", "UNKNOWN"}
        worker_buckets = {"NONE", "TYPE", "VALUE", "KEY", "ATTRIBUTE", "PROCESS", "TIMEOUT",
                          "VALIDATION", "OTHER", "UNKNOWN"}
        origins = {"PRECONDITION", "VALIDATOR", "TRANSITION", "CONTROLLER", "OTHER", "UNKNOWN"}
        if (governance_branch_id not in branch_ids
                or governance_reason_origin not in origins
                or authorization_helper_id not in helper_ids
                or authorization_entry_id not in entry_ids
                or authorization_call_phase not in call_phases
                or authorization_exception_bucket not in exception_buckets
                or authorization_post_return_check_id not in post_return_checks
                or (isinstance(authorization_post_return_check_count, bool)
                    or not isinstance(authorization_post_return_check_count, int)
                    or authorization_post_return_check_count < 0)
                or authorization_return_semantics not in return_semantics
                or authorization_post_return_reason_presence not in post_return_presence
                or authorization_post_return_decision_source not in decision_sources
                or package_transition_check_id not in package_checks
                or (isinstance(package_transition_check_count, bool)
                    or not isinstance(package_transition_check_count, int)
                    or package_transition_check_count < 0)
                or package_transition_semantics not in package_semantics
                or package_transition_phase not in package_phases
                or package_transition_reason_presence not in package_presence
                or package_dispatch_call_phase not in package_call_phases
                or decision_to_package_bridge_id not in bridge_ids
                or decision_to_package_bridge_phase not in bridge_phases
                or decision_to_package_bridge_semantics not in bridge_semantics
                or decision_to_package_bridge_reason_presence not in bridge_presence
                or package_adapter_call_intent not in adapter_intents
                or (isinstance(decision_to_package_bridge_step_count, bool)
                    or not isinstance(decision_to_package_bridge_step_count, int)
                    or decision_to_package_bridge_step_count < 0)
                or package_preentry_last_completed_step not in preentry_steps
                or package_preentry_failure_step not in preentry_failures
                or package_preentry_exception_bucket not in preentry_exceptions
                or auth_validation_last_entered_check not in auth_checks
                or auth_validation_last_successful_check not in auth_checks
                or auth_validation_failure_check not in auth_checks
                or auth_validation_failure_mode not in auth_modes
                or lifecycle_last_entered_stage not in lifecycle_stages
                or lifecycle_last_successful_stage not in lifecycle_stages
                or lifecycle_failure_stage not in lifecycle_stages
                or lifecycle_failure_mode not in lifecycle_modes
                or lifecycle_failure_check_id not in lifecycle_stages
                or lifecycle_failure_reason_presence not in lifecycle_presence
                or dispatch_preinvoke_last_completed_step not in dispatch_steps
                or dispatch_preinvoke_failure_step not in dispatch_steps
                or dispatch_preinvoke_exception_bucket not in dispatch_exceptions
                or post_context_last_evaluated_edge not in context_edges
                or post_context_last_completed_edge not in context_edges
                or post_context_taken_branch not in context_branches
                or post_context_exit_kind not in context_exits
                or post_context_failure_edge not in context_edges
                or post_context_failure_mode not in context_modes
                or worker_verification_last_entered_step not in worker_steps
                or worker_verification_last_successful_step not in worker_steps
                or worker_verification_failure_step not in worker_steps
                or worker_verification_failure_category not in worker_categories
                or worker_verification_exception_bucket not in worker_buckets
                or evidence_origin not in evidence_origins):
            raise ProductionGateRunnerError("governance branch evidence schema is invalid")
        authorization_branch_id = authorization_branch_id or governance_branch_id
        authorization_reason_origin = authorization_reason_origin or governance_reason_origin
        self.run_root.mkdir(parents=True, exist_ok=True)
        _atomic(self.startup_failure_path, {
            "schema_version": "orchestration.startup-failure.v1",
            "run_id": self.run_id, "project_id": self.project_id,
            "gate_id": self.gate_id, "stage": stage,
            "startup_failure_category": category, "startup_failure_status": "BLOCK",
            "authorization_failure_source": authorization_failure_source,
            "authorization_reason_presence": authorization_reason_presence,
            "authorization_reason_mapping": authorization_reason_mapping,
            "governance_branch_id": governance_branch_id,
            "governance_reason_origin": governance_reason_origin,
            "authorization_branch_id": authorization_branch_id,
            "authorization_reason_origin": authorization_reason_origin,
            "authorization_helper_id": authorization_helper_id,
            "authorization_entry_id": authorization_entry_id,
            "authorization_call_phase": authorization_call_phase,
            "authorization_exception_bucket": authorization_exception_bucket,
            "authorization_post_return_check_id": authorization_post_return_check_id,
            "authorization_post_return_check_count": authorization_post_return_check_count,
            "authorization_return_semantics": authorization_return_semantics,
            "authorization_post_return_reason_presence": authorization_post_return_reason_presence,
            "authorization_post_return_decision_source": authorization_post_return_decision_source,
            "package_transition_check_id": package_transition_check_id,
            "package_transition_check_count": package_transition_check_count,
            "package_transition_semantics": package_transition_semantics,
            "package_transition_phase": package_transition_phase,
            "package_transition_reason_presence": package_transition_reason_presence,
            "package_dispatch_call_phase": package_dispatch_call_phase,
            "decision_to_package_bridge_id": decision_to_package_bridge_id,
            "decision_to_package_bridge_phase": decision_to_package_bridge_phase,
            "decision_to_package_bridge_semantics": decision_to_package_bridge_semantics,
            "decision_to_package_bridge_reason_presence": decision_to_package_bridge_reason_presence,
            "package_adapter_call_intent": package_adapter_call_intent,
            "decision_to_package_bridge_step_count": decision_to_package_bridge_step_count,
            "package_preentry_last_completed_step": package_preentry_last_completed_step,
            "package_preentry_failure_step": package_preentry_failure_step,
            "package_preentry_exception_bucket": package_preentry_exception_bucket,
            "auth_validation_last_entered_check": auth_validation_last_entered_check,
            "auth_validation_last_successful_check": auth_validation_last_successful_check,
            "auth_validation_failure_check": auth_validation_failure_check,
            "auth_validation_failure_mode": auth_validation_failure_mode,
            "lifecycle_last_entered_stage": lifecycle_last_entered_stage,
            "lifecycle_last_successful_stage": lifecycle_last_successful_stage,
            "lifecycle_failure_stage": lifecycle_failure_stage,
            "lifecycle_failure_mode": lifecycle_failure_mode,
            "lifecycle_failure_check_id": lifecycle_failure_check_id,
            "lifecycle_failure_reason_presence": lifecycle_failure_reason_presence,
            "dispatch_preinvoke_last_completed_step": dispatch_preinvoke_last_completed_step,
            "dispatch_preinvoke_failure_step": dispatch_preinvoke_failure_step,
            "dispatch_preinvoke_exception_bucket": dispatch_preinvoke_exception_bucket,
            "post_context_last_evaluated_edge": post_context_last_evaluated_edge,
            "post_context_last_completed_edge": post_context_last_completed_edge,
            "post_context_taken_branch": post_context_taken_branch,
            "post_context_exit_kind": post_context_exit_kind,
            "post_context_failure_edge": post_context_failure_edge,
            "post_context_failure_mode": post_context_failure_mode,
            "worker_verification_last_entered_step": worker_verification_last_entered_step,
            "worker_verification_last_successful_step": worker_verification_last_successful_step,
            "worker_verification_failure_step": worker_verification_failure_step,
            "worker_verification_failure_category": worker_verification_failure_category,
            "worker_verification_exception_bucket": worker_verification_exception_bucket,
            "evidence_origin": evidence_origin,
            "hard_stop": True,
        })

    def record_startup_failure_core(self, *, stage: str, category: str,
                                    evidence_origin: str = "TOP_LEVEL_BLOCK_FINALIZER") -> None:
        """Persist only schema-safe core failure evidence before enrichment."""
        stages = {"APPROVAL", "AUTHORIZATION", "REQUEST_BINDING", "RESUME_VALIDATION",
                  "HOST_GATEWAY", "LIFECYCLE_BOOTSTRAP", "PACKAGE_DISPATCH", "UNKNOWN"}
        categories = {"STALE_APPROVAL", "APPROVAL_INVALID", "APPROVAL_SCOPE_MISMATCH",
                      "APPROVAL_LINEAGE_MISMATCH", "APPROVAL_RECORD_MISSING", "GOVERNANCE_MISMATCH",
                      "BASELINE_MISMATCH", "RESUME_AUTHORIZATION_BLOCK", "AUTHORIZATION_BLOCK",
                      "REQUEST_BINDING_BLOCK", "RESUME_STATE_BLOCK", "HOST_GATEWAY_BLOCK",
                      "CALLBACK_FAILURE", "OTHER", "UNKNOWN"}
        origins = {"TOP_LEVEL_BLOCK_FINALIZER", "INTERNAL", "UNKNOWN"}
        if stage not in stages or category not in categories or evidence_origin not in origins:
            raise ProductionGateRunnerError("startup failure core schema is invalid")
        self.run_root.mkdir(parents=True, exist_ok=True)
        _atomic(self.startup_failure_path, {
            "schema_version": "orchestration.startup-failure.v1",
            "run_id": self.run_id, "project_id": self.project_id,
            "gate_id": self.gate_id, "stage": stage,
            "startup_failure_category": category, "startup_failure_status": "BLOCK",
            "evidence_origin": evidence_origin, "hard_stop": True,
        })

    def run(self, execute_lv: Callable[[str], Mapping[str, Any]],
            finalize_gate: Callable[[Sequence[str]], Mapping[str, Any]]) -> dict[str, Any]:
        self.ensure_started()
        state=self.load()
        if state.get("terminal"):
            return {"status":state["status"],"state":state,"mutation_performed":False,"invoked_lvs":[]}
        invoked=[]; budget=(len(self.lvs)-len(state["completed_lvs"]))*2+2; transitions=0
        while len(state["completed_lvs"]) < len(self.lvs):
            if transitions+2 > budget: raise ProductionGateRunnerError("canonical transition budget exceeded")
            lv=self.lvs[len(state["completed_lvs"])]
            counts=dict(state.get("worker_invocations",{}))
            if int(counts.get(lv,0)) != 0: raise ProductionGateRunnerError("duplicate worker invocation blocked")
            before=state["state_sha256"]; outcome=dict(execute_lv(lv)); transitions+=1
            if outcome.get("status") != "SYSTEM_TRANSITION" or outcome.get("lv_id") != lv:
                raise ProductionGateRunnerError("LV lifecycle made no canonical progress")
            counts[lv]=1; state["worker_invocations"]=counts; state["last_lv_outcome"]=outcome
            self._persist(state,{"event":"LV_LIFECYCLE_COMPLETE","lv_id":lv})
            state["completed_lvs"].append(lv); state["stage"]="LV_EXIT"; transitions+=1
            self._persist(state,{"event":"LV_EXIT","lv_id":lv}); invoked.append(lv)
            if state["state_sha256"] == before: raise ProductionGateRunnerError("NO_PROGRESS")
            state["stage"]="LV_LOOP"
        terminal=dict(finalize_gate(tuple(state["completed_lvs"])))
        if terminal.get("next_gate_status") != "USER_APPROVAL_REQUIRED" or terminal.get("gate_status") != "EXITED":
            raise ProductionGateRunnerError("Gate terminal boundary is incomplete")
        state.update({"stage":"HANDOFF_SEALED","status":"USER_APPROVAL_REQUIRED","terminal":True,
                      "gate_terminal":terminal,"hard_stop":True})
        self._persist(state,{"event":"GATE_EXIT","next_gate_status":"USER_APPROVAL_REQUIRED"})
        return {"status":"USER_APPROVAL_REQUIRED","state":state,"mutation_performed":True,
                "invoked_lvs":invoked,"transition_budget":budget,"hard_stop":True}

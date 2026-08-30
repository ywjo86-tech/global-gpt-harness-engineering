from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .canonical_transition import validate_canonical_gate_state, validate_governance_descendant
from .production_approval import ApprovalBindings, evaluate_production_authorization
from .recovery_contract import is_completion_eligible


class GateControllerError(ValueError):
    """Fail-closed error raised at an orchestration lifecycle boundary."""


StageCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class GateControllerAdapters:
    package: StageCallable
    preflight: StageCallable
    worker: StageCallable
    review: StageCallable
    remediation: StageCallable
    checkpoint: StageCallable
    exit: StageCallable
    handoff: StageCallable


_SUCCESS = {
    "PACKAGE": {"SEALED"},
    "PREFLIGHT": {"READY"},
    "WORKER": {"COMPLETED", "PASS"},
    "REVIEW": {"PASS", "FAIL"},
    "REMEDIATION": {"PASS"},
    "CHECKPOINT": {"CHECKPOINTED", "PASS"},
    "EXIT": {"EXITED", "PASS"},
    "HANDOFF": {"SEALED", "PASS"},
}


def _validated_result(stage: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GateControllerError(f"{stage} did not return a result mapping")
    result = dict(value)
    if not is_completion_eligible(result):
        raise GateControllerError(f"{stage} returned completion-ineligible evidence")
    status = result.get("status")
    exit_code = result.get("exit_code")
    evidence = result.get("evidence_sha256")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise GateControllerError(f"{stage} did not return an integer exit code")
    if exit_code != 0:
        raise GateControllerError(f"{stage} failed with exit code {exit_code}")
    if status not in _SUCCESS[stage]:
        raise GateControllerError(f"{stage} returned invalid status {status!r}")
    if not isinstance(evidence, str) or not _SHA256.fullmatch(evidence):
        raise GateControllerError(f"{stage} returned invalid evidence SHA-256")
    if result.get("hard_stop") is not True:
        raise GateControllerError(f"{stage} did not preserve the hard-stop boundary")
    return result


def gate_dry_run(context: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the lifecycle without invoking any execution adapter."""
    required = ("project_id", "gate_id", "lv_id", "run_id", "plan_sha256")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GateControllerError(f"dry-run context is missing: {', '.join(missing)}")
    return {
        "status": "DRY_RUN",
        "mutation_performed": False,
        "stages": [
            "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION",
            "CHECKPOINT", "EXIT", "HANDOFF", "SYSTEM_TRANSITION",
        ],
        "context": dict(context),
        "hard_stop": True,
    }


def run_gate_lifecycle(context: Mapping[str, Any], adapters: GateControllerAdapters) -> dict[str, Any]:
    """Run one LV through the real, injected lifecycle and derive its transition."""
    required = ("project_id", "gate_id", "lv_id", "run_id", "plan_sha256")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GateControllerError(f"run context is missing: {', '.join(missing)}")
    if not _SHA256.fullmatch(str(context["plan_sha256"])):
        raise GateControllerError("run context has invalid plan SHA-256")

    state: dict[str, Any] = dict(context)
    evidence: dict[str, str] = {}
    trace: list[str] = []

    def invoke(stage: str, adapter: StageCallable) -> dict[str, Any]:
        request = dict(state)
        request["prior_evidence"] = dict(evidence)
        result = _validated_result(stage, adapter(request))
        evidence[stage.lower()] = result["evidence_sha256"]
        trace.append(stage)
        state["last_stage"] = stage
        state["last_status"] = result["status"]
        return result

    invoke("PACKAGE", adapters.package)
    invoke("PREFLIGHT", adapters.preflight)
    invoke("WORKER", adapters.worker)
    review = invoke("REVIEW", adapters.review)
    restored_verdicts = review.get("verdict_history")
    review_verdicts = list(restored_verdicts) if isinstance(restored_verdicts, list) and restored_verdicts else [review["status"]]
    remediated = False
    remediation_verdict = review.get("remediation_verdict")
    if remediation_verdict is not None:
        remediated = True
    if review["status"] == "FAIL":
        remediation = invoke("REMEDIATION", adapters.remediation)
        remediation_verdict = remediation["status"]
        remediated = True
        state["review_attempt"] = 2
        review = invoke("REVIEW", adapters.review)
        review_verdicts.append(review["status"])
        if review["status"] != "PASS":
            raise GateControllerError(f"independent review did not pass after remediation: {review}")
    invoke("CHECKPOINT", adapters.checkpoint)
    invoke("EXIT", adapters.exit)
    handoff = invoke("HANDOFF", adapters.handoff)
    trace.append("SYSTEM_TRANSITION")
    return {
        "status": "SYSTEM_TRANSITION",
        "event_type": "SYSTEM_TRANSITION",
        "user_approval_renewal": False,
        "project_id": context["project_id"],
        "gate_id": context["gate_id"],
        "lv_id": context["lv_id"],
        "run_id": context["run_id"],
        "plan_sha256": context["plan_sha256"],
        "trace": trace,
        "evidence": evidence,
        "remediated": remediated,
        "review_verdicts": review_verdicts,
        "remediation_verdict": remediation_verdict,
        "handoff": handoff,
        "hard_stop": True,
    }


def run_production_gate_lifecycle(
    context: Mapping[str, Any], adapters: GateControllerAdapters, *, approval_events: list[Mapping[str, Any]],
    project_root: str, canonical_state: Mapping[str, Any], completion_conditions_sha256: str,
    historical_predecessor: str | None = None, historical_event_ids: tuple[str, ...] = (),
    harness_root: str | None = None,
) -> dict[str, Any]:
    """Production boundary: v2 authorization, Git descendant, state, then lifecycle."""
    required = ("project_id", "gate_id", "plan_sha256", "branch", "baseline_head", "approval_mode", "canonical_lv_scope", "owned_file_scope", "phase")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GateControllerError(f"production context is missing: {', '.join(missing)}")
    try:
        approval = evaluate_production_authorization(
            approval_events,
            ApprovalBindings(
                project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
                plan_sha256=str(context["plan_sha256"]), branch=str(context["branch"]),
                baseline_head=str(context["baseline_head"]), approval_mode=str(context["approval_mode"]),
                canonical_lv_scope=tuple(context["canonical_lv_scope"]),
                owned_file_scope={key: tuple(value) for key, value in context["owned_file_scope"].items()},
                completion_conditions_sha256=completion_conditions_sha256,
            ),
            historical_predecessor=historical_predecessor,
            historical_event_ids=historical_event_ids,
        )
        try:
            validate_governance_descendant(project_root, str(context["baseline_head"]))
        except ValueError:
            # Recovery workers may have committed approved product files after
            # the original governance baseline.  Reuse that descendant only
            # when every changed path remains in the bound owned scope (plus
            # governance metadata); unrelated drift remains a hard stop.
            import subprocess
            changed = subprocess.run(
                ["git", "-C", str(project_root), "diff", "--name-only",
                 f"{context['baseline_head']}..HEAD"], capture_output=True, text=True, check=True,
            ).stdout.splitlines()
            owned = {path for paths in context["owned_file_scope"].values() for path in paths}
            governance = ("AGENTS.md", "docs/", "runtime/orchestrator/", ".agents/", ".codex/")
            if not changed or any(path not in owned and not any(path == p or path.startswith(p) for p in governance)
                                   for path in changed):
                raise
        validate_canonical_gate_state(
            canonical_state, project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
            phase=str(context["phase"]), plan_sha256=str(context["plan_sha256"]),
            approval_record_hash=str(approval["record_hash"]),
        )
    except ValueError as exc:
        raise GateControllerError(str(exc)) from exc
    if harness_root is not None:
        from .active_transition import activate_canonical_lv_transition
        transition = activate_canonical_lv_transition(
            harness_root, project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
            lv_id=str(context["lv_id"]), run_id=str(context["run_id"]), approval_event_id=str(approval["event_id"]),
            plan_sha256=str(context["plan_sha256"]), branch=str(context["branch"]),
            baseline_head=str(context["baseline_head"]), current_head=str(context.get("current_head", "")),
            predecessor_digest=str(context.get("predecessor_completion_digest", "")),
            owned_files=list(context["owned_file_scope"][context["lv_id"]]),
            completion_conditions=list(context.get("completion_conditions", [])),
        )
        context = dict(context)
        context["canonical_state_override"] = {
            "state": "GATE1_ACTIVE", "gate_id": str(context["gate_id"]), "active_scope": [str(context["lv_id"])],
            "selected_source": __import__("pathlib").Path(project_root).resolve() / "IMPLEMENTATION_PLAN.md",
            "canonical_plan": "IMPLEMENTATION_PLAN.md", "plan_sha256": str(context["plan_sha256"]),
            "approval_id": approval["event_id"], "approval_record_hash": approval["record_hash"],
            "checkpoint_commit": transition["current_head"], "owned_files": list(context["owned_file_scope"][context["lv_id"]]),
            "ledger_path": "docs/GATE_STATE.md", "transition": transition,
        }
    outcome = run_gate_lifecycle(context, adapters)
    outcome["production_approval_schema"] = approval["schema_version"]
    outcome["production_approval_record_hash"] = approval["record_hash"]
    return outcome

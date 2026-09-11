from __future__ import annotations

import argparse

def official_partial_adoption_entry(**kwargs):
    """Callable CLI boundary used by the registered production command adapter."""
    from .gate_controller import adopt_terminated_partial
    return adopt_terminated_partial(**kwargs)

def production_terminal_entry(**kwargs):
    from .production_terminal import run_terminal_entry
    return run_terminal_entry(**kwargs)
import json
import os
import re
import hashlib
from pathlib import Path

from .contract_loader import ContractLoadError
from .contract_adapter import ContractMappingError
from .engine import OrchestrationEngine
from .lv_execution_package import LVExecutionPackageError, create_lv_execution_package
from .lv_preview import LVPreviewValidationError, preview_lv_read_only
from .lv_remediation import LVRemediationError
from .gate_orchestrator import GateOrchestrationError
from .gate_approval import GateApprovalError
from .project_isolation import ProjectIsolationError
from .gate_controller import GateControllerError
from .resume_store import ResumeStoreError
from .lv_review import LVReviewError, preflight_run, review_run
from .read_only_inspector import ReadOnlyValidationError, inspect_read_only
from .production_approval import ProductionApprovalError
from .mapping_migration import MappingMigrationError
from .recovery_contract import RecoveryError


def _bind_post_handoff_context(
    context: dict[str, object], predecessor: dict[str, object],
    owned_files: list[str] | None = None,
) -> dict[str, object]:
    """Bind the next LV to the prior in-call outcome; persisted evidence remains authoritative."""
    value = dict(context)
    evidence = predecessor.get("evidence")
    value.pop("recovery", None)
    value["predecessor_completion_digest"] = str(
        evidence.get("exit") if isinstance(evidence, dict) else ""
    )
    value["predecessor_lv"] = predecessor.get("lv_id")
    value["predecessor_evidence"] = predecessor
    value["approval_freshness_stage"] = "POST_HANDOFF"
    if owned_files is not None:
        value["owned_files"] = list(owned_files)
    return value


def _print(obj: object) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Global GPT Harness orchestration runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["inspect", "plan", "run", "collect", "fanin", "approve", "gate", "status", "lv-plan", "lv-package", "lv-preflight", "lv-review", "lv-remediation-package", "lv-remediation-preflight", "lv-remediation-review", "gate-dry-run", "gate-validate", "gate-run", "gate-approve", "production-gate-dry-run", "production-gate-run", "production-adopt-partial", "production-terminal", "project-onboard", "production-approval-create", "production-approval-correct", "production-mapping-migrate"]:
        sub = subparsers.add_parser(name)
        if name in {"production-adopt-partial", "production-terminal"}:
            sub.add_argument("--request", required=True)
        elif name in {"lv-plan", "lv-package"}:
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--lv-id", required=True)
            if name == "lv-plan":
                sub.add_argument("--read-only", action="store_true")
            else:
                sub.add_argument("--run-id", required=True)
        elif name in {"lv-preflight", "lv-review"}:
            sub.add_argument("--run-id", required=True)
            if name == "lv-review":
                sub.add_argument(
                    "--attempt",
                    required=True,
                    help="canonical positive review attempt; writes only to attempt-<NN>",
                )
        elif name == "lv-remediation-package":
            sub.add_argument("--parent-run-id", required=True)
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--reason-code", required=True)
            sub.add_argument("--reason", required=True)
        elif name in {"lv-remediation-preflight", "lv-remediation-review"}:
            sub.add_argument("--run-id", required=True)
        elif name == "gate-dry-run":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--mode", default="GATE_BY_GATE")
            sub.add_argument("--mapping-root")
        elif name == "gate-run":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--harness-root", required=True)
            sub.add_argument("--mode", default="GATE_BY_GATE")
            sub.add_argument("--resume", action="store_true")
            sub.add_argument("--requirements-sha256", required=True)
            sub.add_argument("--approval-evidence", required=True)
            sub.add_argument("--branch", required=True)
            sub.add_argument("--head", required=True)
            sub.add_argument("--requirement-evidence", required=True)
            sub.add_argument("--mapping-root")
        elif name in {"production-gate-dry-run", "production-gate-run"}:
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--harness-root", required=True)
            sub.add_argument("--approval-log", required=True)
            sub.add_argument("--approval-event-id", required=True)
            sub.add_argument("--mode", default="GATE_BY_GATE")
            sub.add_argument("--run-id")
            sub.add_argument("--mapping-root")
        elif name == "gate-approve":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--approval-evidence", required=True)
            sub.add_argument("--mapping-root")
        elif name == "gate-validate":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--requirements-sha256", required=True)
            sub.add_argument("--approval-evidence", required=True)
            sub.add_argument("--branch", required=True)
            sub.add_argument("--head", required=True)
            sub.add_argument("--harness-root", required=True)
            sub.add_argument("--requirement-evidence", required=True)
            sub.add_argument("--mapping-root")
        elif name == "production-mapping-migrate":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--mapping-root", required=True)
            sub.add_argument("--old-plan-sha256", required=True)
            sub.add_argument("--new-plan-sha256", required=True)
            sub.add_argument("--dry-run", action="store_true")
        elif name in {"production-approval-create", "production-approval-correct"}:
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--output", required=True)
            sub.add_argument("--gate-id", required=True)
            sub.add_argument("--plan-sha256", required=True)
            sub.add_argument("--scope-file", required=True)
            sub.add_argument("--authorization-source", required=True)
            sub.add_argument("--approval-mode", default="GATE_BY_GATE")
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("--read-only", action="store_true")
            if name == "production-approval-correct":
                sub.add_argument("--supersedes", required=True)
        elif name == "project-onboard":
            sub.add_argument("--project-root", required=True)
            sub.add_argument("--alias", required=True)
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("--bootstrap", action="store_true")
            sub.add_argument("--mapping-root")
        else:
            sub.add_argument("--project", required=True)
        if name in {"plan", "run", "gate"}:
            sub.add_argument("--mode", default="mock")
        if name in {"plan", "collect", "fanin", "gate", "status", "run"}:
            sub.add_argument("--run-id")
        if name == "approve":
            sub.add_argument("--approval", required=True)
        if name == "inspect":
            sub.add_argument("--read-only", action="store_true", help="validate contracts and static state without creating or changing files")

    args = parser.parse_args(argv)
    if getattr(args, "mapping_root", None) is not None:
        # The child lifecycle commands inherit this process-local registry choice.
        os.environ["HARNESS_CONTRACT_MAPPING_ROOT"] = args.mapping_root
    startup_runner = None
    startup_stage = "UNKNOWN"
    package_reached = False
    authorization_entry_id = "AUTHORIZE_PRODUCTION_DESCENDANT"
    authorization_call_phase = "NOT_STARTED"
    authorization_exception_bucket = "NONE"
    authorization_post_return_check_id = "UNKNOWN"
    authorization_post_return_check_count = 0
    authorization_return_semantics = "UNKNOWN"
    authorization_post_return_reason_presence = "UNKNOWN"
    authorization_post_return_decision_source = "UNKNOWN"
    package_transition_check_id = "UNKNOWN"
    package_transition_check_count = 0
    package_transition_semantics = "UNKNOWN"
    package_transition_phase = "UNKNOWN"
    package_transition_reason_presence = "UNKNOWN"
    package_dispatch_call_phase = "NOT_STARTED"
    decision_to_package_bridge_id = "UNKNOWN"
    decision_to_package_bridge_phase = "UNKNOWN"
    decision_to_package_bridge_semantics = "UNKNOWN"
    decision_to_package_bridge_reason_presence = "UNKNOWN"
    package_adapter_call_intent = "UNKNOWN"
    decision_to_package_bridge_step_count = 0
    package_preentry_last_completed_step = "NONE"
    package_preentry_failure_step = "NONE"
    package_preentry_exception_bucket = "NONE"
    auth_validation_last_entered_check = "NONE"
    auth_validation_last_successful_check = "NONE"
    auth_validation_failure_check = "NONE"
    auth_validation_failure_mode = "NONE"
    lifecycle_last_entered_stage = "NONE"
    lifecycle_last_successful_stage = "NONE"
    lifecycle_failure_stage = "NONE"
    lifecycle_failure_mode = "NONE"
    lifecycle_failure_check_id = "NONE"
    lifecycle_failure_reason_presence = "UNKNOWN"
    dispatch_preinvoke_last_completed_step = "NONE"
    dispatch_preinvoke_failure_step = "NONE"
    dispatch_preinvoke_exception_bucket = "NONE"
    post_context_last_evaluated_edge = "NONE"
    post_context_last_completed_edge = "NONE"
    post_context_taken_branch = "UNKNOWN"
    post_context_exit_kind = "UNKNOWN"
    post_context_failure_edge = "NONE"
    post_context_failure_mode = "NONE"

    def _mark_package_preentry(step: str, *, failure: str | None = None,
                                exception_bucket: str | None = None,
                                completed: bool = True) -> None:
        nonlocal package_preentry_last_completed_step, package_preentry_failure_step
        nonlocal package_preentry_exception_bucket
        if completed:
            package_preentry_last_completed_step = step
        if failure is not None:
            package_preentry_failure_step = failure
        if exception_bucket is not None:
            package_preentry_exception_bucket = exception_bucket

    def _mark_auth_validation(check: str, *, completed: bool = False,
                              failure_mode: str = "NONE") -> None:
        nonlocal auth_validation_last_entered_check, auth_validation_last_successful_check
        nonlocal auth_validation_failure_check, auth_validation_failure_mode
        auth_validation_last_entered_check = check
        if completed:
            auth_validation_last_successful_check = check
        if failure_mode != "NONE":
            auth_validation_failure_check = check
            auth_validation_failure_mode = failure_mode

    def _mark_lifecycle(stage: str, *, completed: bool = False,
                        failure_mode: str = "NONE", check_id: str = "NONE",
                        reason_presence: str = "UNKNOWN") -> None:
        nonlocal lifecycle_last_entered_stage, lifecycle_last_successful_stage
        nonlocal lifecycle_failure_stage, lifecycle_failure_mode
        nonlocal lifecycle_failure_check_id, lifecycle_failure_reason_presence
        lifecycle_last_entered_stage = stage
        if completed:
            lifecycle_last_successful_stage = stage
        if failure_mode != "NONE":
            lifecycle_failure_stage = stage
            lifecycle_failure_mode = failure_mode
            lifecycle_failure_check_id = check_id
            lifecycle_failure_reason_presence = reason_presence

    def _mark_dispatch_preinvoke(step: str, *, completed: bool = False,
                                 failure: str = "NONE", exception_bucket: str = "NONE") -> None:
        nonlocal dispatch_preinvoke_last_completed_step, dispatch_preinvoke_failure_step
        nonlocal dispatch_preinvoke_exception_bucket
        if completed:
            dispatch_preinvoke_last_completed_step = step
        if failure != "NONE":
            dispatch_preinvoke_failure_step = failure
            dispatch_preinvoke_exception_bucket = exception_bucket

    def _mark_post_context(edge: str, *, completed: bool = False,
                           branch: str = "UNKNOWN", exit_kind: str = "UNKNOWN",
                           failure: str = "NONE", failure_mode: str = "NONE") -> None:
        nonlocal post_context_last_evaluated_edge, post_context_last_completed_edge
        nonlocal post_context_taken_branch, post_context_exit_kind
        nonlocal post_context_failure_edge, post_context_failure_mode
        post_context_last_evaluated_edge = edge
        post_context_taken_branch = branch
        post_context_exit_kind = exit_kind
        if completed:
            post_context_last_completed_edge = edge
        if failure != "NONE":
            post_context_failure_edge = failure
            post_context_failure_mode = failure_mode

    def _mark_decision_package_bridge(step_id: str, *, phase: str = "ENTERED",
                                      semantics: str = "UNKNOWN", reason_presence: str = "UNKNOWN",
                                      adapter_intent: str | None = None) -> None:
        nonlocal decision_to_package_bridge_id, decision_to_package_bridge_phase
        nonlocal decision_to_package_bridge_semantics, decision_to_package_bridge_reason_presence
        nonlocal package_adapter_call_intent, decision_to_package_bridge_step_count
        decision_to_package_bridge_id = step_id
        decision_to_package_bridge_phase = phase
        decision_to_package_bridge_semantics = semantics
        decision_to_package_bridge_reason_presence = reason_presence
        decision_to_package_bridge_step_count += 1
        if adapter_intent is not None:
            package_adapter_call_intent = adapter_intent

    def _authorization_exception_bucket(exc: BaseException) -> str:
        if isinstance(exc, GateControllerError):
            return "GATE_CONTROLLER_ERROR"
        if isinstance(exc, TypeError):
            return "TYPE_ERROR"
        if isinstance(exc, KeyError):
            return "KEY_ERROR"
        if isinstance(exc, ValueError):
            return "VALUE_ERROR"
        return "OTHER"

    def _authorization_failure_category(exc: BaseException) -> str:
        propagated = getattr(exc, "approval_reason_code", None)
        if propagated in {"STALE_APPROVAL", "APPROVAL_SCOPE_MISMATCH", "APPROVAL_LINEAGE_MISMATCH",
                          "BASELINE_MISMATCH", "GOVERNANCE_MISMATCH", "RESUME_AUTHORIZATION_BLOCK",
                          "UNKNOWN"}:
            return propagated
        if getattr(exc, "approval_freshness_stage", None) is not None:
            return "STALE_APPROVAL"
        if getattr(exc, "approval_descendant_authorization", None) == "REJECTED":
            return "RESUME_AUTHORIZATION_BLOCK"
        message = str(exc)
        if "scope" in message and "mismatch" in message:
            return "APPROVAL_SCOPE_MISMATCH"
        if "lineage" in message or "record_hash" in message:
            return "APPROVAL_LINEAGE_MISMATCH"
        if "context missing required field" in message or "required field" in message:
            return "GOVERNANCE_MISMATCH"
        if "baseline" in message or "descendant" in message:
            return "BASELINE_MISMATCH"
        if "canonical Gate state" in message or "closure" in message:
            return "GOVERNANCE_MISMATCH"
        if startup_stage == "AUTHORIZATION":
            return "AUTHORIZATION_BLOCK"
        return "UNKNOWN"
    def _record_startup_failure(category: str, exc: BaseException | None = None,
                                *, evidence_origin: str = "INTERNAL") -> bool:
        nonlocal decision_to_package_bridge_phase, decision_to_package_bridge_semantics
        if (category != "UNKNOWN" or startup_stage == "AUTHORIZATION") and package_adapter_call_intent == "NO":
            if decision_to_package_bridge_id != "UNKNOWN":
                decision_to_package_bridge_phase = "BLOCKED"
                decision_to_package_bridge_semantics = "BLOCK"
        if startup_runner is not None and getattr(startup_runner, "startup_path", None).exists():
            try:
                reason_code = getattr(exc, "approval_reason_code", None) if exc is not None else None
                freshness = getattr(exc, "approval_freshness_stage", None) if exc is not None else None
                branch_id = (getattr(exc, "authorization_branch_id", None) or
                             (getattr(exc, "governance_branch_id", None) if exc is not None else None))
                helper_id = getattr(exc, "authorization_helper_id", None) if exc is not None else None
                origin = (getattr(exc, "authorization_reason_origin", None) or
                          (getattr(exc, "governance_reason_origin", None) if exc is not None else None))
                source = ("DESCENDANT" if freshness is not None else
                           ("CONTROLLER" if reason_code is not None else
                            ("GOVERNANCE" if startup_stage == "AUTHORIZATION" else "APPROVAL")))
                presence = "PRESENT" if category != "UNKNOWN" else "ABSENT"
                mapping = "KNOWN" if category != "UNKNOWN" else "UNKNOWN"
                def bounded(value, allowed, fallback="UNKNOWN"):
                    return value if value in allowed else fallback
                def bounded_count(value):
                    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
                safe_stage = bounded(startup_stage, {"APPROVAL", "AUTHORIZATION", "REQUEST_BINDING",
                    "RESUME_VALIDATION", "HOST_GATEWAY", "LIFECYCLE_BOOTSTRAP", "PACKAGE_DISPATCH", "UNKNOWN"})
                safe_category = bounded(category, {"STALE_APPROVAL", "APPROVAL_INVALID", "APPROVAL_SCOPE_MISMATCH",
                    "APPROVAL_LINEAGE_MISMATCH", "APPROVAL_RECORD_MISSING", "GOVERNANCE_MISMATCH",
                    "BASELINE_MISMATCH", "RESUME_AUTHORIZATION_BLOCK", "AUTHORIZATION_BLOCK",
                    "REQUEST_BINDING_BLOCK", "RESUME_STATE_BLOCK", "HOST_GATEWAY_BLOCK", "CALLBACK_FAILURE",
                    "OTHER", "UNKNOWN"})
                safe_source = bounded(source, {"APPROVAL", "RESUME", "DESCENDANT", "GOVERNANCE",
                    "BASELINE", "CONTROLLER", "OTHER", "UNKNOWN"})
                safe_presence = bounded(presence, {"PRESENT", "ABSENT", "UNKNOWN"})
                safe_mapping = bounded(mapping, {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"})
                safe_branch = bounded(branch_id or "UNKNOWN", {"GOVERNANCE_PRECONDITION_CONTEXT",
                    "GOVERNANCE_PRECONDITION_DESCENDANT", "GOVERNANCE_BASELINE_VALIDATION",
                    "GOVERNANCE_RECORD_VALIDATION", "GOVERNANCE_TRANSITION_VALIDATION",
                    "GOVERNANCE_AUTHORIZATION_VALIDATION", "OTHER", "UNKNOWN"})
                safe_origin = bounded(origin or "UNKNOWN", {"PRECONDITION", "VALIDATOR", "TRANSITION",
                    "CONTROLLER", "OTHER", "UNKNOWN"})
                safe_helper = bounded(helper_id or "UNKNOWN", {"VERIFY_PRODUCTION_TRANSITION_DESCENDANT",
                    "VERIFY_SAME_RUN_GOVERNED_DESCENDANT", "VERIFY_PRODUCTION_RECOVERY_DESCENDANT",
                    "OTHER", "UNKNOWN"})
                safe_entry = bounded(authorization_entry_id, {"AUTHORIZE_PRODUCTION_DESCENDANT", "UNKNOWN"})
                safe_call_phase = bounded(authorization_call_phase, {"NOT_STARTED", "ENTERED", "RETURNED", "RAISED", "UNKNOWN"})
                safe_exception = bounded(authorization_exception_bucket, {"GOVERNANCE_BRANCH_ERROR",
                    "GATE_CONTROLLER_ERROR", "VALUE_ERROR", "TYPE_ERROR", "KEY_ERROR", "OTHER", "NONE", "UNKNOWN"})
                safe_post_check = bounded(authorization_post_return_check_id, {"CANONICAL_GATE_STATE_VALIDATION",
                    "RESUME_BRIDGE_VALIDATION", "PRODUCTION_DECISION_BUILD", "UNKNOWN"})
                safe_return = bounded(authorization_return_semantics, {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"})
                safe_post_presence = bounded(authorization_post_return_reason_presence, {"PRESENT", "ABSENT", "UNKNOWN"})
                safe_decision_source = bounded(authorization_post_return_decision_source, {"AUTHORIZER_RESULT",
                    "CLI_VALIDATION", "RUNNER_VALIDATION", "CONTROLLER_VALIDATION", "OTHER", "UNKNOWN"})
                safe_package_check = bounded(package_transition_check_id, {"LV_EXECUTION_PACKAGE_ADAPTER", "UNKNOWN"})
                safe_package_semantics = bounded(package_transition_semantics, {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"})
                safe_package_phase = bounded(package_transition_phase, {"DECISION_READY", "PRECONDITION",
                    "DISPATCH_READY", "DISPATCH_ENTERED", "UNKNOWN"})
                safe_package_presence = bounded(package_transition_reason_presence, {"PRESENT", "ABSENT", "UNKNOWN"})
                safe_dispatch = bounded(package_dispatch_call_phase, {"NOT_STARTED", "ENTERED", "RETURNED", "RAISED", "UNKNOWN"})
                safe_bridge = bounded(decision_to_package_bridge_id, {"POST_DECISION_GATE_BRANCH",
                    "POST_DECISION_RECOVERY_SCAN", "POST_DECISION_AUTHORIZATION_CONTEXT", "POST_DECISION_CONTEXT_BUILD",
                    "POST_DECISION_TRANSITION_REHYDRATION", "POST_DECISION_ADAPTER_CONSTRUCTION",
                    "POST_DECISION_RUNNER_CONSTRUCTION", "PACKAGE_DISPATCH_PREP", "PACKAGE_ADAPTER_CALL",
                    "PACKAGE_LIFECYCLE_DISPATCH", "UNKNOWN"})
                safe_bridge_phase = bounded(decision_to_package_bridge_phase, {"ENTERED", "VALIDATING", "READY",
                    "BLOCKED", "RETURNED", "RAISED", "UNKNOWN"})
                safe_bridge_semantics = bounded(decision_to_package_bridge_semantics, {"PASS", "BLOCK", "INVALID", "MISSING", "UNKNOWN"})
                safe_bridge_presence = bounded(decision_to_package_bridge_reason_presence, {"PRESENT", "ABSENT", "UNKNOWN"})
                safe_intent = bounded(package_adapter_call_intent, {"YES", "NO", "UNKNOWN"})
                startup_runner.record_startup_failure(stage=safe_stage, category=safe_category,
                    authorization_failure_source=safe_source, authorization_reason_presence=safe_presence,
                    authorization_reason_mapping=safe_mapping,
                    governance_branch_id=safe_branch, governance_reason_origin=safe_origin,
                    authorization_helper_id=safe_helper, authorization_entry_id=safe_entry,
                    authorization_call_phase=safe_call_phase, authorization_exception_bucket=safe_exception,
                    authorization_post_return_check_id=safe_post_check,
                    authorization_post_return_check_count=bounded_count(authorization_post_return_check_count),
                    authorization_return_semantics=safe_return,
                    authorization_post_return_reason_presence=safe_post_presence,
                    authorization_post_return_decision_source=safe_decision_source,
                    package_transition_check_id=safe_package_check,
                    package_transition_check_count=bounded_count(package_transition_check_count),
                    package_transition_semantics=safe_package_semantics,
                    package_transition_phase=safe_package_phase,
                    package_transition_reason_presence=safe_package_presence,
                    package_dispatch_call_phase=safe_dispatch,
                    decision_to_package_bridge_id=safe_bridge,
                    decision_to_package_bridge_phase=safe_bridge_phase,
                    decision_to_package_bridge_semantics=safe_bridge_semantics,
                    decision_to_package_bridge_reason_presence=safe_bridge_presence,
                    package_adapter_call_intent=safe_intent,
                    decision_to_package_bridge_step_count=bounded_count(decision_to_package_bridge_step_count),
                    package_preentry_last_completed_step=bounded(package_preentry_last_completed_step,
                        {"NONE", "ADAPTER_OBJECT_RESOLUTION", "ADAPTER_RESOLVED", "LIFECYCLE_ENTRY",
                         "AUTHORIZATION_VALIDATION", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING",
                         "DISPATCH_READY", "UNKNOWN"}),
                    package_preentry_failure_step=bounded(package_preentry_failure_step,
                        {"NONE", "ADAPTER_OBJECT_RESOLUTION", "LIFECYCLE_ENTRY", "AUTHORIZATION_VALIDATION",
                         "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}),
                    package_preentry_exception_bucket=bounded(package_preentry_exception_bucket,
                        {"ATTRIBUTE", "TYPE", "KEY", "VALUE", "STATE", "VALIDATION", "OTHER", "NONE", "UNKNOWN"}),
                    auth_validation_last_entered_check=bounded(auth_validation_last_entered_check,
                        {"NONE", "REQUIRED_CONTEXT_FIELDS", "APPROVAL_AUTHORIZATION", "DESCENDANT_AUTHORIZATION",
                         "DESCENDANT_SCOPE_GUARD", "CANONICAL_GATE_STATE_VALIDATION", "UNKNOWN"}),
                    auth_validation_last_successful_check=bounded(auth_validation_last_successful_check,
                        {"NONE", "REQUIRED_CONTEXT_FIELDS", "APPROVAL_AUTHORIZATION", "DESCENDANT_AUTHORIZATION",
                         "DESCENDANT_SCOPE_GUARD", "CANONICAL_GATE_STATE_VALIDATION", "UNKNOWN"}),
                    auth_validation_failure_check=bounded(auth_validation_failure_check,
                        {"NONE", "REQUIRED_CONTEXT_FIELDS", "APPROVAL_AUTHORIZATION", "DESCENDANT_AUTHORIZATION",
                         "DESCENDANT_SCOPE_GUARD", "CANONICAL_GATE_STATE_VALIDATION", "UNKNOWN"}),
                    auth_validation_failure_mode=bounded(auth_validation_failure_mode,
                        {"BLOCK", "RAISED", "INVALID", "MISSING", "NONE", "UNKNOWN"}),
                    lifecycle_last_entered_stage=bounded(lifecycle_last_entered_stage,
                        {"NONE", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}),
                    lifecycle_last_successful_stage=bounded(lifecycle_last_successful_stage,
                        {"NONE", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}),
                    lifecycle_failure_stage=bounded(lifecycle_failure_stage,
                        {"NONE", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}),
                    lifecycle_failure_mode=bounded(lifecycle_failure_mode,
                        {"BLOCK", "RAISED", "INVALID", "MISSING", "NONE", "UNKNOWN"}),
                    lifecycle_failure_check_id=bounded(lifecycle_failure_check_id,
                        {"NONE", "TRANSITION_ACTIVATION", "LIFECYCLE_BINDING", "DISPATCH_READY", "UNKNOWN"}),
                    lifecycle_failure_reason_presence=bounded(lifecycle_failure_reason_presence,
                        {"PRESENT", "ABSENT", "UNKNOWN"}),
                    dispatch_preinvoke_last_completed_step=bounded(dispatch_preinvoke_last_completed_step,
                        {"NONE", "CALLABLE_RESOLUTION", "CONTEXT_EXTRACTION", "LIFECYCLE_SEAL",
                         "ARTIFACT_PUBLISH", "INVOCATION", "UNKNOWN"}),
                    dispatch_preinvoke_failure_step=bounded(dispatch_preinvoke_failure_step,
                        {"NONE", "CALLABLE_RESOLUTION", "CONTEXT_EXTRACTION", "LIFECYCLE_SEAL",
                         "ARTIFACT_PUBLISH", "INVOCATION", "UNKNOWN"}),
                    dispatch_preinvoke_exception_bucket=bounded(dispatch_preinvoke_exception_bucket,
                        {"ATTRIBUTE", "KEY", "TYPE", "VALUE", "STATE", "CALLABLE", "VALIDATION", "OTHER", "NONE", "UNKNOWN"}),
                    post_context_last_evaluated_edge=bounded(post_context_last_evaluated_edge,
                        {"NONE", "LIFECYCLE_BINDING_CONDITION", "LIFECYCLE_SEAL_PRODUCE_CONSUME",
                         "ARTIFACT_PUBLISH_CONDITION", "PACKAGE_INVOCATION_GATE", "UNKNOWN"}),
                    post_context_last_completed_edge=bounded(post_context_last_completed_edge,
                        {"NONE", "LIFECYCLE_BINDING_CONDITION", "LIFECYCLE_SEAL_PRODUCE_CONSUME",
                         "ARTIFACT_PUBLISH_CONDITION", "PACKAGE_INVOCATION_GATE", "UNKNOWN"}),
                    post_context_taken_branch=bounded(post_context_taken_branch,
                        {"TRUE", "FALSE", "CONTINUE", "RETURN", "UNKNOWN"}),
                    post_context_exit_kind=bounded(post_context_exit_kind,
                        {"TO_NEXT_EDGE", "TO_LIFECYCLE_SEAL", "TO_ARTIFACT_PUBLISH", "TO_INVOCATION",
                         "BLOCK_RETURN", "BYPASS", "UNKNOWN"}),
                    post_context_failure_edge=bounded(post_context_failure_edge,
                        {"NONE", "LIFECYCLE_BINDING_CONDITION", "LIFECYCLE_SEAL_PRODUCE_CONSUME",
                         "ARTIFACT_PUBLISH_CONDITION", "PACKAGE_INVOCATION_GATE", "UNKNOWN"}),
                    post_context_failure_mode=bounded(post_context_failure_mode,
                        {"BLOCK", "RAISED", "INVALID", "NONE", "UNKNOWN"}),
                    worker_verification_last_entered_step=bounded(
                        getattr(exc, "worker_verification_last_entered_step", "NONE") if exc else "NONE",
                        {"NONE", "FOCUSED_TEST_EXECUTION", "FULL_TEST_EXECUTION", "COMPILE_EXECUTION",
                         "DIFF_CHECK_EXECUTION", "UNKNOWN"}),
                    worker_verification_last_successful_step=bounded(
                        getattr(exc, "worker_verification_last_successful_step", "NONE") if exc else "NONE",
                        {"NONE", "FOCUSED_TEST_EXECUTION", "FULL_TEST_EXECUTION", "COMPILE_EXECUTION",
                         "DIFF_CHECK_EXECUTION", "UNKNOWN"}),
                    worker_verification_failure_step=bounded(
                        getattr(exc, "worker_verification_failure_step", "NONE") if exc else "NONE",
                        {"NONE", "FOCUSED_TEST_EXECUTION", "FULL_TEST_EXECUTION", "COMPILE_EXECUTION",
                         "DIFF_CHECK_EXECUTION", "UNKNOWN"}),
                    worker_verification_failure_category=bounded(
                        getattr(exc, "worker_verification_failure_category", "NONE") if exc else "NONE",
                        {"NONE", "INPUT_BINDING", "COMMAND_BUILD", "EXECUTION_CONTEXT", "SPAWN", "TIMEOUT",
                         "NONZERO_EXIT", "OUTPUT_FORMAT", "RESULT_SCHEMA", "SECURITY", "EXPECTATION_MISMATCH",
                         "ARTIFACT_BINDING", "OTHER", "UNKNOWN"}),
                    worker_verification_exception_bucket=bounded(
                        getattr(exc, "worker_verification_exception_bucket", "NONE") if exc else "NONE",
                        {"NONE", "TYPE", "VALUE", "KEY", "ATTRIBUTE", "PROCESS", "TIMEOUT",
                         "VALIDATION", "OTHER", "UNKNOWN"}),
                    evidence_origin=evidence_origin)
                return bool(startup_runner.startup_failure_path.is_file())
            except Exception:
                # Preserve the original fail-closed CLI result; diagnostics
                # must never alter approval or binding semantics.
                return False
        return False

    def _finalize_prepackage_block(category: str = "UNKNOWN",
                                   exc: BaseException | None = None) -> bool:
        """Converge every top-level non-success exit on bounded evidence."""
        if startup_runner is None or not startup_runner.startup_path.exists() or package_reached:
            return False
        if startup_runner.startup_failure_path.is_file():
            return True
        # Persist the schema-safe core record first. Optional diagnostics are
        # an enrichment layer and must never prevent the core failure record
        # from surviving a pre-PACKAGE BLOCK.
        try:
            startup_runner.record_startup_failure_core(
                stage=startup_stage,
                category=category,
                evidence_origin="TOP_LEVEL_BLOCK_FINALIZER",
            )
        except Exception as core_error:
            # A core persistence failure is itself fail-closed; do not return
            # an ordinary BLOCK with no durable evidence.
            raise RuntimeError("startup failure core persistence failed") from core_error
        if not startup_runner.startup_failure_path.is_file():
            raise RuntimeError("startup failure core evidence missing")
        # Full bounded diagnostics are best-effort enrichment. Their schema
        # or serialization failure must not erase the already persisted core.
        _record_startup_failure(category, exc, evidence_origin="TOP_LEVEL_BLOCK_FINALIZER")
        return True
    try:
        if args.command in {"production-adopt-partial", "production-terminal"}:
            request_path=Path(args.request)
            if not request_path.is_file() or request_path.is_symlink(): raise ValueError("unsafe production request")
            request=json.loads(request_path.read_text(encoding="utf-8"))
            if args.command=="production-adopt-partial":
                status=request.pop("process_status",None)
                request["process_probe"]=(lambda pid: request.get("recorded_start")) if status=="live" else (lambda pid: None)
                outcome=official_partial_adoption_entry(**request)
            else: outcome=production_terminal_entry(**request)
            _print(outcome);return 0
        if args.command == "production-mapping-migrate":
            from .mapping_migration import migrate_plan_sha_mapping
            _print(migrate_plan_sha_mapping(
                mapping_root=args.mapping_root, project_root=args.project_root,
                old_plan_sha256=args.old_plan_sha256, new_plan_sha256=args.new_plan_sha256,
                dry_run=args.dry_run,
            ))
            return 0
        if args.command in {"production-approval-create", "production-approval-correct"}:
            from .production_approval import write_production_approval
            scope = json.loads(Path(args.scope_file).read_text(encoding="utf-8"))
            required_scope = {"canonical_lv_scope", "owned_file_scope", "completion_conditions_sha256"}
            if not isinstance(scope, dict) or set(scope) != required_scope:
                raise ProductionApprovalError("scope file schema mismatch")
            outcome = write_production_approval(
                project_root=args.project_root, output_path=args.output, gate_id=args.gate_id,
                plan_sha256=args.plan_sha256, approval_mode=args.approval_mode,
                canonical_lv_scope=scope["canonical_lv_scope"], owned_file_scope=scope["owned_file_scope"],
                completion_conditions_sha256=scope["completion_conditions_sha256"],
                authorization_source=args.authorization_source,
                correction_of=getattr(args, "supersedes", None), dry_run=args.dry_run, read_only=args.read_only,
            )
            _print(outcome)
            return 0
        if args.command == "lv-plan":
            if not args.read_only:
                raise LVPreviewValidationError("H4-1 only supports --read-only LV previews")
            _print(preview_lv_read_only(Path(args.project_root), args.gate_id, args.lv_id))
            return 0
        if args.command == "lv-package":
            package = create_lv_execution_package(Path(args.project_root), args.gate_id, args.lv_id, args.run_id)
            _print(package)
            return 0
        if args.command == "lv-preflight":
            _print(preflight_run(args.run_id))
            return 0
        if args.command == "lv-review":
            outcome = review_run(args.run_id, attempt=args.attempt)
            _print(outcome)
            if outcome.get("status") == "PASS":
                return 0
            if outcome.get("status") == "FAIL":
                return 9
            return 10
        if args.command == "lv-remediation-package":
            from .lv_remediation import create_remediation_package
            _print(create_remediation_package(args.parent_run_id, args.run_id, args.reason_code, args.reason))
            return 0
        if args.command == "lv-remediation-preflight":
            from .lv_remediation import create_remediation_preflight
            outcome = create_remediation_preflight(args.run_id)
            _print(outcome)
            return 0 if outcome.get("status") == "READY" else 10
        if args.command == "lv-remediation-review":
            from .lv_remediation import review_remediation
            outcome = review_remediation(args.run_id)
            _print(outcome)
            if outcome.get("status") == "PASS":
                return 0
            if outcome.get("status") == "FAIL":
                return 9
            return 10
        if args.command == "gate-dry-run":
            from .gate_orchestrator import compatibility_dry_run
            outcome = compatibility_dry_run(args.project_root, args.gate_id, mode=args.mode)
            _print(outcome)
            return 0 if outcome.get("status") == "COMPATIBLE" else 10
        if args.command in {"production-gate-dry-run", "production-gate-run"}:
            from .gate_orchestrator import load_gate_plan, create_gate_authorization, _production_adapters
            from .production_approval import load_v2_event_log, ApprovalBindings, evaluate_production_authorization
            from .production_resume import build_resume_bridge, validate_resume_bridge
            from .canonical_transition import validate_governance_descendant, CanonicalTransitionError
            from .gate_controller import authorize_production_descendant
            if args.command == "production-gate-run" and not args.run_id:
                raise GateControllerError("--run-id is required for production-gate-run")
            plan = load_gate_plan(args.project_root, args.gate_id)
            # Resolve the persisted resume position before constructing the
            # runner.  hprep/hctl bind RUN_ROOT to RUN_ID + current LV; using
            # an empty inherited list here would incorrectly select the first
            # LV on a resumed run and write startup evidence into another root.
            # This bridge is read-only and does not authorize the run.
            bridge = build_resume_bridge(args.project_root, args.harness_root, args.gate_id,
                                         plan_sha256=plan.canonical_plan_sha256,
                                         run_id_hint=args.run_id)
            if args.command == "production-gate-run":
                # Establish the durable runner root before approval/request
                # validation can fail, using the exact persisted LV position.
                from .production_gate_runner import ProductionGateRunner
                startup_runner = ProductionGateRunner(
                    args.harness_root, project_id=plan.project_id, gate_id=args.gate_id,
                    run_id=args.run_id, mode=args.mode,
                    canonical_lvs=[item.lv_id for item in plan.lvs],
                    inherited_completed_lvs=[item["lv_id"] for item in bridge["completed"]],
                )
                startup_runner.ensure_started()
                startup_stage = "APPROVAL"
            startup_stage = "APPROVAL"
            events = load_v2_event_log(args.approval_log)
            selected = [event for event in events if event.get("event_id") == args.approval_event_id]
            if len(selected) != 1:
                missing = GateControllerError("approval event ID is missing or ambiguous")
                missing.approval_reason_code = "APPROVAL_RECORD_MISSING"
                raise missing
            event = selected[0]
            bindings = ApprovalBindings(
                project_id=plan.project_id, gate_id=args.gate_id, plan_sha256=plan.canonical_plan_sha256,
                branch=event["branch"], baseline_head=event["baseline_head"], approval_mode=args.mode,
                canonical_lv_scope=tuple(event["canonical_lv_scope"]),
                owned_file_scope={k: tuple(v) for k, v in event["owned_file_scope"].items()},
                completion_conditions_sha256=event["completion_conditions_sha256"],
            )
            # The markdown log loader returns the v2 suffix while preserving
            # its historical predecessor on the first event. Validate the
            # selected event as a one-event production chain; legacy records
            # remain audit-only and are never converted to v2 authorization.
            approval = evaluate_production_authorization(
                [event], bindings,
                historical_predecessor=event.get("predecessor"),
                historical_event_ids=((event["supersedes"],) if event.get("supersedes") else ()),
            )
            verified_recovery_descendant = False
            startup_stage = "AUTHORIZATION"
            try:
                descendant = validate_governance_descendant(args.project_root, approval["baseline_head"])
            except CanonicalTransitionError:
                # A resumed run may already contain the registered worker's
                # product checkpoint.  Central authorization requires sealed
                # same-run lifecycle evidence; scope or ancestry alone never
                # authorizes a descendant.
                recovery_context = {
                    "project_id": plan.project_id, "gate_id": args.gate_id,
                    "lv_id": bridge["first_incomplete_lv"], "run_id": args.run_id,
                    "plan_sha256": plan.canonical_plan_sha256,
                    "requirements_sha256": "f734be6f2a81c89428f28605a1ffcd12234a511e69ded4c607041a2e0b367361",
                    "owned_file_scope": approval["owned_file_scope"],
                    "branch": approval["branch"], "baseline_head": approval["baseline_head"],
                    "approval_event_id": approval["event_id"], "approval_record_hash": approval["record_hash"],
                    "canonical_lv_scope": approval["canonical_lv_scope"],
                }
                completed_rows = list(bridge.get("completed", []))
                predecessor_row = completed_rows[-1] if completed_rows else None
                current_index = next((index for index, item in enumerate(plan.lvs)
                                      if item.lv_id == bridge.get("first_incomplete_lv")), -1)
                transition_context = dict(recovery_context)
                transition_context.update({
                    "approval_event_id": approval["event_id"],
                    "approval_record_hash": approval["record_hash"],
                    "predecessor_lv": plan.lvs[current_index - 1].lv_id if current_index > 0 else None,
                    "canonical_lv_scope": approval["canonical_lv_scope"],
                })
                authorization_call_phase = "ENTERED"
                try:
                    descendant = authorize_production_descendant(
                        transition_context, project_root=args.project_root, harness_root=args.harness_root,
                        predecessor=predecessor_row, approval_record_hash=approval["record_hash"],
                        freshness_stage="RESUME_AUTHORIZATION",
                    )
                except Exception as exc:
                    authorization_call_phase = "RAISED"
                    authorization_exception_bucket = _authorization_exception_bucket(exc)
                    raise
                authorization_call_phase = "RETURNED"
                authorization_return_semantics = "PASS"
                authorization_post_return_reason_presence = (
                    "PRESENT" if any(key in descendant for key in ("approval_reason_code", "reason_code"))
                    else "ABSENT"
                )
                authorization_post_return_decision_source = "AUTHORIZER_RESULT"
                verified_recovery_descendant = bool(
                    descendant.get("recovery_owned_descendant")
                    or descendant.get("same_run_governed_descendant")
                )
            authorization_post_return_check_id = "CANONICAL_GATE_STATE_VALIDATION"
            authorization_post_return_check_count += 1
            authorization_post_return_decision_source = "CLI_VALIDATION"
            state_text = (Path(args.project_root) / "docs" / "GATE_STATE.md").read_text(encoding="utf-8")
            blocks = re.findall(r"```json[ \t]*\r?\n(.*?)\r?\n```", state_text, flags=re.DOTALL)
            if not blocks:
                raise GateControllerError("canonical Gate state ledger is missing")
            canonical_state = json.loads(blocks[-1])
            from .canonical_transition import validate_canonical_gate_state
            validate_canonical_gate_state(canonical_state, project_id=plan.project_id, gate_id=args.gate_id,
                                          phase=str(canonical_state.get("phase")), plan_sha256=plan.canonical_plan_sha256,
                                          approval_record_hash=approval["record_hash"])
            authorization_post_return_check_id = "RESUME_BRIDGE_VALIDATION"
            authorization_post_return_check_count += 1
            authorization_post_return_decision_source = "CLI_VALIDATION"
            validate_resume_bridge(bridge, project_id=plan.project_id, gate_id=args.gate_id, plan_sha256=plan.canonical_plan_sha256)
            from .production_decision import build_production_decision
            authorization_post_return_check_id = "PRODUCTION_DECISION_BUILD"
            authorization_post_return_check_count += 1
            authorization_post_return_decision_source = "RUNNER_VALIDATION"
            decision = build_production_decision(
                project_root=args.project_root, harness_root=args.harness_root,
                project_id=plan.project_id, gate_id=args.gate_id, run_id=args.run_id,
                mode=args.mode, current_lv=bridge["first_incomplete_lv"],
                inherited_completed_lvs=[item["lv_id"] for item in bridge["completed"]],
                remaining_lvs=bridge["remaining"],
            )
            _mark_decision_package_bridge("POST_DECISION_GATE_BRANCH", phase="READY", semantics="PASS",
                                          reason_presence="ABSENT", adapter_intent="NO")
            output = {"status": "DRY_RUN", "mutation_performed": False,
                      "approval_event_id": approval["event_id"], "approval_schema": approval["schema_version"],
                      "approval_record_hash": approval["record_hash"], "mode": args.mode,
                      "project_id": plan.project_id, "gate_id": args.gate_id,
                      "plan_sha256": plan.canonical_plan_sha256, "branch": approval["branch"],
                      "baseline_head": approval["baseline_head"], "current_head": descendant["current_head"],
                      "governance_only": descendant["governance_only"], "scope": approval["canonical_lv_scope"],
                      "approval_freshness_stage": descendant.get("approval_freshness_stage", "UNKNOWN"),
                      "approval_descendant_authorization": descendant.get("approval_descendant_authorization", "NOT_APPLICABLE"),
                      "resume_bridge": bridge, "decision": decision,
                      "next_gate": "USER_APPROVAL_REQUIRED", "hard_stop": True}
            if args.command == "production-gate-run":
                _mark_decision_package_bridge("POST_DECISION_RECOVERY_SCAN", phase="VALIDATING")
                from .production_completion import write_completion_rejection
                completion_recovery = None
                recovery_root = Path(args.harness_root)/"_workspace"/"global-gate"/plan.project_id/"recovery"
                # A restart must resume an already-created active attempt before
                # deriving another rejection from its incomplete lifecycle.
                active_candidates = []
                for record_path in recovery_root.glob(f"{args.run_id}-recovery-*.json"):
                    if record_path.is_symlink():
                        continue
                    try:
                        record = json.loads(record_path.read_text(encoding="utf-8"))
                        if (record.get("project_id") != plan.project_id or record.get("gate_id") != args.gate_id
                                or record.get("lv_id") != bridge["first_incomplete_lv"]
                                or record.get("run_id") != args.run_id
                                or record.get("hard_stop") is not True):
                            continue
                        record_hash = record.get("record_hash")
                        if not isinstance(record_hash, str) or hashlib.sha256(json.dumps(
                                {key: value for key, value in record.items() if key != "record_hash"},
                                sort_keys=True, separators=(",", ":")).encode()).hexdigest() != record_hash:
                            continue
                        attempt = int(record.get("recovery_attempt", 0))
                        attempt_root = Path(args.harness_root)/"_workspace"/"orchestration-runs"/args.run_id/f"attempt-{attempt:02d}"
                        checkpoint_path = record_path.with_name(record_path.stem + ".checkpoint.json")
                        if (attempt_root/"package.json").is_file():
                            pkg = json.loads((attempt_root/"package.json").read_text(encoding="utf-8"))
                            if pkg.get("lv_id") != record.get("lv_id"):
                                candidate = attempt_root.parent / f"attempt-{attempt:02d}-{record.get('lv_id')}"
                                if (candidate/"package.json").is_file(): attempt_root = candidate
                        if attempt > 1 and checkpoint_path.is_file() and (attempt_root/"package.json").is_file():
                            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                            checkpoint_hash = checkpoint.get("checkpoint_sha256")
                            if (checkpoint.get("schema_version") != "orchestration.production-recovery-checkpoint.v1"
                                    or checkpoint.get("project_id") != plan.project_id
                                    or checkpoint.get("gate_id") != args.gate_id
                                    or checkpoint.get("lv_id") != bridge["first_incomplete_lv"]
                                    or checkpoint.get("run_id") != args.run_id
                                    or checkpoint.get("hard_stop") is not True
                                    or checkpoint.get("recovery_record_hash") != record_hash
                                    or not isinstance(checkpoint_hash, str)
                                    or hashlib.sha256(json.dumps(
                                        {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"},
                                        sort_keys=True, separators=(",", ":")).encode()).hexdigest() != checkpoint_hash):
                                continue
                            active_candidates.append((attempt, record_path, checkpoint_path))
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue
                if active_candidates:
                    attempt, record_path, checkpoint_path = sorted(active_candidates, key=lambda item: item[0])[-1]
                    completion_recovery = {"recovery":json.loads(record_path.read_text(encoding="utf-8")),
                                           "checkpoint":json.loads(checkpoint_path.read_text(encoding="utf-8")),
                                           "next_attempt":attempt, "hard_stop":True,
                                           "classification":{"status":"REJECTED_COMPLETION_UNPROVEN","completion_eligible":False}}
                for rejected in ([] if completion_recovery else bridge.get("rejections", [])):
                    if (not isinstance(rejected, dict) or rejected.get("run_id") != args.run_id
                            or rejected.get("project_id", plan.project_id) != plan.project_id
                            or rejected.get("gate_id", args.gate_id) != args.gate_id
                            or rejected.get("lv_id") != bridge["first_incomplete_lv"]):
                        continue
                    rejection = write_completion_rejection(args.harness_root, project_id=plan.project_id,
                        gate_id=args.gate_id, lv_id=rejected["lv_id"], run_id=rejected["run_id"],
                        attempt=int(rejected["attempt"]), reasons=list(rejected["reasons"]),
                        source_shas=dict(rejected["source_shas"]), next_attempt=int(bridge["next_attempt"]))
                    from .recovery_contract import prepare_completion_recovery
                    completion_recovery = prepare_completion_recovery(args.harness_root,
                        prior_record_path=recovery_root/f"{args.run_id}-recovery-{int(rejected['attempt']):02d}.json",
                        rejection_path=recovery_root/f"{args.run_id}-attempt-{int(rejected['attempt']):02d}-completion-rejection.json")
                _mark_decision_package_bridge("POST_DECISION_AUTHORIZATION_CONTEXT", phase="VALIDATING")
                auth = create_gate_authorization(plan, approval["event_id"], mode=args.mode)
                import subprocess
                _mark_decision_package_bridge("POST_DECISION_CONTEXT_BUILD", phase="VALIDATING")
                head = subprocess.run(["git", "-C", args.project_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
                context = {"project_id": plan.project_id, "gate_id": args.gate_id, "lv_id": bridge["first_incomplete_lv"],
                           "run_id": args.run_id, "plan_sha256": plan.canonical_plan_sha256,
                           "requirements_sha256": "f734be6f2a81c89428f28605a1ffcd12234a511e69ded4c607041a2e0b367361",
                           "branch": approval["branch"], "baseline_head": approval["baseline_head"],
                           "current_head": head, "head": head, "predecessor_completion_digest": bridge["bridge_sha256"],
                           "approval_mode": args.mode, "canonical_lv_scope": approval["canonical_lv_scope"],
                           "owned_file_scope": approval["owned_file_scope"], "phase": "PHASE-1",
                           "approval_event_id": approval["event_id"], "approval_record_hash": approval["record_hash"]}
                context["resume"] = verified_recovery_descendant
                completed_rows_for_context = list(bridge.get("completed", []))
                current_index_for_context = next((index for index, item in enumerate(plan.lvs)
                                                  if item.lv_id == bridge.get("first_incomplete_lv")), -1)
                if completed_rows_for_context and current_index_for_context > 0:
                    context["predecessor_evidence"] = completed_rows_for_context[-1]
                    context["predecessor_lv"] = plan.lvs[current_index_for_context - 1].lv_id
                selected_lv = next(item for item in plan.lvs if item.lv_id == bridge["first_incomplete_lv"])
                context["completion_conditions"] = list(selected_lv.completion_criteria)
                context["issue065_package_preentry"] = _mark_package_preentry
                context["issue065_auth_validation"] = _mark_auth_validation
                context["issue065_lifecycle"] = _mark_lifecycle
                context["issue065_dispatch_preinvoke"] = _mark_dispatch_preinvoke
                context["issue065_post_context"] = _mark_post_context
                recovery = completion_recovery
                if recovery is not None:
                    recovery_lv = recovery.get("recovery", {}).get("lv_id") or recovery.get("checkpoint", {}).get("lv_id")
                    if recovery_lv != selected_lv.lv_id:
                        recovery = None
                _mark_decision_package_bridge("POST_DECISION_TRANSITION_REHYDRATION", phase="VALIDATING")
                package_root = Path(args.harness_root) / "_workspace" / "orchestration-runs" / args.run_id
                legacy_manifest = package_root / "package.manifest.json"
                legacy_worker = package_root / "worker.result.json"
                transition = (Path(args.harness_root) / "_workspace" / "global-gate" / plan.project_id / "state" /
                              f"{args.gate_id}-{args.run_id}-active-transition.json")
                # A production restart must replay the already-sealed transition
                # rather than replace its predecessor binding with a newly
                # rendered resume-bridge digest.  The transition validator below
                # still compares every canonical field and its record hash.
                if transition.is_file() and not transition.is_symlink():
                    existing_transition = json.loads(transition.read_text(encoding="utf-8"))
                    sealed_predecessor = existing_transition.get("predecessor_completion_digest")
                    if isinstance(sealed_predecessor, str) and sealed_predecessor:
                        context["predecessor_completion_digest"] = sealed_predecessor
                    sealed_head = existing_transition.get("current_head")
                    if isinstance(sealed_head, str) and sealed_head:
                        context["current_head"] = sealed_head
                transition_lv = None
                if transition.is_file() and not transition.is_symlink():
                    try:
                        transition_lv = json.loads(transition.read_text(encoding="utf-8")).get("lv_id")
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        transition_lv = None
                if (recovery is None and legacy_manifest.is_file() and legacy_worker.is_file() and transition.is_file()
                        and transition_lv == selected_lv.lv_id):
                    from .recovery_contract import prepare_partial_recovery
                    recovery = prepare_partial_recovery(
                        args.harness_root, manifest_path=legacy_manifest, worker_path=legacy_worker,
                        transition_path=transition, approval_event_id=approval["event_id"],
                    )
                    context["recovery"] = recovery["checkpoint"]
                _mark_decision_package_bridge("POST_DECISION_ADAPTER_CONSTRUCTION", phase="VALIDATING")
                from .production_gate_runner import ProductionGateRunner
                from .production_terminal import run_terminal_entry
                from .lifecycle_binding import DIGEST_FIELDS, build_binding_from_sources
                controller = __import__("runtime.orchestrator.gate_controller", fromlist=["run_production_gate_lifecycle"])
                initial_lv = bridge["first_incomplete_lv"]
                prior_outcome = {}
                _mark_decision_package_bridge("POST_DECISION_RUNNER_CONSTRUCTION", phase="VALIDATING")
                runner=ProductionGateRunner(args.harness_root,project_id=plan.project_id,gate_id=args.gate_id,run_id=args.run_id,
                    mode=args.mode,canonical_lvs=[item.lv_id for item in plan.lvs],
                    inherited_completed_lvs=[item["lv_id"] for item in bridge["completed"]])
                def execute_one(lv_id):
                    nonlocal prior_outcome, package_transition_check_id, package_transition_check_count
                    nonlocal package_transition_semantics, package_transition_phase
                    nonlocal package_transition_reason_presence, package_dispatch_call_phase
                    _mark_decision_package_bridge("PACKAGE_DISPATCH_PREP", phase="READY",
                                                  semantics="PASS", adapter_intent="NO")
                    selected = next(item for item in plan.lvs if item.lv_id == lv_id)
                    current = subprocess.run(["git", "-C", args.project_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
                    lv_context = dict(context)
                    lv_context.update({"lv_id":lv_id,"current_head":current,"head":current,
                                       "completion_conditions":list(selected.completion_criteria),
                                       "owned_files":list(approval["owned_file_scope"].get(lv_id, [])),
                                       "completed_plan_items":[item["lv_id"] for item in bridge["completed"]] + list(prior_outcome.get("completed_in_call", [])),
                                       "remaining_plan_items":[item.lv_id for item in plan.lvs if item.order > selected.order]})
                    lv_context["issue065_bootstrap"] = lambda **markers: runner.record_bootstrap(lv_id, **markers)
                    def package_transition(**markers: object) -> None:
                        nonlocal package_transition_check_id, package_transition_check_count
                        nonlocal package_transition_semantics, package_transition_phase
                        nonlocal package_transition_reason_presence, package_dispatch_call_phase, package_reached
                        if markers.get("package_dispatch_call_phase") == "RETURNED":
                            package_reached = True
                        if "package_transition_check_id" in markers:
                            package_transition_check_id = str(markers["package_transition_check_id"])
                        if "package_transition_check_count" in markers:
                            package_transition_check_count = int(markers["package_transition_check_count"])
                        elif package_transition_check_id != "UNKNOWN":
                            package_transition_check_count = max(1, package_transition_check_count)
                        if "package_transition_semantics" in markers:
                            package_transition_semantics = str(markers["package_transition_semantics"])
                        if "package_transition_phase" in markers:
                            package_transition_phase = str(markers["package_transition_phase"])
                        if "package_transition_reason_presence" in markers:
                            package_transition_reason_presence = str(markers["package_transition_reason_presence"])
                        if "package_dispatch_call_phase" in markers:
                            package_dispatch_call_phase = str(markers["package_dispatch_call_phase"])
                    lv_context["issue065_package_transition"] = package_transition
                    if lv_id != initial_lv:
                        lv_context = _bind_post_handoff_context(
                            lv_context, prior_outcome,
                            list(approval["owned_file_scope"].get(lv_id, [])),
                        )
                    _mark_decision_package_bridge("PACKAGE_ADAPTER_CALL", phase="DISPATCH_ENTERED",
                                                  semantics="PASS", adapter_intent="YES")
                    _mark_package_preentry("ADAPTER_OBJECT_RESOLUTION")
                    adapters = _production_adapters(
                        Path(args.project_root), plan, auth, lv_id, args.run_id, args.harness_root,
                        recovery if lv_id == initial_lv else None,
                    )
                    _mark_package_preentry("ADAPTER_RESOLVED")
                    _mark_package_preentry("LIFECYCLE_ENTRY")
                    result = controller.run_production_gate_lifecycle(
                        lv_context, adapters,
                        approval_events=[approval], project_root=args.project_root, canonical_state=canonical_state,
                        completion_conditions_sha256=approval["completion_conditions_sha256"],
                        historical_predecessor=approval.get("predecessor"),
                        historical_event_ids=((approval["supersedes"],) if approval.get("supersedes") else ()),
                        harness_root=args.harness_root)
                    result["completed_in_call"] = list(prior_outcome.get("completed_in_call", [])) + [lv_id]
                    prior_outcome = result
                    return result
                terminal_sources={field:{"field":field,"project_id":plan.project_id,"gate_id":args.gate_id,
                                  "lv_id":plan.lvs[-1].lv_id,"run_id":args.run_id} for field in DIGEST_FIELDS}
                terminal_binding=build_binding_from_sources(terminal_sources,project_id=plan.project_id,gate_id=args.gate_id,
                    lv_id=plan.lvs[-1].lv_id,run_id=args.run_id,attempt=1,recovery_id="gate-terminal",
                    approval_event_id=approval["event_id"],branch=approval["branch"],baseline_head=approval["baseline_head"],
                    current_head=head,hard_stop=True)
                def finalize(completed):
                    return run_terminal_entry(root=Path(args.harness_root)/"_workspace"/"production-terminal"/args.run_id,
                        binding=terminal_binding,lvs=[item.lv_id for item in plan.lvs],reviewed_lvs=completed,
                        source_sha256=plan.canonical_plan_sha256,predecessor=bridge["bridge_sha256"],mode=args.mode)
                _mark_decision_package_bridge("PACKAGE_LIFECYCLE_DISPATCH", phase="READY",
                                              semantics="PASS", adapter_intent="NO")
                outcome=runner.run(execute_one,finalize)
                output.update(outcome)
            _print(output)
            return 0
        if args.command == "gate-run":
            from .gate_orchestrator import execute_gate, dispatch_requirement_artifact, validate_global_gate_bindings
            validate_global_gate_bindings(
                args.project_root, args.gate_id, requirements_sha256=args.requirements_sha256,
                approval_evidence=args.approval_evidence, branch=args.branch, head=args.head,
                harness_root=args.harness_root,
            )
            raw = json.loads(Path(args.requirement_evidence).read_text(encoding="utf-8"))
            expected = tuple(raw.get("requirements", {}).keys()) if raw.get("schema_version") == "orchestration.project-requirement-contract.v1" else tuple(f"R{i:02d}" for i in range(1, 26))
            first = next(iter(raw.get("requirements", {}).values()), {}) if isinstance(raw.get("requirements"), dict) else {}
            artifact = dispatch_requirement_artifact(args.requirement_evidence, project_id=str(first.get("project_id", Path(args.project_root).name)),
                gate_id=args.gate_id, lv_id=str(first.get("lv_id", "")), plan_sha256=str(first.get("plan_sha256", "")), expected_requirement_ids=expected)
            outcome = execute_gate(
                args.project_root, args.gate_id, args.run_id, harness_root=args.harness_root,
                mode=args.mode, resume=args.resume, requirements_sha256=args.requirements_sha256, approval_evidence=args.approval_evidence,
                branch=args.branch, head=args.head,
                requirement_evidence=artifact["requirements"],
            )
            _print(outcome)
            return 0 if outcome.get("status") in {"SYSTEM_TRANSITION", "GATE_EXIT"} else 10
        if args.command == "gate-approve":
            from .gate_orchestrator import activate_first_gate
            outcome = activate_first_gate(args.project_root, args.gate_id, args.approval_evidence, mapping_root=args.mapping_root)
            _print(outcome)
            return 0 if outcome.get("status") in {"ACTIVATED", "ALREADY_ACTIVE"} else 10
        if args.command == "gate-validate":
            from .gate_orchestrator import load_requirement_evidence, validate_global_gate_bindings
            load_requirement_evidence(args.requirement_evidence, requirements_sha256=args.requirements_sha256)
            outcome = validate_global_gate_bindings(
                args.project_root, args.gate_id, requirements_sha256=args.requirements_sha256,
                approval_evidence=args.approval_evidence, branch=args.branch, head=args.head,
                harness_root=args.harness_root,
            )
            _print(outcome)
            return 0
        if args.command == "project-onboard":
            if args.bootstrap:
                from .project_onboarding import OnboardingRegistry
                if not args.mapping_root:
                    raise GateOrchestrationError("--bootstrap requires an isolated --mapping-root")
                registry = OnboardingRegistry(Path(args.mapping_root) / "aliases")
                outcome = registry.bootstrap(args.project_root, args.alias, mapping_root=args.mapping_root)
            else:
                from .gate_orchestrator import onboarding_dry_run
                outcome = onboarding_dry_run(args.project_root, args.alias)
            _print(outcome)
            return 0 if outcome.get("status") in {"BOOTSTRAPPED", "COMPATIBLE", "REGISTRATION_READY"} or not outcome.get("fail_closed") else 10
        if args.command == "inspect" and args.read_only:
            _print(inspect_read_only(Path(args.project)))
            return 0
        engine = OrchestrationEngine(Path(args.project))
        if args.command == "inspect":
            _print(engine.inspect())
            return 0
        if args.command == "plan":
            _print(engine.plan(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "run":
            _print(engine.run(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "collect":
            _print(engine.collect(args.run_id))
            return 0
        if args.command == "fanin":
            _print(engine.fanin(args.run_id))
            return 0
        if args.command == "approve":
            _print(engine.approve(args.approval))
            return 0
        if args.command == "gate":
            _print(engine.gate(mode=args.mode, run_id=args.run_id))
            return 0
        if args.command == "status":
            _print(engine.status(args.run_id))
            return 0
    except ContractLoadError as exc:
        _print({"error": str(exc), "missing_files": exc.missing_files})
        return 2
    except PermissionError as exc:
        _print({"error": str(exc)})
        return 3
    except ContractMappingError as exc:
        _print({"error": str(exc), "error_type": "contract_mapping_error"})
        return 4
    except ReadOnlyValidationError as exc:
        _print({"error": str(exc), "error_type": "read_only_validation_error", "validation": exc.report})
        return 5
    except LVPreviewValidationError as exc:
        _print({"error": str(exc), "error_type": "lv_preview_validation_error"})
        return 6
    except LVExecutionPackageError as exc:
        _finalize_prepackage_block("CALLBACK_FAILURE", exc)
        _print({"error": str(exc), "error_type": "lv_execution_package_error"})
        return 7
    except LVReviewError as exc:
        _finalize_prepackage_block("CALLBACK_FAILURE", exc)
        _print({"error": str(exc), "error_type": "lv_review_error"})
        return 8
    except LVRemediationError as exc:
        _finalize_prepackage_block("CALLBACK_FAILURE", exc)
        _print({"error": str(exc), "error_type": "lv_remediation_error"})
        return 11
    except GateOrchestrationError as exc:
        _finalize_prepackage_block("OTHER", exc)
        _print({"error": str(exc), "error_type": "gate_orchestration_error"})
        return 12
    except GateApprovalError as exc:
        _finalize_prepackage_block("OTHER", exc)
        _print({"error": str(exc), "error_type": "gate_approval_error"})
        return 13
    except ProjectIsolationError as exc:
        _finalize_prepackage_block("OTHER", exc)
        _print({"error": str(exc), "error_type": "project_isolation_error"})
        return 14
    except ProductionApprovalError as exc:
        _finalize_prepackage_block("APPROVAL_RECORD_MISSING" if "no production approval" in str(exc)
                                   else "APPROVAL_INVALID", exc)
        _print({"error": str(exc), "error_type": "production_approval_error", "status": "BLOCKED"})
        return 16
    except RecoveryError as exc:
        _finalize_prepackage_block("RESUME_STATE_BLOCK", exc)
        _print({"error": str(exc), "error_type": "production_recovery_error", "status": "BLOCKED", "hard_stop": True})
        return 15
    except MappingMigrationError as exc:
        _finalize_prepackage_block("OTHER", exc)
        _print({"error": str(exc), "error_type": "mapping_migration_error", "status": "BLOCKED"})
        return 17
    except (GateControllerError, ResumeStoreError) as exc:
        freshness = getattr(exc, "approval_freshness_stage", None)
        if freshness is not None:
            category = "STALE_APPROVAL"
        elif startup_stage == "APPROVAL":
            category = getattr(exc, "approval_reason_code", "APPROVAL_INVALID")
        elif startup_stage == "AUTHORIZATION":
            category = _authorization_failure_category(exc)
        else:
            category = "RESUME_STATE_BLOCK"
        _finalize_prepackage_block(category, exc)
        error = {"error": str(exc), "error_type": "gate_controller_error", "status": "BLOCKED", "hard_stop": True}
        freshness_stage = getattr(exc, "approval_freshness_stage", None)
        descendant_authorization = getattr(exc, "approval_descendant_authorization", None)
        if freshness_stage is not None:
            error["approval_freshness_stage"] = freshness_stage
        if descendant_authorization is not None:
            error["approval_descendant_authorization"] = descendant_authorization
        _print(error)
        return 15

    except Exception:
        # Final fail-safe for an unclassified production-gate startup failure.
        # Never expose the raw exception; if RUN_STARTED exists, preserve a
        # bounded durable BLOCK record before returning a non-success status.
        _finalize_prepackage_block("UNKNOWN")
        if startup_runner is not None:
            _print({"error_type": "startup_failure", "status": "BLOCKED", "hard_stop": True})
            return 15
        raise

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

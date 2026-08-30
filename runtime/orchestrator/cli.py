from __future__ import annotations

import argparse
import json
import os
import re
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


def _print(obj: object) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Global GPT Harness orchestration runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["inspect", "plan", "run", "collect", "fanin", "approve", "gate", "status", "lv-plan", "lv-package", "lv-preflight", "lv-review", "lv-remediation-package", "lv-remediation-preflight", "lv-remediation-review", "gate-dry-run", "gate-validate", "gate-run", "gate-approve", "production-gate-dry-run", "production-gate-run", "project-onboard", "production-approval-create", "production-approval-correct", "production-mapping-migrate"]:
        sub = subparsers.add_parser(name)
        if name in {"lv-plan", "lv-package"}:
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
    try:
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
            from .canonical_transition import validate_governance_descendant
            plan = load_gate_plan(args.project_root, args.gate_id)
            events = load_v2_event_log(args.approval_log)
            selected = [event for event in events if event.get("event_id") == args.approval_event_id]
            if len(selected) != 1:
                raise GateControllerError("approval event ID is missing or ambiguous")
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
            descendant = validate_governance_descendant(args.project_root, approval["baseline_head"])
            state_text = (Path(args.project_root) / "docs" / "GATE_STATE.md").read_text(encoding="utf-8")
            blocks = re.findall(r"```json[ \t]*\r?\n(.*?)\r?\n```", state_text, flags=re.DOTALL)
            if not blocks:
                raise GateControllerError("canonical Gate state ledger is missing")
            canonical_state = json.loads(blocks[-1])
            from .canonical_transition import validate_canonical_gate_state
            validate_canonical_gate_state(canonical_state, project_id=plan.project_id, gate_id=args.gate_id,
                                          phase=str(canonical_state.get("phase")), plan_sha256=plan.canonical_plan_sha256,
                                          approval_record_hash=approval["record_hash"])
            bridge = build_resume_bridge(args.project_root, args.harness_root, args.gate_id,
                                         plan_sha256=plan.canonical_plan_sha256)
            validate_resume_bridge(bridge, project_id=plan.project_id, gate_id=args.gate_id, plan_sha256=plan.canonical_plan_sha256)
            output = {"status": "DRY_RUN", "mutation_performed": False,
                      "approval_event_id": approval["event_id"], "approval_schema": approval["schema_version"],
                      "approval_record_hash": approval["record_hash"], "mode": args.mode,
                      "project_id": plan.project_id, "gate_id": args.gate_id,
                      "plan_sha256": plan.canonical_plan_sha256, "branch": approval["branch"],
                      "baseline_head": approval["baseline_head"], "current_head": descendant["current_head"],
                      "governance_only": descendant["governance_only"], "scope": approval["canonical_lv_scope"],
                      "resume_bridge": bridge, "next_gate": "USER_APPROVAL_REQUIRED", "hard_stop": True}
            if args.command == "production-gate-run":
                if not args.run_id:
                    raise GateControllerError("--run-id is required for production-gate-run")
                auth = create_gate_authorization(plan, approval["event_id"], mode=args.mode)
                import subprocess
                head = subprocess.run(["git", "-C", args.project_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
                context = {"project_id": plan.project_id, "gate_id": args.gate_id, "lv_id": bridge["first_incomplete_lv"],
                           "run_id": args.run_id, "plan_sha256": plan.canonical_plan_sha256,
                           "branch": approval["branch"], "baseline_head": approval["baseline_head"],
                           "approval_mode": args.mode, "canonical_lv_scope": approval["canonical_lv_scope"],
                           "owned_file_scope": approval["owned_file_scope"], "phase": "PHASE-1"}
                outcome = __import__("runtime.orchestrator.gate_controller", fromlist=["run_production_gate_lifecycle"]).run_production_gate_lifecycle(
                    context, _production_adapters(Path(args.project_root), plan, auth, bridge["first_incomplete_lv"], args.run_id, args.harness_root),
                    approval_events=[approval], project_root=args.project_root,
                    canonical_state=canonical_state,
                    completion_conditions_sha256=approval["completion_conditions_sha256"],
                    historical_predecessor=approval.get("predecessor"),
                    historical_event_ids=((approval["supersedes"],) if approval.get("supersedes") else ()))
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
        _print({"error": str(exc), "error_type": "lv_execution_package_error"})
        return 7
    except LVReviewError as exc:
        _print({"error": str(exc), "error_type": "lv_review_error"})
        return 8
    except LVRemediationError as exc:
        _print({"error": str(exc), "error_type": "lv_remediation_error"})
        return 11
    except GateOrchestrationError as exc:
        _print({"error": str(exc), "error_type": "gate_orchestration_error"})
        return 12
    except GateApprovalError as exc:
        _print({"error": str(exc), "error_type": "gate_approval_error"})
        return 13
    except ProjectIsolationError as exc:
        _print({"error": str(exc), "error_type": "project_isolation_error"})
        return 14
    except ProductionApprovalError as exc:
        _print({"error": str(exc), "error_type": "production_approval_error", "status": "BLOCKED"})
        return 16
    except MappingMigrationError as exc:
        _print({"error": str(exc), "error_type": "mapping_migration_error", "status": "BLOCKED"})
        return 17
    except (GateControllerError, ResumeStoreError) as exc:
        _print({"error": str(exc), "error_type": "gate_controller_error", "status": "BLOCKED", "hard_stop": True})
        return 15

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

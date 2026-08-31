from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .contract_adapter import load_project_mapping, sha256_file, evaluate_canonical_state
from .lv_execution_package import canonical_json_bytes
from .lv_preview import _declared_owned_files, _gate_section, _tables
from .lv_execution_package import create_lv_execution_package
from .lv_review import preflight_run, review_run
from .gate_approval import load_approval_evidence, validate_approval_evidence
from .fixed_runner import COMMAND_REGISTRY, registry_sha256, seal_action_manifest, run_sealed_action
from .schemas import TaskSlice, WorkerRequest
from .lv_execution_package import validate_worker_result
from .project_isolation import AssetManifest, ProjectIsolation, route_assets
from .gate_controller import GateControllerAdapters, GateControllerError, run_gate_lifecycle
from .resume_store import ResumeStore, RunBinding, ResumeStoreError
from .completeness import REQUIREMENT_IDS, build_ledger, load_ledger, save_ledger, validate_ledger as validate_completeness_ledger

GATE_BY_GATE = "GATE_BY_GATE"
FULL_PLAN = "FULL_PLAN"
RESUME = "RESUME"
MODES = {GATE_BY_GATE, FULL_PLAN, RESUME}
LEDGER_STATUSES = {"PENDING", "IN_PROGRESS", "IMPLEMENTED", "VERIFIED", "CHECKPOINTED", "EXITED", "BLOCKED"}
LIFECYCLE = ("PLAN", "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION", "CHECKPOINT", "EXIT", "HANDOFF")
SYSTEM_TRANSITION = "SYSTEM_TRANSITION"
_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_GATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_LV_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class GateOrchestrationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value: object) -> str:
    return _sha(canonical_json_bytes(value))


def _safe_project(root: str | Path) -> tuple[Path, str]:
    supplied = Path(root)
    if not supplied.is_dir() or supplied.absolute() != supplied.resolve():
        raise GateOrchestrationError("project root is missing or contains symlinked components")
    resolved = supplied.resolve(); project_id = resolved.name
    if not _PROJECT_ID.fullmatch(project_id):
        raise GateOrchestrationError("project ID is unsafe")
    return resolved, project_id


def _safe_scope(value: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or "\\" in value:
        raise GateOrchestrationError(f"unsafe project-relative scope: {value}")
    normalized = value.rstrip("/")
    pure = PurePosixPath(normalized)
    if not normalized or ".." in pure.parts or pure.as_posix() != normalized:
        raise GateOrchestrationError(f"unsafe project-relative scope: {value}")
    return normalized + "/" if value.endswith("/") else normalized


def _safe_relative(value: str) -> str:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value or "\\" in value:
        raise GateOrchestrationError(f"unsafe project-relative path: {value}")
    return value


def _atomic_json(path: Path, payload: object, *, overwrite: bool = False) -> str:
    if path.exists() and not overwrite:
        raise GateOrchestrationError(f"immutable artifact already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(payload); digest = _sha(data)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle: handle.write(data)
        os.replace(temp_name, path)
    except Exception:
        try: os.unlink(temp_name)
        except OSError: pass
        raise
    return digest


@dataclass(frozen=True)
class GateLV:
    gate_id: str
    lv_id: str
    order: int
    purpose: str
    dependencies: list[str]
    owned_files: list[str]
    completion_criteria: list[str]
    execution: str
    tests: list[str]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class GatePlan:
    project_id: str
    project_root: str
    gate_id: str
    canonical_plan_path: str
    canonical_plan_sha256: str
    lvs: list[GateLV]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["lvs"] = [item.to_dict() for item in self.lvs]; return payload


@dataclass(frozen=True)
class GateAuthorization:
    schema_version: str
    authorization_id: str
    project_id: str
    gate_id: str
    canonical_plan_sha256: str
    approved_lvs: list[str]
    lv_order: list[str]
    owned_files_by_lv: dict[str, list[str]]
    completion_criteria_by_lv: dict[str, list[str]]
    allowed_execution: list[str]
    allowed_checkpoint: bool
    allowed_exit: bool
    stop_conditions: list[str]
    mode: str
    approved_at: str
    full_plan_opt_in: bool
    project_final_validation: bool

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class CompletenessItem:
    plan_item: str
    gate_id: str
    lv_id: str
    assigned_asset: str
    owned_files: list[str]
    tests: list[str]
    evidence_sha256: str
    status: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def _owned_from_rows(summary: dict[str, str], detail: dict[str, str]) -> list[str]:
    try:
        return _declared_owned_files(summary, detail)
    except Exception:
        raw = re.findall(r"`([^`]+)`", detail.get("owned_files", "") + " " + summary.get("대상", ""))
        return [_safe_relative(item) for item in dict.fromkeys(raw) if "/" in item or item.endswith((".py", ".md", ".json", ".txt"))]


def load_gate_plan(project_root: str | Path, gate_id: str) -> GatePlan:
    root, project_id = _safe_project(project_root)
    match = _GATE_ID.fullmatch(gate_id)
    if not match: raise GateOrchestrationError("invalid Gate ID")
    mapping = load_project_mapping(root)
    if mapping is None: raise GateOrchestrationError("project declarative mapping is required")
    plan = mapping.canonical_source
    if sha256_file(plan) != mapping.canonical_sha256:
        raise GateOrchestrationError("canonical plan SHA mismatch")
    section = _gate_section(plan.read_text(encoding="utf-8"), gate_id)
    summaries: dict[str, dict[str, str]] = {}; details: dict[str, dict[str, str]] = {}
    for headers, rows in _tables(section):
        if {"ID", "작업", "완료조건"}.issubset(headers):
            for row in rows:
                if _LV_ID.fullmatch(row.get("ID", "")): summaries[row["ID"]] = row
        if {"ID", "depends_on", "execution", "owned_files"}.issubset(headers):
            for row in rows:
                if _LV_ID.fullmatch(row.get("ID", "")): details[row["ID"]] = row
    if not summaries or set(summaries) != set(details):
        raise GateOrchestrationError("canonical Gate LV tables are incomplete or inconsistent")
    ordered_ids = list(summaries)
    lvs: list[GateLV] = []
    for order, lv_id in enumerate(ordered_ids, 1):
        detail = details[lv_id]; summary = summaries[lv_id]
        exit_column = next((key for key in detail if "exit_check" in key), "")
        criteria = [value for value in (summary.get("완료조건", ""), detail.get(exit_column, "")) if value]
        owned = _owned_from_rows(summary, detail)
        tests = [path for path in owned if path.startswith("tests/")]
        lvs.append(GateLV(gate_id, lv_id, order, summary["작업"], [x.strip() for x in detail["depends_on"].split(",") if x.strip()], owned, criteria, detail["execution"], tests))
    return GatePlan(project_id, str(root), gate_id, plan.relative_to(root).as_posix(), mapping.canonical_sha256, lvs)


def create_gate_authorization(plan: GatePlan, authorization_id: str, *, mode: str = GATE_BY_GATE, full_plan_opt_in: bool = False, project_final_validation: bool = False) -> GateAuthorization:
    if not authorization_id or len(authorization_id) > 128: raise GateOrchestrationError("authorization ID is invalid")
    mode = mode.upper()
    if mode not in MODES: raise GateOrchestrationError("unsupported Gate execution mode")
    if mode == FULL_PLAN and not (full_plan_opt_in and project_final_validation):
        raise GateOrchestrationError("FULL_PLAN requires final validation and explicit opt-in")
    order = [item.lv_id for item in plan.lvs]
    return GateAuthorization(
        "orchestration.gate.authorization.v1", authorization_id, plan.project_id, plan.gate_id,
        plan.canonical_plan_sha256, order, order,
        {item.lv_id: item.owned_files for item in plan.lvs},
        {item.lv_id: item.completion_criteria for item in plan.lvs},
        list(LIFECYCLE), True, True,
        ["scope expansion", "out-of-Gate LV", "non-owned file", "canonical plan drift", "dangerous or external action", "project isolation violation"],
        mode, _now(), full_plan_opt_in, project_final_validation,
    )


def validate_authorization(plan: GatePlan, authorization: GateAuthorization) -> None:
    if authorization.project_id != plan.project_id or authorization.gate_id != plan.gate_id or authorization.canonical_plan_sha256 != plan.canonical_plan_sha256:
        raise GateOrchestrationError("Gate authorization identity or plan SHA mismatch")
    expected = [item.lv_id for item in plan.lvs]
    if authorization.approved_lvs != expected or authorization.lv_order != expected:
        raise GateOrchestrationError("Gate authorization LV completeness/order mismatch")
    for item in plan.lvs:
        if authorization.owned_files_by_lv.get(item.lv_id) != item.owned_files or authorization.completion_criteria_by_lv.get(item.lv_id) != item.completion_criteria:
            raise GateOrchestrationError("Gate authorization scope/completion binding mismatch")
    if authorization.mode == FULL_PLAN and not (authorization.full_plan_opt_in and authorization.project_final_validation):
        raise GateOrchestrationError("FULL_PLAN activation is blocked")


def initial_ledger(plan: GatePlan, asset: str = "project-orchestrator") -> list[CompletenessItem]:
    return [CompletenessItem(item.lv_id, item.gate_id, item.lv_id, asset, item.owned_files, item.tests, "", "PENDING") for item in plan.lvs]


def validate_ledger(plan: GatePlan, ledger: list[CompletenessItem], *, exit_required: bool = False) -> None:
    expected = [item.lv_id for item in plan.lvs]
    if [item.plan_item for item in ledger] != expected or len({item.plan_item for item in ledger}) != len(expected):
        raise GateOrchestrationError("completeness ledger has missing, duplicate, or reordered plan items")
    for source, item in zip(plan.lvs, ledger):
        if item.gate_id != source.gate_id or item.lv_id != source.lv_id or item.owned_files != source.owned_files or item.tests != source.tests or item.status not in LEDGER_STATUSES:
            raise GateOrchestrationError("completeness ledger binding mismatch")
        if item.status in {"VERIFIED", "CHECKPOINTED", "EXITED"} and not re.fullmatch(r"[0-9a-f]{64}", item.evidence_sha256):
            raise GateOrchestrationError("verified ledger item requires evidence SHA")
    if exit_required and any(item.status != "EXITED" for item in ledger):
        raise GateOrchestrationError("Gate Exit blocked by incomplete plan ledger")


def derive_transition(plan: GatePlan, authorization: GateAuthorization, current_lv: str | None, completed_lvs: list[str]) -> dict[str, Any]:
    validate_authorization(plan, authorization)
    order = authorization.lv_order
    if completed_lvs != order[:len(completed_lvs)]:
        raise GateOrchestrationError("completed LV history is missing or reordered")
    if current_lv is not None and current_lv not in order:
        raise GateOrchestrationError("current LV is outside Gate authorization")
    index = len(completed_lvs)
    if index >= len(order):
        return {"event_type": SYSTEM_TRANSITION, "from_lv": current_lv, "to_lv": None, "gate_exit_ready": True, "authorization_id": authorization.authorization_id, "user_approval_renewal": False}
    next_lv = order[index]
    if current_lv is not None and current_lv not in completed_lvs and current_lv != next_lv:
        raise GateOrchestrationError("LV transition order mismatch")
    return {"event_type": SYSTEM_TRANSITION, "from_lv": current_lv, "to_lv": next_lv, "gate_exit_ready": False, "authorization_id": authorization.authorization_id, "user_approval_renewal": False, "canonical_plan_sha256": plan.canonical_plan_sha256}


def gate_exit_action(authorization: GateAuthorization, next_gate_id: str | None) -> dict[str, Any]:
    if authorization.mode == GATE_BY_GATE:
        return {"action": "WAIT_FOR_NEXT_GATE_USER_APPROVAL", "next_gate_id": next_gate_id, "automatic": False, "hard_stop": True}
    if authorization.mode == FULL_PLAN:
        if not (authorization.full_plan_opt_in and authorization.project_final_validation):
            raise GateOrchestrationError("FULL_PLAN activation is blocked")
        return {"action": SYSTEM_TRANSITION, "next_gate_id": next_gate_id, "automatic": True, "hard_stop": True}
    return {"action": "RESUME_COMPLETE", "next_gate_id": next_gate_id, "automatic": False, "hard_stop": True}


def validate_owned_access(authorization: GateAuthorization, lv_id: str, paths: list[str]) -> None:
    if lv_id not in authorization.approved_lvs: raise GateOrchestrationError("LV is outside Gate authorization")
    allowed = [_safe_scope(path) for path in authorization.owned_files_by_lv[lv_id]]
    requested = {_safe_relative(path) for path in paths}
    if any(not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in allowed) for path in requested):
        raise GateOrchestrationError("owned-file access is outside authorized LV scope")


def validate_concurrent_ownership(assignments: dict[str, list[str]]) -> None:
    scopes: list[tuple[str, str]] = []
    for lv_id, files in assignments.items():
        for raw in files:
            scope = _safe_scope(raw)
            for prior_scope, prior_lv in scopes:
                left = scope.rstrip("/"); right = prior_scope.rstrip("/")
                overlap = left == right or (scope.endswith("/") and right.startswith(scope)) or (prior_scope.endswith("/") and left.startswith(prior_scope))
                if overlap and prior_lv != lv_id:
                    raise GateOrchestrationError(f"concurrent file ownership conflict: {scope}")
            scopes.append((scope, lv_id))


def advance_lifecycle(stage: str, event: str, *, review_verdict: str | None = None) -> dict[str, Any]:
    if stage not in LIFECYCLE: raise GateOrchestrationError("unknown lifecycle stage")
    if event == "BLOCKED": return {"stage": stage, "status": "BLOCKED", "user_handoff": True, "hard_stop": True}
    if stage == "REVIEW" and (review_verdict == "FAIL" or event == "FAIL"):
        return {"stage": "REMEDIATION", "status": "IN_PROGRESS", "same_lv": True, "user_handoff": False, "hard_stop": True}
    if stage == "REMEDIATION":
        if event == "BLOCKED": return {"stage": stage, "status": "BLOCKED", "user_handoff": True, "hard_stop": True}
        if event != "PASS": raise GateOrchestrationError("remediation requires PASS or BLOCKED")
        return {"stage": "CHECKPOINT", "status": "IN_PROGRESS", "same_lv": True, "user_handoff": False, "hard_stop": True}
    index = LIFECYCLE.index(stage)
    if index == len(LIFECYCLE) - 1: return {"stage": "HANDOFF", "status": "COMPLETE", "hard_stop": True}
    if event != "PASS": raise GateOrchestrationError("lifecycle advance requires PASS or explicit BLOCKED")
    return {"stage": LIFECYCLE[index + 1], "status": "IN_PROGRESS", "hard_stop": stage in {"PACKAGE", "PREFLIGHT", "REVIEW"}, "user_handoff": False}


def recovery_checkpoint(project_id: str, gate_id: str, lv_id: str, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    payload = {"schema_version": "orchestration.gate.checkpoint.v1", "project_id": project_id, "gate_id": gate_id, "lv_id": lv_id, "run_id": run_id, "state": state, "sealed_at": _now()}
    return {"payload": payload, "sha256": _canonical_hash(payload)}


def resume_from_checkpoint(checkpoint: dict[str, Any], *, project_id: str, gate_id: str, run_id: str) -> dict[str, Any]:
    payload = checkpoint.get("payload"); digest = checkpoint.get("sha256")
    if not isinstance(payload, dict) or digest != _canonical_hash(payload): raise GateOrchestrationError("checkpoint SHA mismatch")
    if payload.get("project_id") != project_id or payload.get("gate_id") != gate_id or payload.get("run_id") != run_id:
        raise GateOrchestrationError("checkpoint namespace mismatch")
    return dict(payload["state"])


def structured_handoff(plan: GatePlan, authorization: GateAuthorization, *, lv_id: str, run_id: str, branch: str, head: str, completed_plan_items: list[str], remaining_plan_items: list[str], changed_files: list[str], tests: list[dict[str, Any]], review: dict[str, Any], artifact_sha256: str, used_assets: list[str], recovery: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version": "orchestration.gate.handoff.v1", "project": plan.project_id, "gate": plan.gate_id, "lv": lv_id, "run_id": run_id,
        "canonical_plan_sha256": plan.canonical_plan_sha256, "branch": branch, "head": head,
        "completed_plan_items": completed_plan_items, "remaining_plan_items": remaining_plan_items,
        "owned_files": authorization.owned_files_by_lv[lv_id], "changed_files": changed_files,
        "tests": tests, "review": review, "artifact_sha256": artifact_sha256,
        "known_issues": [], "deferred_items": [], "next_stage_input": remaining_plan_items[:1],
        "next_stage_completion_criteria": authorization.completion_criteria_by_lv[lv_id],
        "authorization": {"id": authorization.authorization_id, "derived": True},
        "prohibitions": ["non-owned change", "next Gate without authorization", "artifact overwrite", "secret access"],
        "used_assets": used_assets, "asset_selection_reason": "existing assets before capability-gap creation",
        "recovery_checkpoint": recovery, "hard_stop": True,
    }
    fields["handoff_sha256"] = _canonical_hash(fields)
    return fields


def validate_handoff(handoff: dict[str, Any], plan: GatePlan, authorization: GateAuthorization) -> None:
    required = {"schema_version", "project", "gate", "lv", "run_id", "canonical_plan_sha256", "branch", "head", "completed_plan_items", "remaining_plan_items", "owned_files", "changed_files", "tests", "review", "artifact_sha256", "known_issues", "deferred_items", "next_stage_input", "next_stage_completion_criteria", "authorization", "prohibitions", "used_assets", "asset_selection_reason", "recovery_checkpoint", "hard_stop", "handoff_sha256"}
    if set(handoff) != required: raise GateOrchestrationError("structured handoff required field mismatch")
    unsigned = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    if handoff["handoff_sha256"] != _canonical_hash(unsigned): raise GateOrchestrationError("structured handoff SHA mismatch")
    if handoff["project"] != plan.project_id or handoff["gate"] != plan.gate_id or handoff["canonical_plan_sha256"] != plan.canonical_plan_sha256:
        raise GateOrchestrationError("structured handoff project/Gate/plan mismatch")
    validate_owned_access(authorization, handoff["lv"], handoff["changed_files"])


def namespace_root(harness_root: str | Path, project_id: str, kind: str) -> Path:
    if not _PROJECT_ID.fullmatch(project_id): raise GateOrchestrationError("unsafe namespace project ID")
    if kind not in {"approval", "state", "artifact", "run", "secret"}: raise GateOrchestrationError("unknown namespace kind")
    base = Path(harness_root).resolve() / "_workspace" / "global-gate" / project_id / kind
    expected = Path(harness_root).resolve() / "_workspace" / "global-gate" / project_id
    if base.parent != expected: raise GateOrchestrationError("project namespace escapes isolation root")
    return base


def select_assets(global_assets: list[Mapping[str, Any]], project_assets: list[Mapping[str, Any]],
                  required: list[str], *, permissions: list[str], owned_files: list[str]) -> dict[str, Any]:
    from .project_isolation import AssetManifest, route_assets
    manifests = [AssetManifest.from_mapping(item) for item in global_assets + project_assets]
    routed = route_assets(manifests, capabilities=set(required), permissions=set(permissions), owned_files=owned_files)
    return {**routed, "strategy": "EXACT_REGISTRY_MANIFEST", "capability_gaps": required if not routed["selected"] else [],
            "global_creation_authorized": False}


def compatibility_dry_run(project_root: str | Path, gate_id: str, *, mode: str = GATE_BY_GATE) -> dict[str, Any]:
    root, project_id = _safe_project(project_root)
    try:
        plan = load_gate_plan(root, gate_id)
        authorization = create_gate_authorization(plan, "DRY-RUN", mode=mode)
        ledger = initial_ledger(plan); validate_ledger(plan, ledger)
        return {"status": "COMPATIBLE", "project_id": project_id, "gate_id": gate_id, "plan_sha256": plan.canonical_plan_sha256, "lv_order": authorization.lv_order, "mutation_performed": False, "default_mode": GATE_BY_GATE, "full_plan_active": False}
    except Exception as exc:
        return {"status": "BLOCKED", "project_id": project_id, "gate_id": gate_id, "reason": str(exc), "mutation_performed": False, "default_mode": GATE_BY_GATE, "full_plan_active": False}


def onboarding_dry_run(project_root: str | Path, alias: str) -> dict[str, Any]:
    root, project_id = _safe_project(project_root)
    required = [root / "AGENTS.md", root / "docs/DEVELOPMENT_PLAN.txt", root / "CHANGELOG.txt", root / "logs/app.log"]
    missing = [path.relative_to(root).as_posix() for path in required if not path.is_file()]
    return {"schema_version": "orchestration.project.onboarding.v1", "project_id": project_id, "path": str(root), "alias": alias, "mapping_ready": not missing, "missing_contracts": missing, "namespaces": ["approval", "state", "artifact", "run", "secret"], "mutation_performed": False, "fail_closed": bool(missing)}


def validate_global_gate_bindings(project_root: str | Path, gate_id: str, *, requirements_sha256: str,
                                  approval_evidence: str | Path, branch: str, head: str,
                                  harness_root: str | Path) -> dict[str, Any]:
    """Validate the W0-W6 boundary without executing a lifecycle or mutating the project."""
    root, project_id = _safe_project(project_root)
    plan = load_gate_plan(root, gate_id)
    order = [item.lv_id for item in plan.lvs]
    owned = {item.lv_id: item.owned_files for item in plan.lvs}
    evidence = load_approval_evidence(approval_evidence)
    approval = validate_approval_evidence(
        evidence, project_id=project_id, gate_id=gate_id, requirements_sha256=requirements_sha256,
        plan_sha256=plan.canonical_plan_sha256, branch=branch, head=head, lv_order=order,
        owned_files_by_lv=owned,
    )
    harness = Path(harness_root)
    isolation = ProjectIsolation(harness, root, project_id, project_id, {project_id: project_id})
    namespaces = {kind: str(isolation.namespace_path(kind, "validation.json")) for kind in ("approval", "state", "artifact", "run", "secret")}
    return {
        "status": "VALIDATED", "mutation_performed": False, "project_id": project_id,
        "gate_id": gate_id, "requirements_sha256": requirements_sha256,
        "plan_sha256": plan.canonical_plan_sha256, "approval_id": approval["approval_id"],
        "lv_order": order, "registry_sha256": registry_sha256(COMMAND_REGISTRY),
        "namespaces": namespaces, "default_mode": GATE_BY_GATE, "full_plan_active": False,
        "next_gate_automatic": False, "hard_stop": True,
    }


def load_requirement_evidence(path: str | Path, *, requirements_sha256: str) -> dict[str, Mapping[str, Any]]:
    source = Path(path)
    if not source.is_file() or source.is_symlink() or source.stat().st_size > 1024 * 1024:
        raise GateOrchestrationError("requirement evidence is missing or unsafe")
    try: envelope = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError("requirement evidence is malformed") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "requirements_sha256", "evidence"}:
        raise GateOrchestrationError("requirement evidence envelope mismatch")
    if envelope["schema_version"] != "orchestration.requirement-evidence.v1" or envelope["requirements_sha256"] != requirements_sha256:
        raise GateOrchestrationError("requirement evidence requirements SHA mismatch")
    evidence = envelope["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != set(REQUIREMENT_IDS) or any(not isinstance(value, dict) for value in evidence.values()):
        raise GateOrchestrationError("exact R01-R25 requirement evidence mapping is required")
    return evidence


def load_engine_conformance_evidence(path: str | Path, *, requirements_sha256: str) -> dict[str, Mapping[str, Any]]:
    """Compatibility reader for Harness R01-R25 conformance evidence."""
    return load_requirement_evidence(path, requirements_sha256=requirements_sha256)


def load_project_requirement_contract(path: str | Path, *, project_id: str, gate_id: str,
                                     lv_id: str, plan_sha256: str,
                                     expected_requirement_ids: list[str] | tuple[str, ...]) -> dict[str, Mapping[str, Any]]:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise GateOrchestrationError("project requirement contract is missing or unsafe")
    try: envelope = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError("project requirement contract is malformed") from exc
    if not isinstance(envelope, dict) or envelope.get("schema_version") != "orchestration.project-requirement-contract.v1":
        raise GateOrchestrationError("unknown project requirement contract schema")
    requirements = envelope.get("requirements")
    expected = tuple(expected_requirement_ids)
    if not isinstance(requirements, dict) or set(requirements) != set(expected) or len(requirements) != len(expected):
        raise GateOrchestrationError("project requirement IDs are missing, duplicated, or unknown")
    result: dict[str, Mapping[str, Any]] = {}
    for requirement_id in expected:
        item = requirements[requirement_id]
        if not isinstance(item, dict) or item.get("project_id") != project_id or item.get("gate_id") != gate_id or item.get("lv_id") != lv_id or item.get("plan_sha256") != plan_sha256 or item.get("status") != "PENDING" or item.get("verdict") is not None:
            raise GateOrchestrationError(f"project requirement {requirement_id} binding mismatch")
        result[requirement_id] = item
    return result


def dispatch_requirement_artifact(path: str | Path, *, project_id: str, gate_id: str, lv_id: str,
                                  plan_sha256: str, expected_requirement_ids: Sequence[str]) -> dict[str, Any]:
    """Dispatch by explicit schema version; never infer engine/project scope."""
    source = Path(path)
    try: envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError("requirement artifact is malformed") from exc
    version = envelope.get("schema_version") if isinstance(envelope, dict) else None
    if version == "orchestration.project-requirement-contract.v1":
        return {"profile": "project", "requirements": load_project_requirement_contract(source, project_id=project_id, gate_id=gate_id, lv_id=lv_id, plan_sha256=plan_sha256, expected_requirement_ids=expected_requirement_ids)}
    if version == "orchestration.requirement-evidence.v1":
        return {"profile": "engine", "requirements": load_engine_conformance_evidence(source, requirements_sha256=str(envelope.get("requirements_sha256", "")))}
    raise GateOrchestrationError("unknown requirement artifact schema")


def seal_requirement_semantic_metadata(*, requirement_id: str, semantic_metadata: Mapping[str, Any],
                                       canonical_plan_sha256: str, project_id: str, gate_id: str,
                                       lv_id: str) -> dict[str, Any]:
    """Create the stable, independently verifiable Rxx semantic binding."""
    if requirement_id not in REQUIREMENT_IDS:
        raise GateOrchestrationError("unknown requirement ID")
    metadata = dict(semantic_metadata)
    if metadata.get("requirement_id") != requirement_id:
        raise GateOrchestrationError("requirement semantic metadata ID mismatch")
    envelope = {"requirement_id": requirement_id, "semantic_metadata": metadata,
                "canonical_plan_sha256": canonical_plan_sha256, "project_id": project_id,
                "gate_id": gate_id, "lv_id": lv_id}
    envelope["semantic_sha256"] = _canonical_hash(metadata)
    return envelope


def validate_requirement_semantic_binding(item: Mapping[str, Any], *, requirement_id: str,
                                          project_id: str, gate_id: str, lv_id: str,
                                          canonical_plan_sha256: str) -> None:
    """Fail closed on semantic metadata tamper or scope drift."""
    required = {"requirement_id", "semantic_metadata", "semantic_sha256", "canonical_plan_sha256",
                "project_id", "gate_id", "lv_id"}
    if not required.issubset(item):
        raise GateOrchestrationError(f"{requirement_id} semantic metadata binding is missing")
    if item["requirement_id"] != requirement_id or item["project_id"] != project_id or item["gate_id"] != gate_id or item["lv_id"] != lv_id or item["canonical_plan_sha256"] != canonical_plan_sha256:
        raise GateOrchestrationError(f"{requirement_id} semantic binding scope mismatch")
    metadata = item["semantic_metadata"]
    if not isinstance(metadata, Mapping) or metadata.get("requirement_id") != requirement_id:
        raise GateOrchestrationError(f"{requirement_id} semantic metadata is invalid")
    if item["semantic_sha256"] != _canonical_hash(metadata):
        raise GateOrchestrationError(f"{requirement_id} semantic metadata SHA drift")


def validate_evidence_binding(evidence: Mapping[str, Any], *, requirement_id: str,
                              project_id: str, gate_id: str, lv_id: str,
                              canonical_plan_sha256: str, lifecycle_attempt: int | str) -> None:
    """Validate the common schema used by implementation/test/review evidence."""
    required = {"project_id", "gate_id", "lv_id", "requirement_id", "canonical_plan_sha256",
                "evidence_type", "producer", "content", "artifact_sha256", "lifecycle_attempt"}
    if set(evidence) != required:
        raise GateOrchestrationError(f"{requirement_id} evidence schema is incomplete")
    if (evidence["project_id"], evidence["gate_id"], evidence["lv_id"], evidence["requirement_id"], evidence["canonical_plan_sha256"]) != (project_id, gate_id, lv_id, requirement_id, canonical_plan_sha256):
        raise GateOrchestrationError(f"{requirement_id} evidence scope binding mismatch")
    if evidence["evidence_type"] not in {"implementation", "test", "review"} or not evidence["producer"] or not isinstance(evidence["content"], Mapping):
        raise GateOrchestrationError(f"{requirement_id} evidence content schema is invalid")
    if evidence["lifecycle_attempt"] != lifecycle_attempt:
        raise GateOrchestrationError(f"{requirement_id} stale lifecycle attempt evidence")
    digest = evidence["artifact_sha256"]
    unsigned = {key: value for key, value in evidence.items() if key != "artifact_sha256"}
    if not isinstance(digest, str) or digest != _canonical_hash(unsigned):
        raise GateOrchestrationError(f"{requirement_id} evidence SHA mismatch")


def load_approved_authorization(project_root: str | Path, gate_id: str, *, mode: str = GATE_BY_GATE) -> GateAuthorization:
    """Load the canonical approval/state binding; never fabricate approval scope."""
    root, _ = _safe_project(project_root)
    plan = load_gate_plan(root, gate_id)
    mapping = load_project_mapping(root)
    if mapping is None:
        raise GateOrchestrationError("project declarative mapping is required")
    try:
        state = evaluate_canonical_state(mapping)
    except Exception as exc:
        raise GateOrchestrationError(f"canonical approval/state validation failed: {exc}") from exc
    if state.get("gate_id") not in (None, gate_id) or state.get("transition_authorized") is not True:
        raise GateOrchestrationError("Gate approval is not active for this project/Gate")
    approval_id = (getattr(mapping, "gate_approval_ids", None) or {}).get(gate_id) or getattr(mapping, "transition_approval_id", None)
    if not approval_id:
        activation_path = root / "docs" / "harness" / "first-gate.activation.json"
        if activation_path.is_file() and not activation_path.is_symlink():
            try:
                activation = json.loads(activation_path.read_text(encoding="utf-8"))
                if activation.get("gate_id") == gate_id and activation.get("state") == "ACTIVE":
                    approval_id = activation.get("approval_id")
            except (OSError, UnicodeError, json.JSONDecodeError):
                approval_id = None
    if not approval_id:
        raise GateOrchestrationError("canonical Gate approval ID is missing")
    auth = create_gate_authorization(plan, approval_id, mode=mode)
    validate_authorization(plan, auth)
    return auth


def activate_first_gate(project_root: str | Path, gate_id: str, approval_evidence: str | Path, *,
                        mapping_root: str | Path | None = None) -> dict[str, Any]:
    """Receive a sealed first-Gate approval at the project boundary.

    This records an immutable activation envelope; it does not fabricate a
    predecessor Gate checkpoint or grant LV-specific user approvals.
    """
    root, project_id = _safe_project(project_root)
    plan = load_gate_plan(root, gate_id)
    envelope = load_approval_evidence(approval_evidence)
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    validated = validate_approval_evidence(
        envelope, project_id=project_id, gate_id=gate_id,
        requirements_sha256=str(payload["requirements_sha256"]), plan_sha256=plan.canonical_plan_sha256,
        branch="main", head=head, lv_order=[item.lv_id for item in plan.lvs],
        owned_files_by_lv={item.lv_id: item.owned_files for item in plan.lvs},
    )
    activation = {"schema_version": "orchestration.first-gate.activation.v1", "project_id": project_id,
                  "gate_id": gate_id, "plan_sha256": plan.canonical_plan_sha256,
                  "approval_id": validated["approval_id"], "approval_record_hash": envelope["record_hash"],
                  "branch": "main", "head": head, "lv_order": [item.lv_id for item in plan.lvs],
                  "owned_files": plan.lvs[0].owned_files,
                  "state": "ACTIVE", "system_transition": True}
    # Materialize the legacy approval-log event shape so existing readers can
    # validate the new bootstrap lineage without a second schema.
    event = {"approval_id": validated["approval_id"], "target_type": "GATE", "target_id": gate_id,
             "approval_type": "START_GATE", "approval_scope": {"lv3_ids": activation["lv_order"], "owned_files": activation["owned_files"]},
             "approval_version": 1, "approval_hash_version": 1, "plan_version": "GENERIC",
             "plan_sha256": plan.canonical_plan_sha256, "external_action": False, "action_parameters": {},
             "approved_hash": envelope["record_hash"], "approved_by": "USER", "approved_at": payload["issued_at"],
             "expires_at": payload["expires_at"], "source_reference": "BOOTSTRAP_GENESIS",
             "approval_event_type": "APPROVED", "previous_approval_id": None, "revokes_approval_id": None,
             "previous_record_hash": None}
    event["record_hash"] = hashlib.sha256(canonical_json_bytes(event)).hexdigest()
    path = root / "docs" / "harness" / "first-gate.activation.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != activation:
            raise GateOrchestrationError("first Gate approval replay or activation drift")
        return {"status": "ALREADY_ACTIVE", **activation}
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, activation)
    state_path = root / "docs" / "GATE_STATE.md"
    ledger = {"schema_version": 1, "project_id": project_id, "gate_id": gate_id, "gate_state": "GATE1_ACTIVE",
              "canonical_plan": plan.canonical_plan_path, "plan_sha256": plan.canonical_plan_sha256,
              "approval_id": event["approval_id"], "approval_record_hash": event["record_hash"],
              "active_scope": activation["lv_order"], "owned_files": activation["owned_files"]}
    state_path.write_text("# Gate State Ledger\n\nStatus: FIRST_GATE_ACTIVE\n\n```json\n" + json.dumps(ledger, sort_keys=True, indent=2) + "\n```\n", encoding="utf-8")
    approval_path = root / "docs" / "APPROVAL_LOG.md"
    approval_path.write_text("# Approval Log\n\n```json\n" + json.dumps(event, sort_keys=True, indent=2) + "\n```\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", "docs/GATE_STATE.md", "docs/APPROVAL_LOG.md", "docs/harness/first-gate.activation.json"], check=True, capture_output=True)
    committed = subprocess.run(["git", "-C", str(root), "-c", "user.name=Harness Bootstrap", "-c", "user.email=harness-bootstrap@localhost", "commit", "-m", f"chore(orchestration): activate {gate_id}"], check=False, capture_output=True, text=True)
    if committed.returncode != 0:
        raise GateOrchestrationError("first Gate activation commit failed")
    return {"status": "ACTIVATED", **activation}


def persist_checkpoint(harness_root: str | Path, plan: GatePlan, authorization: GateAuthorization, state: dict[str, Any]) -> dict[str, Any]:
    """Seal a durable checkpoint without overwriting an existing artifact."""
    payload = recovery_checkpoint(plan.project_id, plan.gate_id, state.get("lv_id", ""), state["run_id"], state)
    stage = str(state.get("current_stage", "UNKNOWN")).lower()
    if not re.fullmatch(r"[a-z]+", stage):
        raise GateOrchestrationError("unsafe checkpoint stage")
    path = namespace_root(harness_root, plan.project_id, "state") / f"{plan.gate_id}-{state['run_id']}-{stage}.checkpoint.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise GateOrchestrationError("checkpoint overwrite or drift detected")
        return payload
    _atomic_json(path, payload)
    return payload


def resume_persisted(harness_root: str | Path, plan: GatePlan, authorization: GateAuthorization, run_id: str) -> dict[str, Any]:
    base = namespace_root(harness_root, plan.project_id, "state")
    paths = list(base.glob(f"{plan.gate_id}-{run_id}-*.checkpoint.json")) if base.is_dir() else []
    order = {stage.lower(): index for index, stage in enumerate(LIFECYCLE)}
    candidates = []
    for path in paths:
        if not path.is_file() or path.is_symlink(): raise GateOrchestrationError("sealed checkpoint is unsafe")
        stage = path.name.removeprefix(f"{plan.gate_id}-{run_id}-").removesuffix(".checkpoint.json")
        if stage not in order: raise GateOrchestrationError("sealed checkpoint stage is unknown")
        candidates.append((order[stage], path))
    if not candidates:
        raise GateOrchestrationError("sealed checkpoint is missing")
    path = max(candidates, key=lambda item: item[0])[1]
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    return resume_from_checkpoint(checkpoint, project_id=plan.project_id, gate_id=plan.gate_id, run_id=run_id)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_worker_result_ok(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    value = path.lstat()
    return value.st_uid == os.getuid() and stat.S_IMODE(value.st_mode) == 0o600


def _production_adapters(root: Path, plan: GatePlan, auth: GateAuthorization, lv_id: str, run_id: str, harness_root: str | Path,
                         recovery: Mapping[str, Any] | None = None) -> GateControllerAdapters:
    from .lv_remediation import review_remediation
    from .lv_review import preflight_run
    state: dict[str, Any] = {}

    def resumed(stage: str, status: str) -> dict[str, Any] | None:
        records = state.get("resume_records", [])
        matches = [item for item in records if item.get("lifecycle") == stage]
        if not matches: return None
        payload = matches[-1].get("stage_payload")
        if isinstance(payload, dict) and payload:
            restored = dict(payload)
            restored.update(exit_code=0, evidence_sha256=matches[-1]["evidence_sha256"], hard_stop=True)
            if stage == "REVIEW":
                restored["verdict_history"] = [item.get("stage_payload", {}).get("status") for item in matches
                                                if item.get("stage_payload", {}).get("status") in {"PASS", "FAIL"}]
                remediation = [item for item in records if item.get("lifecycle") == "REMEDIATION"]
                if remediation:
                    restored["remediation_verdict"] = remediation[-1].get("stage_payload", {}).get("status", "PASS")
            return restored
        return {"status": status, "exit_code": 0, "evidence_sha256": matches[-1]["evidence_sha256"], "hard_stop": True}

    def sealed(stage: str, status: str, evidence: str, *, payload: Mapping[str, Any] | None = None,
               checkpoint_payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = {"status": status, "exit_code": 0, "evidence_sha256": evidence, "hard_stop": True}
        store = state.get("store")
        if isinstance(store, ResumeStore):
            store.append(stage, evidence, checkpoint=stage == "CHECKPOINT", stage_payload=payload or result,
                         checkpoint_payload=checkpoint_payload)
        return result

    def package(context: Mapping[str, Any]) -> dict[str, Any]:
        if recovery and recovery.get("classification", {}).get("completion_eligible") is False:
            from .recovery_contract import execute_recovery_attempt
            recovery_root = Path(harness_root) / "_workspace" / "global-gate" / plan.project_id / "recovery"
            attempt = int(recovery["next_attempt"]); recovery_id = recovery["recovery"]["recovery_id"]
            record_path = recovery_root / f"{recovery_id}.json"
            checkpoint_path = recovery_root / f"{recovery_id}.checkpoint.json"
            selected = next(item for item in plan.lvs if item.lv_id == lv_id)
            def registered_worker(recovery_package: Mapping[str, Any], recovery_preflight: Mapping[str, Any]) -> Mapping[str, Any]:
                from .recovery_contract import attempt_directory
                attempt_root = Path(harness_root) / "_workspace" / "orchestration-runs" / run_id / attempt_directory(attempt)
                base_package = attempt_root / "package.json"
                if base_package.is_file():
                    try:
                        if json.loads(base_package.read_text(encoding="utf-8")).get("lv_id") != lv_id:
                            attempt_root = attempt_root.parent / f"{attempt_directory(attempt)}-{lv_id}"
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        raise GateControllerError("recovery package is malformed")
                result = attempt_root / "registered.worker.result.json"
                request_path = attempt_root / "worker.request.json"
                task = TaskSlice(thread_id=lv_id, assigned_agent="implementation_agent", input=selected.purpose,
                                 expected_output="truthful recovery worker result", validation_criteria=list(selected.completion_criteria),
                                 editable_scope=list(selected.owned_files), forbidden_scope=[], merge_point="GATE_EXIT",
                                 run_id=run_id, run_root=str(attempt_root), output_dir=str(attempt_root),
                                 result_path=str(result), worker_request_path=str(request_path))
                request = WorkerRequest(project_root=str(root), task=task,
                    contract_summary={"project_id":plan.project_id,"gate_id":plan.gate_id,"lv_id":lv_id,
                                      "canonical_plan_sha256":plan.canonical_plan_sha256},
                    state_snapshot={"branch":"sealed","head":str(context.get("head", ""))},
                    extra_context={"execution_mode":"production","run_id":run_id,"run_root":str(attempt_root),
                                   "package_manifest_sha256":recovery_package["package_sha256"],
                                   "preflight_evidence_sha256":recovery_preflight["preflight_sha256"],
                                   "attempt":attempt,"gate_id":plan.gate_id,"lv_id":lv_id,
                                   "approval_event_id":recovery_package["approval_event_id"],
                                   "source_snapshot":{"source_head":str(context.get("head", ""))}})
                request_path.write_bytes(canonical_json_bytes(request.to_dict()))
                action = seal_action_manifest(requirements_sha256=str(context["requirements_sha256"]),
                    project_id=plan.project_id, gate_id=plan.gate_id, lv_id=lv_id, run_id=run_id,
                    branch=str(context["branch"]), head=str(context["head"]), owned_files=list(selected.owned_files),
                    command_id="lv.worker", input_sha256=_file_sha(request_path),
                    parameters={"request_file":str(request_path),"result_file":str(result)})
                audit_path = namespace_root(harness_root, plan.project_id, "artifact") / f"{run_id}.attempt-{attempt:02d}.runner.audit.jsonl"
                execution = run_sealed_action(action, expected_project_id=plan.project_id,
                    expected_requirements_sha256=str(context["requirements_sha256"]), audit_path=audit_path,
                    execution_root=attempt_root, timeout=1800.0)
                if execution["exit_code"] != 0 or not result.is_file() or result.is_symlink():
                    raise GateControllerError("recovery registered worker failed")
                return json.loads(result.read_text(encoding="utf-8"))
            outcome = execute_recovery_attempt(harness_root, recovery_record_path=record_path,
                                               recovery_checkpoint_path=checkpoint_path, worker=registered_worker)
            state["recovery_mode"] = True; state["recovery_control"] = (record_path, checkpoint_path)
            state["recovery_outcome"] = outcome; state["package_root"] = Path(outcome["attempt_root"])
            state["package_manifest"] = outcome["package"]
            state["package_manifest_sha256"] = outcome["package"]["package_sha256"]
            state["worker_payload"] = outcome["worker_result"]
            state["worker_result_path"] = Path(outcome["attempt_root"]) / "worker.result.json"
            return {"status":"SEALED","exit_code":0,"evidence_sha256":outcome["package"]["package_sha256"],"hard_stop":True}
        from .canonical_paths import canonical_lv_path
        package_root = canonical_lv_path(harness_root, project_id=plan.project_id, run_id=run_id,
                                         gate_id=plan.gate_id, lv_id=lv_id)
        manifest_path = package_root / "package.manifest.json"
        sidecar = package_root / "package.manifest.sha256"
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing_manifest = {}
            if existing_manifest.get("lv_id") not in {None, lv_id}:
                raise GateControllerError("STALE_NAMESPACE_SELECTION")
        if manifest_path.is_file() and sidecar.is_file() and not manifest_path.is_symlink() and not sidecar.is_symlink():
            digest = _file_sha(manifest_path)
            if sidecar.read_text(encoding="ascii").strip() != digest:
                raise GateControllerError("PACKAGE manifest drift on resume")
        else:
            value = create_lv_execution_package(
                root, plan.gate_id, lv_id, run_id,
                output_root=package_root.parent, output_dir=package_root,
                canonical_state_override=context.get("canonical_state_override"),
            )
            digest = value["manifest_sha256"]
        # Persist the package details needed by the registered worker command.
        package_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        state["package_root"] = package_root
        state["package_manifest"] = package_payload
        state["package_manifest_sha256"] = digest
        owned_hashes = {path: _file_sha(root / path) if (root / path).is_file() else hashlib.sha256(b"").hexdigest()
                        for path in next(item for item in plan.lvs if item.lv_id == lv_id).owned_files}
        if not owned_hashes: owned_hashes = {"__no_owned_files__": hashlib.sha256(b"").hexdigest()}
        binding = RunBinding(plan.project_id, plan.gate_id, lv_id, run_id,
                             str(context["requirements_sha256"]), plan.canonical_plan_sha256,
                             str(context["branch"]), str(context["head"]), digest, owned_hashes)
        store_key = lv_id
        if str(context.get("head")) != str(package_payload.get("source_head")):
            store_key = f"{lv_id}-adoption-{str(context.get('head'))[:12]}"
        store_base = Path(harness_root) / "_workspace" / "global-gate-resume" / store_key
        event_one = store_base / plan.project_id / plan.gate_id / lv_id / run_id / "events" / "000001.json"
        if event_one.is_file() and not event_one.is_symlink():
            persisted = json.loads(event_one.read_text(encoding="utf-8")).get("binding")
            if not isinstance(persisted, dict):
                raise GateControllerError("persisted run binding is malformed")
            stable = {key:value for key,value in binding.payload().items() if key != "owned_content_sha256"}
            if {key:value for key,value in persisted.items() if key != "owned_content_sha256"} != stable:
                raise GateControllerError("persisted run binding identity drift")
            binding = RunBinding(**persisted)
        store = ResumeStore(store_base, binding)
        state["store"] = store
        if context.get("resume") and store.verify():
            resumed = store.resume(binding, owned_hashes)
            state["latest_checkpoint"] = resumed["checkpoint"]
            state["resume_records"] = store.verify()
            return {"status": "SEALED", "exit_code": 0, "evidence_sha256": digest, "hard_stop": True}
        return sealed("PACKAGE", "SEALED", digest)

    def preflight(_: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            value = state["recovery_outcome"]["preflight"]
            return {"status":"READY","exit_code":0,"evidence_sha256":value["preflight_sha256"],"hard_stop":True}
        prior = resumed("PREFLIGHT", "READY")
        if prior:
            package_root = state.get("package_root")
            if isinstance(package_root, Path):
                published = preflight_run(run_id, package_root=package_root, result_path=package_root / "worker.result.json")
                if isinstance(published.get("status"), dict) and published["status"].get("status") == "READY":
                    state["preflight_evidence_sha256"] = str(published["preflight_evidence_sha256"])
            return prior
        package_root = state.get("package_root")
        manifest = state.get("package_manifest")
        if not isinstance(package_root, Path) or not isinstance(manifest, dict):
            raise GateControllerError("PREFLIGHT requires a sealed package")
        preflight_root = package_root / "preflight"
        evidence_path = preflight_root / "preflight.evidence.json"
        sidecar = preflight_root / "preflight.evidence.sha256"
        if evidence_path.is_file() and sidecar.is_file() and not evidence_path.is_symlink() and not sidecar.is_symlink():
            digest = _file_sha(evidence_path)
            if sidecar.read_text(encoding="ascii").strip() != digest:
                raise GateControllerError("PREFLIGHT evidence drift on resume")
            return sealed("PREFLIGHT", "READY", digest)
        evidence = {"schema_version": "orchestration.gate.preflight.v1", "run_id": run_id,
                    "project_id": plan.project_id, "gate_id": plan.gate_id, "lv_id": lv_id,
                    "package_manifest_sha256": state["package_manifest_sha256"],
                    "canonical_plan_sha256": plan.canonical_plan_sha256,
                    "owned_files": list(manifest.get("owned_files", [])), "status": "READY", "hard_stop": True}
        digest = _sha(canonical_json_bytes(evidence)); preflight_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(evidence_path, evidence)
        sidecar.write_text(digest, encoding="ascii")
        (preflight_root / "preflight.status").write_bytes(canonical_json_bytes({"status": "READY", "hard_stop": True, "evidence_sha256": digest}))
        # Publish the same sealed preflight through the production review
        # store so review_run consumes the canonical evidence location.
        published = preflight_run(run_id, package_root=package_root, result_path=package_root / "worker.result.json")
        if published.get("status") != "READY" and not (isinstance(published.get("status"), dict) and published["status"].get("status") == "READY"):
            raise GateControllerError(f"PREFLIGHT publication failed: {published}")
        state["preflight_evidence_sha256"] = str(published["preflight_evidence_sha256"])
        return sealed("PREFLIGHT", "READY", state["preflight_evidence_sha256"], payload=published)

    def worker(_: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            value = state["recovery_outcome"]["worker_result"]
            return {"status":"COMPLETED","exit_code":0,"evidence_sha256":value["worker_result_sha256"],"hard_stop":True}
        package_root = state.get("package_root")
        manifest = state.get("package_manifest")
        package_sha = state.get("package_manifest_sha256")
        if not isinstance(package_root, Path) or not isinstance(manifest, dict) or not isinstance(package_sha, str):
            raise GateControllerError("WORKER request cannot be bound to sealed package")
        # Partial-workspace recovery takes precedence over replaying a stale
        # WORKER event.  Adoption is allowed only for files inside this LV's
        # sealed owned scope; the registered executor independently validates,
        # tests, commits, and collects the result.
        pending = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
                                 capture_output=True, text=True, check=True).stdout.splitlines()
        owned_scope = list(manifest.get("owned_files", []))
        partial_owned = [line[3:] for line in pending if len(line) > 3 and
                         any(line[3:] == scope or (scope.endswith("/") and line[3:].startswith(scope))
                             for scope in owned_scope)]
        if not partial_owned:
            prior = resumed("WORKER", "COMPLETED")
            if prior:
                state["worker_payload"] = {key: value for key, value in prior.items()
                                           if key not in {"exit_code", "evidence_sha256", "hard_stop"}}
                return prior
        # The worker result is a child of the sealed run package.  Never read a
        # process-global /tmp result: that would permit an unrelated process to
        # satisfy this lifecycle by merely creating a matching filename.
        result = package_root / "worker.result.json"
        if result.exists() or result.is_symlink():
            if result.is_symlink():
                raise GateControllerError("WORKER_RESULT_REQUIRED: stale worker result exists")
            try:
                existing_result = json.loads(result.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise GateControllerError("WORKER_RESULT_REQUIRED: stale worker result exists") from exc
            if (existing_result.get("project_id") != plan.project_id or existing_result.get("gate_id") != plan.gate_id
                    or existing_result.get("lv_id") != lv_id or existing_result.get("run_id") != run_id):
                raise GateControllerError("WORKER_RESULT_REQUIRED: stale worker result exists")
            result_stat = result.lstat()
            if result_stat.st_uid != os.getuid() or result_stat.st_mode & 0o022:
                successor = package_root / "worker.result.private-01.json"
                original = result.read_bytes()
                if successor.exists():
                    if not _private_worker_result_ok(successor) or successor.read_bytes() != original:
                        raise GateControllerError("WORKER_RESULT_REQUIRED: unsafe private successor")
                else:
                    fd = os.open(successor, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(original); handle.flush(); os.fsync(handle.fileno())
                    if not _private_worker_result_ok(successor):
                        raise GateControllerError("WORKER_RESULT_REQUIRED: private successor mode mismatch")
                result = successor
            state["worker_payload"] = existing_result
            state["worker_result_path"] = result
            return sealed("WORKER", "COMPLETED", _file_sha(result), payload=existing_result)
        task = TaskSlice(
            thread_id=lv_id, assigned_agent="implementation_agent",
            input=str(manifest.get("task", {}).get("purpose", "sealed LV worker")),
            expected_output="truthful worker result", validation_criteria=list(manifest.get("completion_checks", [])),
            editable_scope=list(manifest.get("owned_files", [])), forbidden_scope=[], merge_point="GATE_EXIT",
            run_id=run_id, run_root=str(package_root), task_prompt_path=str(package_root / "worker_prompt.md"),
            output_dir=str(package_root), result_path=str(result), worker_request_path=str(package_root / "worker.request.json"),
        )
        request = WorkerRequest(
            project_root=str(root), task=task,
            contract_summary={"project_id": plan.project_id, "gate_id": plan.gate_id, "lv_id": lv_id,
                              "canonical_plan_sha256": plan.canonical_plan_sha256},
            state_snapshot={"branch": "sealed", "head": str(manifest.get("source_head", ""))},
            extra_context={"execution_mode": "production", "run_id": run_id, "run_root": str(package_root),
                           "package_manifest_sha256": package_sha,
                           "preflight_evidence_sha256": state.get("preflight_evidence_sha256") or _file_sha(package_root / "preflight" / "preflight.evidence.json"),
                           "attempt": 1,
                           "source_snapshot": {key: manifest.get(key) for key in ("source_head", "source_tree", "source_index_fingerprint", "source_worktree_fingerprint")},
                    "gate_id": plan.gate_id, "lv_id": lv_id,
                    "approval_event_id": getattr(auth, "authorization_id", ""),
                           },
        )
        request_path = package_root / "worker.request.json"
        request_path.write_bytes(canonical_json_bytes(request.to_dict()))
        # Use the registered production executor for real projects.  It
        # independently validates scope/tests/commit evidence and resumes a
        # partial owned workspace without spawning a duplicate child.
        from .production_worker_executor import execute_production_worker
        if str(request.extra_context.get("execution_mode")) == "production":
            try:
                worker_payload = execute_production_worker(request, timeout=1800)
            except Exception as exc:
                raise GateControllerError(f"registered worker failed (production): {exc}") from exc
            data = canonical_json_bytes(worker_payload)
            fd = os.open(result, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            if not _private_worker_result_ok(result):
                raise GateControllerError("WORKER_RESULT_REQUIRED: private result mode mismatch")
            state["worker_payload"] = worker_payload
            state["worker_result_path"] = result
            return sealed("WORKER", "COMPLETED", _file_sha(result), payload=worker_payload)
        action = seal_action_manifest(
            requirements_sha256=str(_.get("requirements_sha256", "")), project_id=plan.project_id,
            gate_id=plan.gate_id, lv_id=lv_id, run_id=run_id, branch=str(_.get("branch", "")),
            head=str(_.get("head", "")), owned_files=list(manifest.get("owned_files", [])), command_id="lv.worker",
            input_sha256=_sha(request_path.read_bytes()),
            parameters={"request_file": str(request_path), "result_file": str(result)},
        )
        audit_path = namespace_root(harness_root, plan.project_id, "artifact") / f"{run_id}.runner.audit.jsonl"
        execution = run_sealed_action(action, expected_project_id=plan.project_id,
                                       expected_requirements_sha256=str(_.get("requirements_sha256", "")), audit_path=audit_path,
                                       execution_root=package_root, timeout=1800.0)
        if execution["exit_code"] != 0 or not result.is_file() or result.is_symlink():
            raise GateControllerError("WORKER_RESULT_REQUIRED: registered worker failed or produced no result")
        try: worker_payload = json.loads(result.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc: raise GateControllerError("sealed worker result is malformed") from exc
        if not isinstance(worker_payload, dict) or not isinstance(worker_payload.get("changed_files"), list) or not isinstance(worker_payload.get("tests"), list):
            raise GateControllerError("worker result lacks truthful changed-files/tests evidence")
        state["worker_payload"] = worker_payload
        state["worker_result_path"] = result
        return sealed("WORKER", "COMPLETED", _file_sha(result), payload=worker_payload)

    def review(context: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            from .recovery_contract import review_recovery_attempt
            record_path, checkpoint_path = state["recovery_control"]
            reviewed = review_recovery_attempt(harness_root, recovery_record_path=record_path,
                recovery_checkpoint_path=checkpoint_path,
                reviewer=lambda worker, binding: {"verdict":"PASS" if worker.get("status") == "completed" and worker.get("tests") else "FAIL",
                                                   "findings":[]})
            value = reviewed["review"]; state["review_payload"] = value
            if value["verdict"] == "PASS":
                from .production_completion import verify_product_completion
                evidence = dict(state["recovery_outcome"]["worker_result"])
                evidence["review_verdict"] = "PASS"
                contract = {"project_id":plan.project_id,"gate_id":plan.gate_id,"lv_id":lv_id,"run_id":run_id,
                            "approval_event_id":evidence.get("approval_event_id"),"plan_sha256":plan.canonical_plan_sha256,
                            "owned_files":list(next(item for item in plan.lvs if item.lv_id == lv_id).owned_files)}
                verdict = verify_product_completion(root, evidence, contract)
                if verdict["status"] != "PASS":
                    raise GateControllerError(f"product completion verification failed: {verdict['reasons']}")
                evidence["product_verdict_sha256"] = hashlib.sha256(canonical_json_bytes(verdict)).hexdigest()
                _atomic_json(Path(state["recovery_outcome"]["attempt_root"]) / "product-completion.json", evidence)
            return {"status":value["verdict"],"exit_code":0,"evidence_sha256":value["review_sha256"],"hard_stop":True}
        prior = resumed("REVIEW", "PASS")
        if prior:
            state["review_payload"] = {key: value for key, value in prior.items()
                                       if key not in {"exit_code", "evidence_sha256", "hard_stop", "verdict_history", "remediation_verdict"}}
            return prior
        worker_payload = state.get("worker_payload")
        if not isinstance(worker_payload, dict) or worker_payload.get("status") != "completed":
            raise GateControllerError("REVIEW requires a completed registered worker result")
        if not isinstance(worker_payload.get("tests"), list) or not worker_payload["tests"]:
            raise GateControllerError("REVIEW blocked: worker test evidence is absent")
        from .lv_review import resolve_derived_preflight_publication
        package_root = Path(state["package_root"])
        manifest = state["package_manifest"]
        transition = manifest.get("production_transition")
        requested_review_attempt = int(context.get("review_attempt", 1))
        review_request = {
            "schema_version": "orchestration.production.review-request.v1",
            "run_id": run_id, "project_id": plan.project_id, "gate_id": plan.gate_id, "lv_id": lv_id,
            "review_attempt": requested_review_attempt, "package_manifest_sha256": state["package_manifest_sha256"],
            "worker_result_sha256": _file_sha(Path(state["worker_result_path"])),
            "canonical_plan_sha256": plan.canonical_plan_sha256,
            "approval_id": manifest.get("approval_id"), "approval_record_hash": manifest.get("approval_record_hash"),
            "production_transition_sha256": _sha(canonical_json_bytes(transition)) if isinstance(transition, dict) else "",
            "predecessor_completion_digest": transition.get("predecessor_completion_digest", "") if isinstance(transition, dict) else "",
        }
        review_request_path = package_root / f"production.review-request-{requested_review_attempt:02d}.json"
        if review_request_path.exists() or review_request_path.is_symlink():
            if review_request_path.is_symlink() or review_request_path.read_bytes() != canonical_json_bytes(review_request):
                raise GateControllerError("REVIEW request replay conflict")
        else:
            _atomic_json(review_request_path, review_request)
        publication = resolve_derived_preflight_publication(
            run_id, package_root=Path(state["package_root"]),
            source_root=Path(state["package_root"]) / "preflight",
            result_path=Path(state["worker_result_path"]),
            review_request_path=review_request_path,
        )
        if publication.get("status") != "READY":
            raise GateControllerError(f"REVIEW preflight publication blocked: {publication}")
        review_attempt = int(context.get("review_attempt", 1))
        review_root = Path(state["package_root"]) / f"review-attempt-{review_attempt:02d}"
        # A prior failed review is immutable; publish a successor review
        # record instead of attempting to overwrite or rerun the worker.
        while review_root.exists() or review_root.is_symlink():
            review_attempt += 1
            review_root = Path(state["package_root"]) / f"review-attempt-{review_attempt:02d}"
        review_result = review_run(
            run_id, attempt=review_attempt,
            package_root=Path(state["package_root"]),
            result_path=Path(state["worker_result_path"]), results_root=review_root,
        )
        if review_result.get("status") not in {"PASS", "FAIL"}:
            raise GateControllerError(f"REVIEW blocked: {review_result}")
        value = {"status": review_result["status"], "run_id": run_id,
                 "review_attempt": int(context.get("review_attempt", 1)),
                 "worker_result_sha256": _file_sha(Path(state["worker_result_path"])),
                 "review_report_sha256": review_result.get("reviewer_report_sha256", ""),
                 "checks": review_result.get("independent_checks", []), "hard_stop": True}
        digest = _canonical_hash(value)
        state["review_payload"] = value
        if value["status"] != "PASS":
            raise GateControllerError(f"REVIEW verdict is FAIL: {review_result}")
        return sealed("REVIEW", value["status"], digest, payload=value)

    def remediation(_: Mapping[str, Any]) -> dict[str, Any]:
        remediation_run = f"{run_id}-remediation"
        value = review_remediation(remediation_run)
        if value.get("status") != "PASS": raise GateControllerError(f"REMEDIATION blocked: {value.get('reason', 'sealed remediation artifacts required')}")
        digest = value.get("reviewer_report_sha256") or hashlib.sha256(canonical_json_bytes(value)).hexdigest()
        return sealed("REMEDIATION", "PASS", digest, payload=value)

    def checkpoint(context: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            from .recovery_contract import finalize_recovery_lifecycle
            remaining = [item.lv_id for item in plan.lvs if item.order > next(x.order for x in plan.lvs if x.lv_id == lv_id)]
            final = finalize_recovery_lifecycle(harness_root, run_id=run_id, attempt=int(state["recovery_outcome"]["package"]["attempt"]), remaining_lvs=remaining, gate_complete=not remaining)
            state["recovery_final"] = final
            value = final["checkpoint"]
            return {"status":"CHECKPOINTED","exit_code":0,"evidence_sha256":value["lifecycle_checkpoint_sha256"],"hard_stop":True}
        prior = resumed("CHECKPOINT", "CHECKPOINTED")
        if prior: return prior
        digest = hashlib.sha256(canonical_json_bytes({"stage": "CHECKPOINT", "prior": context.get("prior_evidence")})).hexdigest()
        checkpoint_payload = {"lv_id": lv_id, "run_id": run_id, "prior_evidence": dict(context.get("prior_evidence") or {})}
        value = sealed("CHECKPOINT", "CHECKPOINTED", digest, checkpoint_payload=checkpoint_payload)
        store = state.get("store")
        if not isinstance(store, ResumeStore) or not store.verify()[-1]["checkpoint"]:
            raise GateControllerError("persistent checkpoint validation failed")
        state["latest_checkpoint"] = store.verify()[-1]
        return value

    def exit_stage(context: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            value = state["recovery_final"]["lv_exit"]
            return {"status":"EXITED","exit_code":0,"evidence_sha256":value["lv_exit_sha256"],"hard_stop":True}
        prior = resumed("EXIT", "EXITED")
        if prior: return prior
        checkpoint_record = state.get("latest_checkpoint")
        store = state.get("store")
        if not isinstance(store, ResumeStore) or not isinstance(checkpoint_record, dict):
            raise GateControllerError("Exit requires a verified persistent checkpoint")
        verified = store.verify()
        if not verified or checkpoint_record.get("event_sha256") not in {item.get("event_sha256") for item in verified if item.get("checkpoint")}:
            raise GateControllerError("Exit checkpoint evidence mismatch")
        digest = hashlib.sha256(canonical_json_bytes({"stage": "EXIT", "prior": context.get("prior_evidence")})).hexdigest()
        return sealed("EXIT", "EXITED", digest)

    def handoff(context: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("recovery_mode"):
            value = state["recovery_final"]["handoff"]
            return {"status":"SEALED","exit_code":0,"evidence_sha256":value["handoff_sha256"],"hard_stop":True}
        prior_handoff = resumed("HANDOFF", "SEALED")
        if prior_handoff:
            target = namespace_root(harness_root, plan.project_id, "artifact") / f"{run_id}.handoff.json"
            stored = json.loads(target.read_text(encoding="utf-8")); validate_handoff(stored, plan, auth)
            return prior_handoff
        prior = context.get("prior_evidence") or {}
        worker_payload = state.get("worker_payload")
        review_payload = state.get("review_payload")
        if not isinstance(worker_payload, dict) or not isinstance(review_payload, dict):
            raise GateControllerError("truthful worker/review handoff evidence is unavailable")
        changed = worker_payload.get("changed_files")
        tests = worker_payload.get("tests")
        if not isinstance(changed, list) or not isinstance(tests, list) or not tests:
            raise GateControllerError("truthful changed-files/tests handoff evidence is incomplete")
        routed = route_assets(
            [AssetManifest("harness-runtime", "global", frozenset({"gate-lifecycle"}),
                           frozenset({"execute-approved-lv"}), tuple(auth.owned_files_by_lv[lv_id]))],
            capabilities={"gate-lifecycle"}, permissions={"execute-approved-lv"}, owned_files=changed,
        )
        if routed["selected"] != ["harness-runtime"] or routed["substring_matching_used"] is not False:
            raise GateControllerError("exact asset routing did not authorize handoff evidence")
        recovery = {"payload": state.get("latest_checkpoint"), "sha256": hashlib.sha256(canonical_json_bytes(state.get("latest_checkpoint"))).hexdigest()}
        payload = structured_handoff(
            plan, auth, lv_id=lv_id, run_id=run_id, branch=str(context["branch"]), head=str(context["head"]),
            completed_plan_items=list(context.get("completed_plan_items", [])) + [lv_id],
            remaining_plan_items=list(context.get("remaining_plan_items", [])), changed_files=changed,
            tests=tests, review=review_payload,
            artifact_sha256=str(prior.get("worker", prior.get("package", ""))),
            used_assets=routed["selected"], recovery=recovery,
        )
        validate_handoff(payload, plan, auth)
        digest = payload["handoff_sha256"]
        target = namespace_root(harness_root, plan.project_id, "artifact") / f"{run_id}.handoff.json"
        _atomic_json(target, payload)
        stored = json.loads(target.read_text(encoding="utf-8"))
        validate_handoff(stored, plan, auth)
        return sealed("HANDOFF", "SEALED", digest)
    return GateControllerAdapters(package, preflight, worker, review, remediation,
                                  checkpoint, exit_stage, handoff)


def execute_gate(project_root: str | Path, gate_id: str, run_id: str, *, harness_root: str | Path,
                 approval_evidence: str | Path, requirements_sha256: str,
                 branch: str, head: str, mode: str = GATE_BY_GATE, resume: bool = False,
                 adapters: GateControllerAdapters | None = None,
                 requirement_evidence: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Execute a complete LV lifecycle; incomplete worker handoffs are never success."""
    root, _ = _safe_project(project_root)
    plan = load_gate_plan(root, gate_id)
    validate_global_gate_bindings(root, gate_id, requirements_sha256=requirements_sha256,
                                  approval_evidence=approval_evidence, branch=branch, head=head,
                                  harness_root=harness_root)
    auth = load_approved_authorization(root, gate_id, mode=mode)
    completed: list[str] = []
    completed_evidence: dict[str, str] = {}
    if resume:
        gap_found = False
        for index, item in enumerate(plan.lvs):
            prior_run = run_id if index == 0 else f"{run_id}-{item.lv_id.lower()}"
            handoff_path = namespace_root(harness_root, plan.project_id, "artifact") / f"{prior_run}.handoff.json"
            if not handoff_path.exists():
                gap_found = True
                continue
            if gap_found: raise GateOrchestrationError("resume handoff order mismatch")
            if not handoff_path.is_file() or handoff_path.is_symlink(): raise GateOrchestrationError("resume handoff is unsafe")
            handoff = json.loads(handoff_path.read_text(encoding="utf-8")); validate_handoff(handoff, plan, auth)
            if handoff.get("lv") != item.lv_id or handoff.get("run_id") != prior_run: raise GateOrchestrationError("resume handoff order mismatch")
            completed.append(item.lv_id)
            digest = handoff.get("handoff_sha256")
            if digest is None:
                digest = hashlib.sha256(canonical_json_bytes(handoff)).hexdigest()
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise GateOrchestrationError("resume handoff evidence SHA is invalid")
            completed_evidence[item.lv_id] = digest
    state = {"run_id": run_id, "project_id": plan.project_id, "gate_id": gate_id, "current_stage": "PLAN", "completed_lvs": completed,
             "lv_id": completed[-1] if completed else None}
    lifecycles: list[dict[str, Any]] = []
    while True:
        transition = derive_transition(plan, auth, state.get("lv_id"), state["completed_lvs"])
        if transition.get("gate_exit_ready"):
            common = {"gate_id": gate_id, "lv_id": plan.lvs[-1].lv_id, "owned_files": [],
                      "selected_assets": ["registry-selected-runtime"], "excluded_assets": [],
                      "selection_rationale": "exact runtime registry capability, permission, and owned-file match", "tests": ["sealed lifecycle evidence"]}
            plan_items = [dict(common, item_id=item.lv_id, gate_id=item.gate_id, lv_id=item.lv_id, owned_files=item.owned_files,
                               tests=item.tests or ["sealed lifecycle evidence"]) for item in plan.lvs]
            requirements = {key: dict(common) for key in REQUIREMENT_IDS}
            ledger_path = namespace_root(harness_root, plan.project_id, "artifact") / f"{run_id}.completeness.json"
            if resume and not lifecycles and ledger_path.exists():
                original = ledger_path.read_bytes()
                existing = load_ledger(ledger_path)
                validate_completeness_ledger(existing["payload"], plan_items=plan_items,
                                             requirements_sha256=requirements_sha256,
                                             plan_sha256=plan.canonical_plan_sha256, require_exit=True)
                if ledger_path.read_bytes() != original:
                    raise GateOrchestrationError("immutable completeness ledger changed during resume")
                return {"status": "GATE_EXIT", "transition": transition, "lifecycles": [], "resume_noop": True,
                        "next": gate_exit_action(auth, None), "state": state,
                        "ledger_sha256": existing["ledger_sha256"], "hard_stop": True}
            if requirement_evidence is None:
                raise GateOrchestrationError("sealed requirement contract is required")
            project_profile = set(requirement_evidence) != set(REQUIREMENT_IDS)
            if project_profile:
                # Project requirements are plan-owned items; engine R01-R25
                # conformance remains a separate prerequisite and is never
                # copied into this ledger.
                if not lifecycles:
                    raise GateOrchestrationError("project requirement lifecycle evidence is missing")
                lifecycle = lifecycles[-1]
                if lifecycle.get("status") != "SYSTEM_TRANSITION" or any(v != "PASS" for v in lifecycle.get("review_verdicts", [])):
                    raise GateOrchestrationError("project requirement lifecycle is incomplete")
                project_items = {}
                for requirement_id, contract_item in requirement_evidence.items():
                    if not isinstance(contract_item, Mapping) or contract_item.get("status") != "PENDING":
                        raise GateOrchestrationError("project requirement contract must begin PENDING")
                    worker_sha = str(lifecycle.get("evidence", {}).get("worker", ""))
                    review_sha = str(lifecycle.get("evidence", {}).get("review", ""))
                    if not re.fullmatch(r"[0-9a-f]{64}", worker_sha) or not re.fullmatch(r"[0-9a-f]{64}", review_sha):
                        raise GateOrchestrationError("project worker/review evidence is missing")
                    project_items[requirement_id] = {**dict(contract_item), "status": "COMPLETE", "verdict": "PASS",
                        "implementation_evidence_sha256": worker_sha, "review_evidence_sha256": review_sha,
                        "evidence_sha256": _canonical_hash({"requirement_id": requirement_id, "worker": worker_sha, "review": review_sha})}
                return {"status": "GATE_EXIT", "transition": transition, "lifecycles": lifecycles,
                        "project_requirements": project_items, "engine_conformance": {"requirements_sha256": requirements_sha256},
                        "next": gate_exit_action(auth, None), "state": state, "hard_stop": True}
            if set(requirement_evidence) != set(REQUIREMENT_IDS):
                raise GateOrchestrationError("exact R01-R25 requirement evidence mapping is required")
            evidence_by_lv = dict(completed_evidence)
            for lifecycle in lifecycles:
                lifecycle_lv = lifecycle.get("lv_id")
                if lifecycle_lv not in {item.lv_id for item in plan.lvs} or lifecycle_lv in evidence_by_lv:
                    raise GateOrchestrationError("lifecycle evidence LV identity is missing, duplicated, or reordered")
                evidence_by_lv[str(lifecycle_lv)] = str(lifecycle["evidence"].get("handoff", ""))
            if list(evidence_by_lv) != [item.lv_id for item in plan.lvs]:
                raise GateOrchestrationError("lifecycle evidence LV order mismatch")
            required_fields = {"implementation_ref", "implementation_sha256", "test_ref", "test_sha256",
                               "selected_assets", "excluded_assets", "selection_rationale", "gate_id", "lv_id",
                               "owned_files", "tests", "artifact_sha256", "lv_evidence_sha256",
                               "checkpoint_ref", "exit_ref", "handoff_ref"}
            seen_artifacts: set[str] = set()
            seen_refs: set[str] = set()
            validated_requirements: dict[str, dict[str, str]] = {}
            harness = Path(harness_root).resolve()
            for requirement_id in REQUIREMENT_IDS:
                item = dict(requirement_evidence[requirement_id])
                if not required_fields.issubset(item):
                    raise GateOrchestrationError(f"{requirement_id} evidence field mismatch")
                digest = item["artifact_sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest == hashlib.sha256(requirement_id.encode("ascii")).hexdigest():
                    raise GateOrchestrationError(f"{requirement_id} evidence is generic or has invalid SHA")
                if not isinstance(item["selected_assets"], list) or not item["selected_assets"] or any(not isinstance(asset, str) or not asset for asset in item["selected_assets"]):
                    raise GateOrchestrationError(f"{requirement_id} selected asset evidence is invalid")
                if not isinstance(item["excluded_assets"], list) or not item["selection_rationale"] or not isinstance(item["owned_files"], list) or not isinstance(item["tests"], list) or not item["tests"]:
                    raise GateOrchestrationError(f"{requirement_id} ledger metadata is incomplete")
                if item["gate_id"] != gate_id or item["lv_id"] not in {entry.lv_id for entry in plan.lvs}:
                    raise GateOrchestrationError(f"{requirement_id} Gate/LV metadata mismatch")
                expected_lv = item["lv_id"]
                if {"semantic_metadata", "semantic_sha256", "project_id", "canonical_plan_sha256"}.issubset(item):
                    validate_requirement_semantic_binding(item, requirement_id=requirement_id, project_id=plan.project_id,
                        gate_id=gate_id, lv_id=expected_lv, canonical_plan_sha256=plan.canonical_plan_sha256)
                for evidence_type in ("implementation_evidence", "test_evidence", "review_evidence"):
                    evidence_value = item.get(evidence_type)
                    if evidence_value:
                        if not isinstance(evidence_value, Mapping):
                            raise GateOrchestrationError(f"{requirement_id} {evidence_type} schema is invalid")
                        validate_evidence_binding(evidence_value, requirement_id=requirement_id,
                            project_id=plan.project_id, gate_id=gate_id, lv_id=expected_lv,
                            canonical_plan_sha256=plan.canonical_plan_sha256,
                            lifecycle_attempt=item.get("lifecycle_attempt", 1))
                if item["lv_evidence_sha256"] not in set(evidence_by_lv.values()):
                    raise GateOrchestrationError(f"{requirement_id} LV evidence binding mismatch")
                refs = [item["implementation_ref"], item["test_ref"], item["checkpoint_ref"], item["exit_ref"], item["handoff_ref"]]
                if any(not ref or Path(ref).is_absolute() or ".." in PurePosixPath(ref).parts for ref in refs):
                    raise GateOrchestrationError(f"{requirement_id} evidence reference is unsafe")
                ref_paths = [harness / ref for ref in refs]
                if any(not path.is_file() or path.is_symlink() or path.resolve() != path or harness not in path.parents for path in ref_paths):
                    raise GateOrchestrationError(f"{requirement_id} sealed evidence reference is missing or unsafe")
                artifact = ref_paths[4]
                if not re.fullmatch(r"[0-9a-f]{64}", str(item["implementation_sha256"])) or _file_sha(ref_paths[0]) != item["implementation_sha256"]:
                    raise GateOrchestrationError(f"{requirement_id} implementation evidence SHA drift")
                if not re.fullmatch(r"[0-9a-f]{64}", str(item["test_sha256"])) or _file_sha(ref_paths[1]) != item["test_sha256"]:
                    raise GateOrchestrationError(f"{requirement_id} test evidence SHA drift")
                for label, reference in (("implementation", ref_paths[0]), ("test", ref_paths[1])):
                    try: marker = json.loads(reference.read_text(encoding="utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError(f"{requirement_id} {label} evidence schema is invalid") from exc
                    expected_marker = {"requirement_id": requirement_id, "lv_evidence_sha256": item["lv_evidence_sha256"], "evidence_type": label}
                    if any(marker.get(key) != value for key, value in expected_marker.items()):
                        raise GateOrchestrationError(f"{requirement_id} {label} evidence content binding mismatch")
                if _file_sha(artifact) != digest:
                    raise GateOrchestrationError(f"{requirement_id} evidence artifact SHA drift")
                try: artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError(f"{requirement_id} evidence artifact is malformed") from exc
                payload_fields = {"requirement_id", "lv_evidence_sha256", "implementation_ref", "implementation_sha256", "test_ref", "test_sha256", "selected_assets", "excluded_assets", "selection_rationale", "gate_id", "lv_id", "owned_files", "tests"}
                if not payload_fields.issubset(artifact_payload) or any(artifact_payload.get(field) != item[field] for field in payload_fields - {"requirement_id"}) or artifact_payload.get("requirement_id") != requirement_id:
                    raise GateOrchestrationError(f"{requirement_id} evidence is not bound to sealed LV evidence")
                if {"semantic_metadata", "semantic_sha256", "project_id", "canonical_plan_sha256"}.issubset(item):
                    for field in ("semantic_metadata", "semantic_sha256", "project_id", "canonical_plan_sha256"):
                        if artifact_payload.get(field) != item[field]:
                            raise GateOrchestrationError(f"{requirement_id} semantic evidence binding mismatch")
                for reference in ref_paths[2:4]:
                    try: reference_payload = json.loads(reference.read_text(encoding="utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc: raise GateOrchestrationError(f"{requirement_id} evidence reference is malformed") from exc
                    if reference_payload != artifact_payload:
                        raise GateOrchestrationError(f"{requirement_id} evidence reference binding mismatch")
                if digest in seen_artifacts or any(ref in seen_refs for ref in refs):
                    raise GateOrchestrationError("duplicate requirement evidence or reference")
                seen_artifacts.add(digest); seen_refs.update(refs); validated_requirements[requirement_id] = item
            requirements = {
                key: {"gate_id": value["gate_id"], "lv_id": value["lv_id"], "owned_files": value["owned_files"],
                      "selected_assets": value["selected_assets"], "excluded_assets": value["excluded_assets"],
                      "selection_rationale": value["selection_rationale"], "tests": value["tests"]}
                for key, value in validated_requirements.items()
            }
            if len({_canonical_hash(value) for value in requirements.values()}) != len(REQUIREMENT_IDS):
                raise GateOrchestrationError("generic common requirement ledger metadata is forbidden")
            ledger = build_ledger(project_id=plan.project_id, requirements_sha256=requirements_sha256,
                                  plan_sha256=plan.canonical_plan_sha256, plan_items=plan_items, requirements=requirements)
            for row in ledger["payload"]["items"]:
                if row["item_kind"] == "REQUIREMENT":
                    requirement_id = str(row["item_id"])
                    actual = validated_requirements[requirement_id]
                    evidence = actual["artifact_sha256"]
                    checkpoint_ref = actual["checkpoint_ref"]
                    exit_ref = actual["exit_ref"]
                    handoff_ref = actual["handoff_ref"]
                else:
                    evidence = evidence_by_lv.get(str(row["lv_id"]), "")
                    checkpoint_ref = f"ResumeStore:CHECKPOINT:{row['lv_id']}"
                    exit_ref = f"ResumeStore:EXIT:{row['lv_id']}"
                    handoff_ref = f"immutable-handoff:{row['lv_id']}"
                row.update(status="EXITED", evidence_sha256=evidence, checkpoint_ref=checkpoint_ref,
                           exit_ref=exit_ref, handoff_ref=handoff_ref)
            ledger["ledger_sha256"] = _canonical_hash(ledger["payload"])
            validate_completeness_ledger(ledger["payload"], plan_items=plan_items, requirements=requirements,
                                         requirements_sha256=requirements_sha256, plan_sha256=plan.canonical_plan_sha256, require_exit=True)
            save_ledger(ledger_path, ledger)
            loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
            if loaded != ledger: raise GateOrchestrationError("immutable Gate Exit ledger drift")
            return {"status": "GATE_EXIT", "transition": transition, "lifecycles": lifecycles,
                    "resume_noop": bool(resume and not lifecycles),
                    "next": gate_exit_action(auth, None), "state": state, "ledger_sha256": ledger["ledger_sha256"], "hard_stop": True}
        lv_id = transition["to_lv"]
        lv_index = [item.lv_id for item in plan.lvs].index(lv_id)
        lv_run_id = run_id if lv_index == 0 else f"{run_id}-{lv_id.lower()}"
        context = {"project_id": plan.project_id, "gate_id": gate_id, "lv_id": lv_id, "run_id": lv_run_id,
                   "plan_sha256": plan.canonical_plan_sha256, "requirements_sha256": requirements_sha256,
                   "branch": branch, "head": head, "resume": resume,
                   "completed_plan_items": list(state["completed_lvs"]),
                   "remaining_plan_items": [item.lv_id for item in plan.lvs[lv_index + 1:]]}
        lifecycle = run_gate_lifecycle(context, adapters or _production_adapters(root, plan, auth, lv_id, lv_run_id, harness_root))
        lifecycles.append(lifecycle); state["completed_lvs"].append(lv_id); state["lv_id"] = lv_id

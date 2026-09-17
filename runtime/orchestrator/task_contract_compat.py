from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

_TASK_HEADING = re.compile(r"(?m)^##\s+(TASK-\d{3})\b(?:\s+—\s*(.*?))?\s*$")
_GATE_HEADING = re.compile(r"(?m)^##\s+(GATE-\d{3})\b.*$")
_CT_ROW = re.compile(r"(?m)^\|\s*(CT-\d{3})\s*\|\s*`([^`]+)`\s*\|[^\n]*$")
_DEP_ROW = re.compile(r"(?m)^\|\s*(TASK-\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")
_PROJECTION_SCHEMA = "orchestration.task-lv-authority-projection.v1"
_PROJECTION_POLICY = {
    "lv_identity": "TASK_ID",
    "gate_membership": "CANONICAL_GATE_REQUIRED_TASKS",
    "dependencies": "CANONICAL_TASK_DEPENDENCIES",
    "execution": "CANONICAL_TASK_DEPENDENCY_TYPE",
    "completion_criteria": "CANONICAL_TASK_COMPLETION_CONDITION_PLUS_VALIDATION",
    "provider_capabilities": "CANONICAL_TASK_REQUIRED_CAPABILITIES",
    "operational_capability": "DECLARED_NONE",
}


class TaskContractProjectionError(ValueError):
    pass


def _section_map(text: str, pattern: re.Pattern[str]) -> dict[str, str]:
    matches = list(pattern.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.start():end]
    return sections


def _field(section: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.*?)\s*$", section)
    return match.group(1).strip() if match else None


def _ids(value: str | None, prefix: str) -> list[str]:
    if not value or value.upper() in {"NONE", "N/A"}:
        return []
    return [item.strip() for item in value.split(",") if item.strip().startswith(prefix)]


def _task_titles(text: str) -> dict[str, str]:
    return {match.group(1): (match.group(2) or match.group(1)).strip() for match in _TASK_HEADING.finditer(text)}


def _change_target_sources(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in _CT_ROW.finditer(text):
        target_id, expression = match.group(1), match.group(2).strip()
        if target_id in values and values[target_id] != expression:
            raise TaskContractProjectionError(f"duplicate Change Target definition: {target_id}")
        values[target_id] = expression
    return values


def _dependency_types(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in _DEP_ROW.finditer(text):
        task_id, dependency_type = match.group(1), match.group(2).strip()
        if task_id in values and values[task_id] != dependency_type:
            raise TaskContractProjectionError(f"duplicate TASK dependency type: {task_id}")
        values[task_id] = dependency_type
    return values


def _safe_owned_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise TaskContractProjectionError("projection owned_files must contain non-empty POSIX paths")
    normalized = value.rstrip("/")
    if not normalized:
        raise TaskContractProjectionError(f"unsafe projection owned path: {value}")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or pure.as_posix() != normalized or ".." in pure.parts or any(not part for part in pure.parts):
        raise TaskContractProjectionError(f"unsafe projection owned path: {value}")
    return normalized + "/" if value.endswith("/") else normalized


def analyze_task_stage_gate_contract(text: str, requested_gate_id: str) -> dict[str, Any] | None:
    tasks_raw = _section_map(text, _TASK_HEADING)
    gates_raw = _section_map(text, _GATE_HEADING)
    if not tasks_raw or not gates_raw:
        return None

    tasks: dict[str, dict[str, Any]] = {}
    for task_id, section in tasks_raw.items():
        tasks[task_id] = {
            "dependencies": _ids(_field(section, "Dependencies"), "TASK-"),
            "required_capabilities": [
                item.strip() for item in (_field(section, "Required Capabilities") or "").split(",") if item.strip()
            ],
            "change_targets": _ids(_field(section, "Change Targets"), "CT-"),
        }

    gates: dict[str, list[str]] = {}
    for gate_id, section in gates_raw.items():
        gates[gate_id] = _ids(_field(section, "Required Tasks"), "TASK-")

    blockers: list[str] = []
    if requested_gate_id not in gates:
        blockers.append(f"requested Stage Gate is absent: {requested_gate_id}")

    unknown_required: list[dict[str, str]] = []
    unknown_dependencies: list[dict[str, str]] = []
    appearances: dict[str, list[str]] = {}
    for gate_id, required in gates.items():
        for task_id in required:
            appearances.setdefault(task_id, []).append(gate_id)
            if task_id not in tasks:
                unknown_required.append({"gate_id": gate_id, "task_id": task_id})
    for task_id, task in tasks.items():
        for dependency in task["dependencies"]:
            if dependency not in tasks:
                unknown_dependencies.append({"task_id": task_id, "dependency": dependency})

    duplicate_bindings = {task_id: gate_ids for task_id, gate_ids in appearances.items() if len(gate_ids) > 1}
    if unknown_required:
        blockers.append("Stage Gate references undefined TASK IDs")
    if unknown_dependencies:
        blockers.append("TASK dependency references undefined TASK IDs")
    if duplicate_bindings:
        blockers.append("TASK reused across Stage Gates requires explicit execute-vs-evidence projection")

    gate_order = {gate_id: index for index, gate_id in enumerate(gates)}
    first_gate = {task_id: gate_ids[0] for task_id, gate_ids in appearances.items() if gate_ids}
    forward_dependencies: list[dict[str, str]] = []
    for gate_id, required in gates.items():
        for task_id in required:
            task = tasks.get(task_id)
            if not task:
                continue
            for dependency in task["dependencies"]:
                dependency_gate = first_gate.get(dependency)
                if dependency_gate and gate_order[dependency_gate] > gate_order[gate_id]:
                    forward_dependencies.append({
                        "gate_id": gate_id,
                        "task_id": task_id,
                        "dependency": dependency,
                        "dependency_gate": dependency_gate,
                    })
    if forward_dependencies:
        blockers.append("TASK depends on work first staged behind its required Stage Gate")

    unstaged_dependencies: list[dict[str, str]] = []
    for task_id, task in tasks.items():
        for dependency in task["dependencies"]:
            if dependency in tasks and dependency not in first_gate:
                unstaged_dependencies.append({"task_id": task_id, "dependency": dependency})
    if unstaged_dependencies:
        blockers.append("TASK dependency exists but is not staged by any Gate")

    dependency_cycles: list[list[str]] = []
    visiting: list[str] = []
    visited: set[str] = set()
    def walk(task_id: str) -> None:
        if task_id in visiting:
            start = visiting.index(task_id)
            cycle = visiting[start:] + [task_id]
            if cycle not in dependency_cycles:
                dependency_cycles.append(cycle)
            return
        if task_id in visited:
            return
        visiting.append(task_id)
        for dependency in tasks.get(task_id, {}).get("dependencies", []):
            if dependency in tasks:
                walk(dependency)
        visiting.pop()
        visited.add(task_id)
    for task_id in tasks:
        walk(task_id)
    if dependency_cycles:
        blockers.append("TASK dependency graph contains a cycle")

    missing_capabilities = [task_id for task_id, task in tasks.items() if not task["required_capabilities"]]
    if missing_capabilities:
        blockers.append("TASK Required Capabilities are missing")

    return {
        "schema_version": "orchestration.task-stage-gate-analysis.v1",
        "contract_shape": "TASK_STAGE_GATE",
        "requested_gate_id": requested_gate_id,
        "task_count": len(tasks),
        "gate_count": len(gates),
        "requested_gate_tasks": list(gates.get(requested_gate_id, [])),
        "blockers": blockers,
        "duplicate_task_bindings": duplicate_bindings,
        "forward_dependency_violations": forward_dependencies,
        "unknown_required_tasks": unknown_required,
        "unknown_dependencies": unknown_dependencies,
        "unstaged_dependencies": unstaged_dependencies,
        "dependency_cycles": dependency_cycles,
        "missing_required_capabilities": missing_capabilities,
        "runtime_projection_ready": not blockers,
    }


def validate_task_lv_authority_projection(
    text: str,
    projection: Mapping[str, Any],
    *,
    project_id: str,
    canonical_plan_sha256: str,
) -> dict[str, Any]:
    required_fields = {
        "schema_version", "project_id", "canonical_plan_sha256", "contract_shape",
        "projection_policy", "change_targets",
    }
    if not isinstance(projection, Mapping) or set(projection) != required_fields:
        raise TaskContractProjectionError("TASK-to-LV projection field set mismatch")
    if projection.get("schema_version") != _PROJECTION_SCHEMA:
        raise TaskContractProjectionError("TASK-to-LV projection schema is unsupported")
    if projection.get("project_id") != project_id:
        raise TaskContractProjectionError("TASK-to-LV projection project binding mismatch")
    if projection.get("canonical_plan_sha256") != canonical_plan_sha256:
        raise TaskContractProjectionError("TASK-to-LV projection canonical plan SHA mismatch")
    if projection.get("contract_shape") != "TASK_STAGE_GATE":
        raise TaskContractProjectionError("TASK-to-LV projection contract shape mismatch")
    if projection.get("projection_policy") != _PROJECTION_POLICY:
        raise TaskContractProjectionError("TASK-to-LV projection policy mismatch")

    analysis = analyze_task_stage_gate_contract(text, next(iter(_section_map(text, _GATE_HEADING)), ""))
    if analysis is None or analysis["blockers"]:
        raise TaskContractProjectionError("canonical TASK contract is not projection-ready")

    canonical_targets = _change_target_sources(text)
    projected_targets = projection.get("change_targets")
    if not isinstance(projected_targets, Mapping) or set(projected_targets) != set(canonical_targets):
        raise TaskContractProjectionError("TASK-to-LV projection Change Target set mismatch")
    normalized: dict[str, dict[str, Any]] = {}
    for target_id, source_expression in canonical_targets.items():
        item = projected_targets.get(target_id)
        if not isinstance(item, Mapping) or set(item) != {"source_expression", "owned_files"}:
            raise TaskContractProjectionError(f"projection Change Target entry is malformed: {target_id}")
        if item.get("source_expression") != source_expression:
            raise TaskContractProjectionError(f"projection Change Target source drift: {target_id}")
        owned = item.get("owned_files")
        if not isinstance(owned, list) or not owned:
            raise TaskContractProjectionError(f"projection Change Target owned_files missing: {target_id}")
        safe = [_safe_owned_path(value) for value in owned]
        if len(safe) != len(set(safe)):
            raise TaskContractProjectionError(f"projection Change Target owned_files duplicated: {target_id}")
        normalized[target_id] = {"source_expression": source_expression, "owned_files": safe}

    return {"analysis": analysis, "change_targets": normalized}


def resolve_task_lv_projection(
    text: str,
    projection: Mapping[str, Any],
    *,
    project_id: str,
    canonical_plan_sha256: str,
    gate_id: str,
) -> list[dict[str, Any]]:
    validated = validate_task_lv_authority_projection(
        text, projection, project_id=project_id, canonical_plan_sha256=canonical_plan_sha256
    )
    analysis = analyze_task_stage_gate_contract(text, gate_id)
    if analysis is None or analysis["blockers"]:
        raise TaskContractProjectionError(compatibility_block_reason(analysis or {"blockers": ["not a TASK contract"]}))
    tasks_raw = _section_map(text, _TASK_HEADING)
    titles = _task_titles(text)
    dependency_types = _dependency_types(text)
    targets = validated["change_targets"]
    resolved: list[dict[str, Any]] = []
    for task_id in analysis["requested_gate_tasks"]:
        section = tasks_raw.get(task_id)
        if section is None:
            raise TaskContractProjectionError(f"projected TASK is missing: {task_id}")
        dependency_type = dependency_types.get(task_id)
        if not dependency_type:
            raise TaskContractProjectionError(f"TASK dependency type is missing: {task_id}")
        change_target_ids = _ids(_field(section, "Change Targets"), "CT-")
        if not change_target_ids:
            raise TaskContractProjectionError(f"TASK Change Targets are missing: {task_id}")
        owned_files: list[str] = []
        for target_id in change_target_ids:
            if target_id not in targets:
                raise TaskContractProjectionError(f"TASK references unprojected Change Target: {task_id}/{target_id}")
            for path in targets[target_id]["owned_files"]:
                if path not in owned_files:
                    owned_files.append(path)
        validation_ids = _ids(_field(section, "Validation"), "TEST-")
        completion = _field(section, "Completion Condition")
        purpose = _field(section, "Purpose") or titles[task_id]
        capabilities = [item.strip() for item in (_field(section, "Required Capabilities") or "").split(",") if item.strip()]
        dependencies = _ids(_field(section, "Dependencies"), "TASK-")
        if not completion or not validation_ids or not capabilities:
            raise TaskContractProjectionError(f"TASK runtime authority fields are incomplete: {task_id}")
        resolved.append({
            "lv_id": task_id,
            "purpose": purpose,
            "dependencies": dependencies,
            "owned_files": owned_files,
            "completion_criteria": [completion, "Validation: " + ", ".join(validation_ids)],
            "execution": dependency_type,
            "tests": validation_ids,
            "required_capabilities": capabilities,
            "capability_contract": {"version": "v1", "mode": "DECLARED_NONE", "requirements": []},
        })
    return resolved


def resolve_task_project_requirement_contract(
    text: str,
    *,
    project_id: str,
    canonical_plan_sha256: str,
    gate_id: str,
    task_id: str,
    owned_files: list[str],
) -> dict[str, Any]:
    """Project a TASK's explicit Related Requirements into a deterministic execution contract."""
    tasks_raw = _section_map(text, _TASK_HEADING)
    section = tasks_raw.get(task_id)
    if section is None:
        raise TaskContractProjectionError(f"project requirement TASK is missing: {task_id}")
    analysis = analyze_task_stage_gate_contract(text, gate_id)
    if analysis is None or analysis["blockers"] or task_id not in analysis["requested_gate_tasks"]:
        raise TaskContractProjectionError(f"project requirement TASK is outside executable Gate authority: {gate_id}/{task_id}")

    related = _field(section, "Related Requirements")
    if not related:
        raise TaskContractProjectionError(f"TASK Related Requirements are missing: {task_id}")
    if "~" in related:
        raise TaskContractProjectionError(f"TASK Related Requirements must use explicit IDs: {task_id}")
    requirement_ids = re.findall(r"\b(?:REQ|NFR|SEC|OPS)-\d{3}\b", related)
    if not requirement_ids or len(requirement_ids) != len(set(requirement_ids)):
        raise TaskContractProjectionError(f"TASK Related Requirements are missing or duplicated: {task_id}")

    definitions: dict[str, dict[str, str]] = {}
    row_pattern = re.compile(r"(?m)^\|\s*((?:REQ|NFR|SEC|OPS)-\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
    for match in row_pattern.finditer(text):
        requirement_id = match.group(1)
        value = {
            "requirement_text": match.group(2).strip(),
            "acceptance_criteria": match.group(3).strip(),
            "priority": match.group(4).strip(),
        }
        if requirement_id in definitions and definitions[requirement_id] != value:
            raise TaskContractProjectionError(f"duplicate requirement definition: {requirement_id}")
        definitions[requirement_id] = value

    completion = _field(section, "Completion Condition")
    validation_ids = _ids(_field(section, "Validation"), "TEST-")
    purpose = _field(section, "Purpose")
    if not completion or not validation_ids or not purpose:
        raise TaskContractProjectionError(f"TASK execution requirement fields are incomplete: {task_id}")
    safe_owned = [_safe_owned_path(value) for value in owned_files]
    if not safe_owned or len(safe_owned) != len(set(safe_owned)):
        raise TaskContractProjectionError(f"TASK execution owned scope is missing or duplicated: {task_id}")

    requirements: dict[str, dict[str, Any]] = {}
    for requirement_id in requirement_ids:
        definition = definitions.get(requirement_id)
        if definition is None:
            raise TaskContractProjectionError(f"Related Requirement definition is missing: {requirement_id}")
        semantic_metadata = {
            "requirement_id": requirement_id,
            **definition,
            "task_id": task_id,
            "task_purpose": purpose,
            "task_completion_condition": completion,
            "validation_ids": list(validation_ids),
            "owned_files": list(safe_owned),
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(semantic_metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        requirements[requirement_id] = {
            "project_id": project_id,
            "gate_id": gate_id,
            "lv_id": task_id,
            "plan_sha256": canonical_plan_sha256,
            "canonical_plan_sha256": canonical_plan_sha256,
            "requirement_id": requirement_id,
            "status": "PENDING",
            "verdict": None,
            "semantic_metadata": semantic_metadata,
            "semantic_sha256": semantic_sha256,
            "owned_files": list(safe_owned),
            "validation_ids": list(validation_ids),
            "required_evidence_types": ["implementation", "test", "review"],
        }
    return {
        "schema_version": "orchestration.project-requirement-contract.v1",
        "requirements": requirements,
    }


def compatibility_block_reason(analysis: dict[str, Any]) -> str:
    forward = analysis.get("forward_dependency_violations") or []
    if forward:
        item = forward[0]
        return (
            "task-stage-gate dependency is not executable without contract revision: "
            f"{item['gate_id']}/{item['task_id']} depends on {item['dependency']} "
            f"first staged at later {item['dependency_gate']}"
        )
    duplicates = analysis.get("duplicate_task_bindings") or {}
    if duplicates:
        task_id = sorted(duplicates)[0]
        gate_ids = ",".join(duplicates[task_id])
        return (
            "task-based Full Plan needs an explicit execute-vs-evidence Runtime projection: "
            f"{task_id} is referenced by {gate_ids}"
        )
    blockers = analysis.get("blockers") or []
    if blockers:
        return f"task-based Full Plan compatibility blocked: {blockers[0]}"
    return (
        "task-based Full Plan contract is structurally consistent but the current Gate/LV Runtime "
        "has no approved TASK-to-LV authority projection; execution remains fail-closed"
    )

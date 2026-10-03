from __future__ import annotations

import hashlib
import json
import re
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contract_adapter import evaluate_canonical_state, load_project_mapping, sha256_file
from .read_only_inspector import inspect_read_only
from .task_contract_compat import resolve_task_lv_projection


class LVPreviewValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LVDefinition:
    gate_id: str
    lv_id: str
    purpose: str
    dependencies: list[str]
    completion_criteria: list[str]
    execution: str
    owned_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "lv_id": self.lv_id,
            "purpose": self.purpose,
            "dependencies": list(self.dependencies),
            "completion_criteria": list(self.completion_criteria),
            "execution": self.execution,
            "owned_files": list(self.owned_files),
        }


def _gate_number(gate_id: str) -> str:
    if not isinstance(gate_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", gate_id):
        raise LVPreviewValidationError(f"invalid Gate ID: {gate_id}")
    return gate_id


def _validate_lv_id(gate_id: str, lv_id: str) -> None:
    _gate_number(gate_id)
    if not isinstance(lv_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", lv_id):
        raise LVPreviewValidationError(f"invalid LV ID: {lv_id}")


def _gate_section(plan_text: str, gate_id: str) -> str:
    gate_number = _gate_number(gate_id)
    headings = list(re.finditer(r"(?m)^###\s+Gate\s+([A-Za-z0-9_-]+).*?$", plan_text))
    matches = [index for index, heading in enumerate(headings)
               if heading.group(1) == gate_number or (gate_number.startswith("GATE-") and heading.group(1) == gate_number[5:])]
    if len(matches) != 1:
        raise LVPreviewValidationError(f"canonical plan must contain exactly one section for {gate_id}")
    index = matches[0]
    start = headings[index].end()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(plan_text)
    return plan_text[start:end]


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _tables(section: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    lines = section.splitlines()
    tables: list[tuple[list[str], list[dict[str, str]]]] = []
    index = 0
    while index + 1 < len(lines):
        if not lines[index].lstrip().startswith("|") or not lines[index + 1].lstrip().startswith("|"):
            index += 1
            continue
        headers = _split_row(lines[index])
        separator = _split_row(lines[index + 1])
        if len(headers) != len(separator) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            index += 1
            continue
        rows: list[dict[str, str]] = []
        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            cells = _split_row(lines[index])
            if len(cells) != len(headers):
                raise LVPreviewValidationError("canonical plan contains a malformed LV table row")
            rows.append(dict(zip(headers, cells)))
            index += 1
        tables.append((headers, rows))
    return tables


def _validated_project_path(value: str) -> str:
    if not value or Path(value).is_absolute() or "\\" in value:
        raise LVPreviewValidationError(f"owned file must be a project-relative POSIX path: {value}")
    parts = PurePosixPath(value).parts
    if ".." in parts or any(not part for part in parts):
        raise LVPreviewValidationError(f"owned file escapes the project root: {value}")
    return value


def _approved_owned_files(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise LVPreviewValidationError("approved owned files contain duplicates")
    return [_validated_project_path(value) for value in values]


def _declared_owned_files(
    summary_row: dict[str, str],
    detail_row: dict[str, str],
    *,
    allow_empty: bool = False,
) -> list[str]:
    summary_paths = re.findall(r"`([^`]+)`", summary_row.get("대상", ""))
    detail_owned = detail_row.get("owned_files", "")
    detail_paths = re.findall(r"`([^`]+)`", detail_owned)
    declared = list(dict.fromkeys(detail_paths + summary_paths))
    if "관련 테스트" in detail_owned:
        summary_app_paths = [path for path in summary_paths if path.startswith("app/") and path.endswith(".py")]
        declared_app_paths = [path for path in declared if path.startswith("app/") and path.endswith(".py")]
        if len(summary_app_paths) == 1:
            declared.append(f"tests/test_{PurePosixPath(summary_app_paths[0]).stem}.py")
        elif len(declared_app_paths) == 1:
            declared.append(f"tests/test_{PurePosixPath(declared_app_paths[0]).stem}.py")
        elif not declared_app_paths:
            raise LVPreviewValidationError("related test ownership is ambiguous")
    if not declared and not allow_empty:
        raise LVPreviewValidationError("canonical plan does not declare owned files")
    return [_validated_project_path(value) for value in dict.fromkeys(declared)]


def parse_lv_definition(
    plan_text: str,
    gate_id: str,
    lv_id: str,
    approved_owned_files: list[str],
) -> LVDefinition:
    _validate_lv_id(gate_id, lv_id)
    section = _gate_section(plan_text, gate_id)
    summary_rows: list[dict[str, str]] = []
    detail_rows: list[dict[str, str]] = []
    for headers, rows in _tables(section):
        matches = [row for row in rows if row.get("ID") == lv_id]
        if {"ID", "작업", "완료조건"}.issubset(headers):
            summary_rows.extend(matches)
        if {"ID", "depends_on", "execution", "owned_files"}.issubset(headers):
            detail_rows.extend(matches)
    if len(summary_rows) != 1 or len(detail_rows) != 1:
        raise LVPreviewValidationError(
            f"canonical plan must define {lv_id} exactly once in both summary and execution tables"
        )

    approved = _approved_owned_files(approved_owned_files)
    declared = _declared_owned_files(summary_rows[0], detail_rows[0], allow_empty=not approved)
    if declared != approved:
        raise LVPreviewValidationError(
            f"canonical plan owned files do not match approved owned files: declared={declared}, approved={approved}"
        )

    detail = detail_rows[0]
    exit_column = next((name for name in detail if "exit_check" in name), "")
    return LVDefinition(
        gate_id=gate_id,
        lv_id=lv_id,
        purpose=summary_rows[0]["작업"],
        dependencies=[value.strip() for value in detail["depends_on"].split(",") if value.strip()],
        completion_criteria=[summary_rows[0]["완료조건"], detail.get(exit_column, "")],
        execution=detail["execution"],
        owned_files=approved,
    )


def _validate_sealed_project_authority_state(
    root: Path,
    mapping: Any,
    gate_id: str,
    lv_id: str,
    canonical_state: Mapping[str, Any],
) -> None:
    from .gate_approval import GateApprovalError, load_approval_evidence, validate_approval_evidence
    if canonical_state.get("project_id") != mapping.project_id:
        raise LVPreviewValidationError("sealed project authority project binding mismatch")
    if canonical_state.get("state") != "GATE1_RESUME_READY":
        raise LVPreviewValidationError("sealed project authority state is incomplete or malformed")
    if canonical_state.get("transition_authorized") is not True or canonical_state.get("gate_1_started") is not True:
        raise LVPreviewValidationError("sealed project authority state is incomplete or malformed")
    if canonical_state.get("gate_id") != gate_id or canonical_state.get("active_scope") != [lv_id]:
        raise LVPreviewValidationError("sealed project authority Gate/LV binding mismatch")
    approval_id = canonical_state.get("approval_id")
    record_hash = canonical_state.get("approval_record_hash")
    requirements_sha256 = canonical_state.get("requirements_sha256")
    head = canonical_state.get("head")
    branch = canonical_state.get("branch")
    checkpoint = canonical_state.get("checkpoint_commit")
    transition = canonical_state.get("transition")
    if not isinstance(approval_id, str) or not approval_id:
        raise LVPreviewValidationError("sealed project authority state is incomplete or malformed")
    if not isinstance(record_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", record_hash):
        raise LVPreviewValidationError("sealed project authority state is incomplete or malformed")
    if not isinstance(requirements_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", requirements_sha256):
        raise LVPreviewValidationError("sealed project authority requirements binding is malformed")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise LVPreviewValidationError("sealed project authority HEAD binding is malformed")
    if not isinstance(branch, str) or not branch:
        raise LVPreviewValidationError("sealed project authority branch binding is malformed")

    current_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    current_branch = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if branch != current_branch:
        raise LVPreviewValidationError("sealed project authority source binding drift")

    if transition is None:
        if checkpoint != head or head != current_head:
            raise LVPreviewValidationError("sealed project authority source binding drift")
    else:
        required_transition = {
            "schema_version", "project_id", "gate_id", "lv_id", "run_id",
            "approval_event_id", "plan_sha256", "branch", "baseline_head",
            "current_head", "predecessor_completion_digest", "owned_file_scope",
            "completion_conditions", "transition_type", "created_at", "record_hash",
        }
        if not isinstance(transition, dict) or set(transition) != required_transition:
            raise LVPreviewValidationError("sealed project authority transition binding is malformed")
        unsigned = {key: value for key, value in transition.items() if key != "record_hash"}
        digest = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if (
            transition.get("record_hash") != digest
            or transition.get("schema_version") != "orchestration.canonical-active-lv-transition.v1"
            or transition.get("transition_type") != "SYSTEM_TRANSITION"
        ):
            raise LVPreviewValidationError("sealed project authority transition binding is malformed")
        if (
            transition.get("project_id") != mapping.project_id
            or transition.get("gate_id") != gate_id
            or transition.get("lv_id") != lv_id
            or transition.get("approval_event_id") != approval_id
            or transition.get("plan_sha256") != mapping.canonical_sha256
            or transition.get("branch") != branch
            or transition.get("baseline_head") != head
            or transition.get("current_head") != current_head
            or checkpoint != current_head
            or not isinstance(transition.get("run_id"), str)
            or not transition.get("run_id")
            or not re.fullmatch(r"[0-9a-f]{64}", str(transition.get("predecessor_completion_digest") or ""))
            or transition.get("owned_file_scope") != canonical_state.get("owned_files")
        ):
            raise LVPreviewValidationError("sealed project authority transition binding drift")

    evidence_value = canonical_state.get("approval_evidence_path")
    if not isinstance(evidence_value, (str, os.PathLike)):
        raise LVPreviewValidationError("sealed project authority approval evidence path is missing")
    evidence_path = Path(evidence_value)
    if not evidence_path.is_absolute() or evidence_path.is_symlink() or not evidence_path.is_file():
        raise LVPreviewValidationError("sealed project authority approval evidence path is unsafe")
    parts = evidence_path.resolve().parts
    expected_tail = ("_workspace", "global-gate", mapping.project_id, "approval")
    if len(parts) < 5 or tuple(parts[-5:-1]) != expected_tail:
        raise LVPreviewValidationError("sealed project authority approval evidence namespace mismatch")

    projection_path = getattr(mapping, "task_lv_projection_path", None)
    projection_sha = getattr(mapping, "task_lv_projection_sha256", None)
    if (
        projection_path is None
        or projection_sha is None
        or projection_path.is_symlink()
        or not projection_path.is_file()
        or sha256_file(projection_path) != projection_sha
    ):
        raise LVPreviewValidationError("sealed project authority TASK projection binding is invalid")
    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        projected = resolve_task_lv_projection(
            mapping.canonical_source.read_text(encoding="utf-8"),
            projection,
            project_id=mapping.project_id,
            canonical_plan_sha256=mapping.canonical_sha256,
            gate_id=gate_id,
        )
        lv_order = [item["lv_id"] for item in projected]
        owned_files_by_lv = {item["lv_id"]: list(item["owned_files"]) for item in projected}
        if isinstance(transition, dict):
            projected_item = next((item for item in projected if item.get("lv_id") == lv_id), None)
            if (
                not isinstance(projected_item, dict)
                or transition.get("owned_file_scope") != list(projected_item.get("owned_files", []))
                or transition.get("completion_conditions") != list(projected_item.get("completion_criteria", []))
            ):
                raise LVPreviewValidationError("sealed project authority transition scope drift")
        envelope = load_approval_evidence(evidence_path)
        payload = validate_approval_evidence(
            envelope,
            project_id=mapping.project_id,
            gate_id=gate_id,
            requirements_sha256=requirements_sha256,
            plan_sha256=mapping.canonical_sha256,
            branch=branch,
            head=head,
            lv_order=lv_order,
            owned_files_by_lv=owned_files_by_lv,
        )
    except (GateApprovalError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise LVPreviewValidationError(f"sealed project authority approval validation failed: {exc}") from exc
    if payload.get("approval_id") != approval_id or envelope.get("record_hash") != record_hash:
        raise LVPreviewValidationError("sealed project authority approval identity mismatch")
    if canonical_state.get("owned_files") != owned_files_by_lv.get(lv_id):
        raise LVPreviewValidationError("sealed project authority owned scope mismatch")


def preview_lv_read_only(
    project_root: str | Path,
    gate_id: str,
    lv_id: str,
    *,
    canonical_state_override: Mapping[str, Any] | None = None,
    sealed_project_authority: bool = False,
) -> dict[str, Any]:
    if not gate_id:
        raise LVPreviewValidationError("gate_id is required")
    if not lv_id:
        raise LVPreviewValidationError("lv_id is required; implicit LV selection is forbidden")
    root = Path(project_root).resolve()
    mapping = load_project_mapping(root)
    if mapping is None:
        raise LVPreviewValidationError("a project contract mapping is required for LV preview")
    if sealed_project_authority and canonical_state_override is None:
        raise LVPreviewValidationError("sealed project authority requires an explicit canonical state")

    if sealed_project_authority:
        canonical_state = dict(canonical_state_override)
    else:
        inspection = inspect_read_only(root)
        canonical_state = (
            dict(canonical_state_override)
            if canonical_state_override is not None
            else evaluate_canonical_state(mapping)
        )
    state = canonical_state.get("state")
    if not isinstance(state, str) or not (state.endswith("_ACTIVE") or state == "GATE1_RESUME_READY"):
        raise LVPreviewValidationError("LV preview requires an active canonical Gate state")
    if canonical_state.get("gate_id") != gate_id:
        raise LVPreviewValidationError(f"requested Gate is not active: {gate_id}")

    active_scope = canonical_state.get("active_scope")
    if not isinstance(active_scope, list) or active_scope != [lv_id]:
        raise LVPreviewValidationError(
            f"requested LV must exactly match the single active scope: requested={lv_id}, active_scope={active_scope}"
        )
    selected_source = canonical_state.get("selected_source")
    if not isinstance(selected_source, (str, os.PathLike)):
        raise LVPreviewValidationError("selected lifecycle source is malformed")
    selected_path = Path(selected_source)
    if not selected_path.is_absolute():
        raise LVPreviewValidationError("selected lifecycle source is not absolute")
    if selected_path.is_symlink() or selected_path != mapping.canonical_source:
        raise LVPreviewValidationError("selected lifecycle source is not the canonical implementation plan")
    canonical_relative = mapping.canonical_source.relative_to(root).as_posix()
    if canonical_state.get("canonical_plan") != canonical_relative:
        raise LVPreviewValidationError("Gate State ledger canonical plan does not match the selected source")
    if canonical_state.get("plan_sha256") != mapping.canonical_sha256:
        raise LVPreviewValidationError("Gate State ledger plan hash does not match the selected source")
    if sha256_file(mapping.canonical_source) != mapping.canonical_sha256:
        raise LVPreviewValidationError("canonical implementation plan hash mismatch")

    if sealed_project_authority:
        _validate_sealed_project_authority_state(root, mapping, gate_id, lv_id, canonical_state)
        inspection = {
            "business_gate_state": {
                "namespace": "business_gate_state",
                "status": "historical_static_not_execution_authority",
                "validation": "sealed_project_gate_authority",
                "transition_authorized": False,
            },
            "business_lv_approval_state": {
                "namespace": "business_lv_gate_approval",
                "status": "historical_static_not_execution_authority",
                "validation": "sealed_project_gate_authority",
                "reused_as_runtime_approval": False,
            },
            "codex_runtime_sandbox_approval_state": {
                "namespace": "codex_runtime_sandbox_approval",
                "status": "not_requested_read_only",
                "business_approval_reused": False,
                "runtime_mutation_authorized": False,
            },
        }
    owned = canonical_state.get("owned_files")
    if not isinstance(owned, list):
        raise LVPreviewValidationError("approved owned files are missing")
    if getattr(mapping, "task_lv_projection_path", None) is not None:
        projection_path = mapping.task_lv_projection_path
        projection_sha = getattr(mapping, "task_lv_projection_sha256", None)
        if (projection_sha is None or projection_path.is_symlink() or not projection_path.is_file()
                or sha256_file(projection_path) != projection_sha):
            raise LVPreviewValidationError("TASK-to-LV authority projection is missing or SHA-mismatched")
        try:
            projection = json.loads(projection_path.read_text(encoding="utf-8"))
            projected = resolve_task_lv_projection(
                mapping.canonical_source.read_text(encoding="utf-8"), projection,
                project_id=mapping.project_id, canonical_plan_sha256=mapping.canonical_sha256, gate_id=gate_id,
            )
        except Exception as exc:
            raise LVPreviewValidationError(f"TASK-to-LV authority projection validation failed: {exc}") from exc
        matches = [item for item in projected if item["lv_id"] == lv_id]
        if len(matches) != 1:
            raise LVPreviewValidationError(f"projected TASK must resolve exactly once: {lv_id}")
        item = matches[0]
        approved = _approved_owned_files(owned)
        if item["owned_files"] != approved:
            raise LVPreviewValidationError(
                f"projected TASK owned files do not match approved owned files: projected={item['owned_files']}, approved={approved}"
            )
        definition = LVDefinition(
            gate_id=gate_id, lv_id=lv_id, purpose=item["purpose"],
            dependencies=list(item["dependencies"]), completion_criteria=list(item["completion_criteria"]),
            execution=item["execution"], owned_files=approved,
        )
    else:
        definition = parse_lv_definition(
            mapping.canonical_source.read_text(encoding="utf-8"),
            gate_id,
            lv_id,
            owned,
        )
    return {
        "inspection_mode": "read_only_preview_no_write",
        "write_operations_performed": False,
        "business_gate_state": inspection["business_gate_state"],
        "business_lv_approval_state": inspection["business_lv_approval_state"],
        "codex_runtime_sandbox_approval_state": inspection["codex_runtime_sandbox_approval_state"],
        "selected_canonical_plan": {
            "path": canonical_relative,
            "sha256": mapping.canonical_sha256,
        },
        "selected_lv": definition.to_dict(),
        "approved_owned_files": definition.owned_files,
        "execution_mode": "read-only-preview",
        "mutation_permitted": False,
    }

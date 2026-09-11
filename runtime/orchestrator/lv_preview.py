from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contract_adapter import evaluate_canonical_state, load_project_mapping, sha256_file
from .read_only_inspector import inspect_read_only


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


def _declared_owned_files(summary_row: dict[str, str], detail_row: dict[str, str]) -> list[str]:
    summary_paths = re.findall(r"`([^`]+)`", summary_row.get("대상", ""))
    detail_owned = detail_row.get("owned_files", "")
    detail_paths = re.findall(r"`([^`]+)`", detail_owned)
    declared = list(dict.fromkeys(summary_paths + detail_paths))
    if "관련 테스트" in detail_owned:
        app_paths = [path for path in declared if path.startswith("app/") and path.endswith(".py")]
        if len(app_paths) != 1:
            raise LVPreviewValidationError("related test ownership is ambiguous")
        declared.append(f"tests/test_{PurePosixPath(app_paths[0]).stem}.py")
    if not declared:
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
    declared = _declared_owned_files(summary_rows[0], detail_rows[0])
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


def preview_lv_read_only(project_root: str | Path, gate_id: str, lv_id: str, *, canonical_state_override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not gate_id:
        raise LVPreviewValidationError("gate_id is required")
    if not lv_id:
        raise LVPreviewValidationError("lv_id is required; implicit LV selection is forbidden")
    root = Path(project_root).resolve()
    mapping = load_project_mapping(root)
    if mapping is None:
        raise LVPreviewValidationError("a project contract mapping is required for LV preview")

    inspection = inspect_read_only(root)
    canonical_state = dict(canonical_state_override) if canonical_state_override is not None else evaluate_canonical_state(mapping)
    state = canonical_state.get("state")
    if not isinstance(state, str) or not state.endswith("_ACTIVE"):
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

    owned = canonical_state.get("owned_files")
    if not isinstance(owned, list):
        raise LVPreviewValidationError("approved owned files are missing")
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

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .contract_adapter import load_project_mapping, select_canonical_source, validate_mapping_sources
from .schemas import ExecutionContract, ProjectPaths

REQUIRED_FILE_KEYS = [
    "development_plan",
    "changelog",
    "app_log",
    "orchestration_state_md",
]


class ContractLoadError(FileNotFoundError):
    def __init__(self, missing_files: list[str]) -> None:
        super().__init__("Missing execution contract files: " + ", ".join(missing_files))
        self.missing_files = missing_files


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _extract_current_phase(plan_text: str, state_text: str) -> str:
    patterns = [
        r"(?im)^\s*current phase\s*:\s*(.+?)\s*$",
        r"(?im)^\s*current_phase\s*:\s*(.+?)\s*$",
        r"(?im)^\s*current phase\s*=\s*(.+?)\s*$",
        r"(?im)^\s*-?\s*현재 상태\s*:\s*(.+?)\s*$",
        r"(?im)^\s*-?\s*상태\s*:\s*(.+?)\s*$",
    ]
    for text in (state_text, plan_text):
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
    return "unknown"


def load_contract(project_root: str | Path, strict: bool = True) -> ExecutionContract:
    root = Path(project_root).resolve()
    paths = ProjectPaths.from_root(root)
    mapping = load_project_mapping(root)
    required_keys = REQUIRED_FILE_KEYS
    mapping_summary: dict[str, object] = {}
    if mapping is not None:
        source_errors = validate_mapping_sources(mapping)
        if source_errors:
            raise ContractLoadError(source_errors)
        selected_source = select_canonical_source(mapping)
        selected_paths = dict(mapping.contract_paths)
        selected_paths["development_plan"] = selected_source
        paths = replace(
            paths,
            **{key: str(value) for key, value in selected_paths.items()},
        )
        required_keys = mapping.required_contract_keys
        mapping_summary = mapping.summary(root, selected_source)
    path_map = paths.as_path_map()
    missing = [key for key in required_keys if not path_map[key].is_file()]
    if strict and missing:
        raise ContractLoadError([str(path_map[key]) for key in missing])

    development_plan_text = _read_text(path_map["development_plan"])
    changelog_text = _read_text(path_map["changelog"])
    app_log_text = _read_text(path_map["app_log"])
    orchestration_state_text = _read_text(path_map["orchestration_state_md"])
    current_phase = _extract_current_phase(development_plan_text, orchestration_state_text)

    return ExecutionContract(
        paths=paths,
        development_plan_text=development_plan_text,
        changelog_text=changelog_text,
        app_log_text=app_log_text,
        orchestration_state_text=orchestration_state_text,
        current_phase=current_phase,
        missing_files=[str(path_map[key]) for key in missing],
        contract_mapping=mapping_summary,
    )

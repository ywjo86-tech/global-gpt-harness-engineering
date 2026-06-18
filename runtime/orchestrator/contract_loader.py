from __future__ import annotations

import re
from pathlib import Path

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
    path_map = paths.as_path_map()
    missing = [key for key in REQUIRED_FILE_KEYS if not path_map[key].exists()]
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
    )


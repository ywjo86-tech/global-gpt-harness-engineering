from __future__ import annotations

import re
import subprocess
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
ENGINE_HOST_ROLE = "engine-host"
MANAGED_PROJECT_ROLE = "managed-project"
ENGINE_HOST_ANCHORS = (
    "AGENTS.md",
    "runtime/orchestrator/cli.py",
    ".agents/skills/harness/SKILL.md",
)


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

    # Engine-host state is append-only and may not carry a literal
    # ``Current phase:`` line.  In that case, use the latest explicitly
    # declared next-Gate identifier as the last known orchestration phase.
    # This remains a read-only textual fallback; it does not authorize a
    # transition or infer a new phase.
    gate_pattern = r"(?is)The next Gate is defined as\s*`([^`]+)`"
    for text in (state_text, plan_text):
        matches = list(re.finditer(gate_pattern, text))
        if matches:
            return matches[-1].group(1).strip()
    return "unknown"


def _is_engine_host(root: Path) -> bool:
    if root.name != "global-gpt-harness-engineering":
        return False
    try:
        git_root = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    if Path(git_root).resolve() != root:
        return False
    return all((root / anchor).is_file() for anchor in ENGINE_HOST_ANCHORS)


def load_contract(
    project_root: str | Path,
    strict: bool = True,
    *,
    role: str = MANAGED_PROJECT_ROLE,
) -> ExecutionContract:
    root = Path(project_root).resolve()
    if role not in {MANAGED_PROJECT_ROLE, ENGINE_HOST_ROLE}:
        raise ContractLoadError([f"unsupported contract role: {role}"])
    host_role = role == ENGINE_HOST_ROLE
    if host_role and not _is_engine_host(root):
        raise ContractLoadError(["engine-host identity or anchors are not verified"])
    paths = ProjectPaths.from_root(root)
    mapping = load_project_mapping(root)
    required_keys = ["orchestration_state_md"] if host_role else REQUIRED_FILE_KEYS
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
    missing = [key for key in REQUIRED_FILE_KEYS if not path_map[key].is_file()]
    missing_required = [key for key in required_keys if key in missing]
    if strict and missing_required:
        raise ContractLoadError([str(path_map[key]) for key in missing_required])

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

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

RUNTIME_SURFACE = (
    "poc/graphify/contracts.py",
    "poc/graphify/graphify_adapter.py",
    "poc/graphify/baseline_adapter.py",
    "poc/graphify/canonical_verifier.py",
    "poc/graphify/comparator.py",
    "poc/graphify/environment.py",
    "poc/graphify/entry_gate.py",
    "poc/graphify/baseline_guard.py",
    "poc/graphify/current_repository_boundary.py",
    "poc/graphify/source_precedence.py",
    "poc/graphify/context_assembly_boundary.py",
    "poc/graphify/phase_boundary.py",
    "poc/graphify/decision.py",
    "poc/graphify/decision_closure.py",
    "poc/graphify/handoff.py",
)
FORBIDDEN_DEPENDENCY_TOKENS = (
    "obsidian", "notion", "memory_adapter", "project_memory",
)


def _import_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def verify_memory_independence(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    violations: list[str] = []
    scanned: list[str] = []
    for rel in RUNTIME_SURFACE:
        path = root / rel
        if not path.is_file():
            violations.append(f"missing_runtime_surface:{rel}")
            continue
        scanned.append(rel)
        for module in _import_modules(path):
            lowered = module.lower()
            if any(token in lowered for token in FORBIDDEN_DEPENDENCY_TOKENS):
                violations.append(f"forbidden_memory_dependency:{rel}:{module}")
    return {
        "record_type": "MemoryIndependenceResult",
        "scanned_runtime_surface": scanned,
        "forbidden_dependency_tokens": list(FORBIDDEN_DEPENDENCY_TOKENS),
        "violations": violations,
        "obsidian_connected": False,
        "notion_connected": False,
        "memory_adapter_connected": False,
        "verified": not violations,
    }

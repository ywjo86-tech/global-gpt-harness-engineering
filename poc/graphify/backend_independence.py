from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path
from typing import Any

from .contracts import ProviderQueryRequest

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
FORBIDDEN_IMPORT_TOKENS = (
    "codex", "execution_backend", "full_mcp", "mcp_backend",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def verify_backend_independence(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    violations: list[str] = []
    scanned: list[str] = []
    for rel in RUNTIME_SURFACE:
        path = root / rel
        if not path.is_file():
            violations.append(f"missing_runtime_surface:{rel}")
            continue
        scanned.append(rel)
        for module in _imports(path):
            lowered = module.lower()
            if any(token in lowered for token in FORBIDDEN_IMPORT_TOKENS):
                violations.append(f"forbidden_backend_import:{rel}:{module}")
    request_fields = {field.name for field in fields(ProviderQueryRequest)}
    backend_fields = request_fields.intersection(
        {"backend", "backend_id", "codex_session", "mcp_session", "runtime_handle"}
    )
    if backend_fields:
        violations.append("backend_specific_request_fields:" + ",".join(sorted(backend_fields)))
    return {
        "record_type": "BackendIndependenceResult",
        "scanned_runtime_surface": scanned,
        "forbidden_import_tokens": list(FORBIDDEN_IMPORT_TOKENS),
        "backend_specific_request_fields": sorted(backend_fields),
        "violations": violations,
        "verified": not violations,
    }

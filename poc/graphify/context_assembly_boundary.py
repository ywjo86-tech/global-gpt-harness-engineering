from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterable

FORBIDDEN_PUBLIC_SYMBOL_TOKENS = (
    "memory_capture", "memory_retrieval", "memory_merge", "memory_injection",
    "context_compression", "notion_projection", "project_context_assembly",
)


def verify_context_assembly_boundary(
    project_root: str | Path,
    runtime_paths: Iterable[str],
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    violations: list[str] = []
    scanned: list[str] = []
    for rel in runtime_paths:
        path = root / rel
        if not path.is_file():
            violations.append(f"missing_runtime_path:{rel}")
            continue
        scanned.append(rel)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if any(token in lowered for token in FORBIDDEN_PUBLIC_SYMBOL_TOKENS):
                    violations.append(f"forbidden_context_symbol:{rel}:{node.name}")
    return {
        "record_type": "ContextAssemblyBoundaryResult",
        "scanned_runtime_paths": scanned,
        "violations": violations,
        "context_assembly_owned_by_graphify": False,
        "verified": not violations,
    }

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

PHASE7_FORBIDDEN = (
    "provider_scoring", "cost_optimizer", "benchmark_router",
    "automatic_multi_model_routing", "automatic_provider_fallback",
    "provider_budget_runtime",
)
PHASE8_FORBIDDEN = (
    "instruction_registry", "instruction_telemetry", "instruction_ablation",
    "instruction_reconstruction", "continuous_instruction_optimization",
    "instruction_governance_runtime",
)


def _python_identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name.lower())
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr.lower())
        elif isinstance(node, ast.alias):
            identifiers.add(node.name.lower())
    return identifiers


def _config_identifiers(path: Path) -> set[str]:
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return set()
        identifiers: set[str] = set()
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    identifiers.add(str(key).lower())
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(payload)
        return identifiers
    identifiers = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*[-]?\s*([A-Za-z0-9_.-]+)\s*:", line)
        if match:
            identifiers.add(match.group(1).lower())
    return identifiers


def verify_reserved_phase_isolation(
    project_root: str | Path,
    owned_paths: Iterable[str],
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    violations: list[str] = []
    scanned: list[str] = []
    tokens = PHASE7_FORBIDDEN + PHASE8_FORBIDDEN
    for rel in owned_paths:
        path = root / rel
        if not path.is_file() or path.suffix not in {".py", ".yaml", ".json"}:
            continue
        scanned.append(rel)
        identifiers = (
            _python_identifiers(path)
            if path.suffix == ".py"
            else _config_identifiers(path)
        )
        for token in tokens:
            if token in identifiers:
                violations.append(f"reserved_phase_capability:{rel}:{token}")
    return {
        "record_type": "ReservedPhaseIsolationResult",
        "scanned_paths": scanned,
        "phase7_violations": [v for v in violations if any(t in v for t in PHASE7_FORBIDDEN)],
        "phase8_violations": [v for v in violations if any(t in v for t in PHASE8_FORBIDDEN)],
        "violations": violations,
        "verified": not violations,
    }

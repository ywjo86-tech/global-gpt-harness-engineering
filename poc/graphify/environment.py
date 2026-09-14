from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import venv
from pathlib import Path
from typing import Any, Iterable

from .baseline_guard import EXPECTED_ABSENT_PATHS, PROTECTED_PATHS

SECRET_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*",
    "secrets.*", "credentials.*", "*.p12", "*.pfx",
)
NOISE_NAMES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "node_modules",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_secret_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


def canonical_manifest(
    project_root: str | Path,
    *,
    protected_paths: Iterable[str] = PROTECTED_PATHS,
    expected_absent_paths: Iterable[str] = EXPECTED_ABSENT_PATHS,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for rel in protected_paths:
        target = root / rel
        if not target.is_file():
            missing.append(rel)
        else:
            hashes[rel] = _sha256(target)
    expected_absent = {
        rel: not (root / rel).exists() for rel in expected_absent_paths
    }
    return {
        "protected_hashes": hashes,
        "missing_protected_paths": missing,
        "expected_absent": expected_absent,
    }


def _ignore_snapshot(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in NOISE_NAMES or _is_secret_name(name):
            ignored.add(name)
        if name == "orchestrator_runs" and Path(directory).name == "runtime":
            ignored.add(name)
    return ignored


def prepare_isolated_environment(
    project_root: str | Path,
    run_root: str | Path,
    *,
    create_venv: bool = True,
) -> dict[str, Any]:
    project = Path(project_root).resolve()
    run = Path(run_root).resolve()
    try:
        run.relative_to(project)
    except ValueError:
        pass
    else:
        raise ValueError("isolated run root must be outside canonical project")

    before = canonical_manifest(project)
    if before["missing_protected_paths"] or not all(before["expected_absent"].values()):
        raise RuntimeError("canonical protection precheck failed")

    workspace = run / "workspace"
    snapshot = workspace / "source-snapshot"
    output = workspace / "graphify-output"
    records = run / "records"
    if run.exists():
        shutil.rmtree(run)
    records.mkdir(parents=True, exist_ok=True)
    shutil.copytree(project, snapshot, ignore=_ignore_snapshot)
    output.mkdir(parents=True, exist_ok=True)
    venv_path = run / "venv"
    if create_venv:
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_path)

    after = canonical_manifest(project)
    mutation_detected = before != after
    (records / "mutation_manifest.before.json").write_text(
        json.dumps(before, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (records / "mutation_manifest.after.json").write_text(
        json.dumps(after, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    record = {
        "record_type": "GraphifyIsolatedEnvironmentRecord",
        "project_root": str(project),
        "run_root": str(run),
        "source_snapshot": str(snapshot),
        "graphify_output": str(output),
        "venv_path": str(venv_path) if create_venv else "",
        "canonical_mutation_detected": mutation_detected,
        "secret_patterns_excluded": list(SECRET_PATTERNS),
        "shared_http_allowed": False,
        "git_hook_install_allowed": False,
        "ready_for_package_installation": not mutation_detected,
    }
    (records / "environment_record.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if mutation_detected:
        raise RuntimeError("canonical protected state changed during environment preparation")
    return record

"""Read-only source qualification for CLI-Anything provenance."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .manifest import ToolImplementationError

_ALLOWED_MECHANISMS = frozenset({"REGISTRY_METADATA", "SKILL_GENERATOR_REFERENCE", "GENERATED_CLI_CONTRACT_PATTERN"})

@dataclass(frozen=True, slots=True)
class SourceQualification:
    upstream_url: str
    commit: str
    tree_sha: str
    license_name: str
    license_sha256: str
    mechanisms: tuple[str, ...]
    control_authority: str
    qualification_sha256: str


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=20)
    if completed.returncode != 0:
        raise ToolImplementationError("source qualification Git verification failed")
    return completed.stdout.strip()


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def qualify_source_checkout(checkout: str | Path, *, upstream_url: str, expected_commit: str,
                            mechanisms: Sequence[str]) -> SourceQualification:
    root = Path(checkout).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ToolImplementationError("source checkout is unsafe")
    head = _git(root, "rev-parse", "HEAD")
    if head != expected_commit:
        raise ToolImplementationError("source checkout commit mismatch")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    selected = tuple(str(x) for x in mechanisms)
    if not selected or len(set(selected)) != len(selected) or any(x not in _ALLOWED_MECHANISMS for x in selected):
        raise ToolImplementationError("source qualification mechanism is not allowlisted")
    license_path = root / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise ToolImplementationError("source license is missing")
    license_text = license_path.read_text(encoding="utf-8", errors="replace")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ToolImplementationError("source license is not the qualified Apache-2.0 license")
    unsigned = {"upstream_url": str(upstream_url), "commit": head, "tree_sha": tree,
                "license_name": "Apache-2.0", "license_sha256": hashlib.sha256(license_path.read_bytes()).hexdigest(),
                "mechanisms": list(selected), "control_authority": "NONE"}
    return SourceQualification(**unsigned, qualification_sha256=_digest(unsigned))

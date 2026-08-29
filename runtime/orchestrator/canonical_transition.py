from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


class CanonicalTransitionError(ValueError):
    pass


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
STATE_FIELDS = {
    "schema_version", "project_id", "gate_id", "phase", "plan_sha256",
    "gate_status", "closure_status", "approval_record_hash",
}
DEFAULT_GOVERNANCE_PREFIXES = (
    "AGENTS.md", "docs/", "runtime/orchestrator/contract_mappings/", ".agents/", ".codex/",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CanonicalTransitionError("Git descendant validation failed")
    return result.stdout.strip()


def validate_governance_descendant(
    project_root: str | Path, baseline_head: str, *, governance_prefixes: Iterable[str] = DEFAULT_GOVERNANCE_PREFIXES,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    current = _git(root, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", baseline_head, current],
        capture_output=True, check=False,
    )
    if ancestor.returncode != 0:
        raise CanonicalTransitionError("approval baseline is not an ancestor of current HEAD")
    changed = [line for line in _git(root, "diff", "--name-only", f"{baseline_head}..{current}").splitlines() if line]
    prefixes = tuple(governance_prefixes)
    product = [path for path in changed if not any(path == prefix or path.startswith(prefix) for prefix in prefixes)]
    if product:
        raise CanonicalTransitionError("production approval is stale after product-code descendant changes")
    return {"baseline_head": baseline_head, "current_head": current, "changed_files": changed, "governance_only": True}


def validate_canonical_gate_state(
    state: Mapping[str, Any], *, project_id: str, gate_id: str, phase: str,
    plan_sha256: str, approval_record_hash: str | None,
) -> dict[str, Any]:
    if set(state) != STATE_FIELDS or state.get("schema_version") != "orchestration.canonical-gate-state.v2":
        raise CanonicalTransitionError("canonical Gate state schema mismatch")
    expected = {
        "project_id": project_id, "gate_id": gate_id, "phase": phase,
        "plan_sha256": plan_sha256, "approval_record_hash": approval_record_hash,
    }
    for field, value in expected.items():
        if state.get(field) != value:
            raise CanonicalTransitionError(f"canonical Gate state {field} mismatch")
    if state.get("gate_status") not in {"READY_FOR_APPROVAL", "READY_FOR_TRANSITION"}:
        raise CanonicalTransitionError("canonical Gate state is not ready for approval or transition")
    if state["gate_status"] == "READY_FOR_APPROVAL" and state.get("approval_record_hash") is not None:
        raise CanonicalTransitionError("pre-approval canonical Gate state must not bind an approval hash")
    if state["gate_status"] == "READY_FOR_TRANSITION" and not _SHA256.fullmatch(str(state.get("approval_record_hash"))):
        raise CanonicalTransitionError("transition-ready canonical Gate state approval digest is invalid")
    if state.get("closure_status") != "CLOSED":
        raise CanonicalTransitionError("canonical Gate closure is missing")
    if not _SHA256.fullmatch(str(state.get("plan_sha256"))):
        raise CanonicalTransitionError("canonical Gate state digest is invalid")
    return dict(state)


def load_canonical_gate_state(path: str | Path, **expected: str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file() or source.is_symlink() or source.stat().st_size > 1024 * 1024:
        raise CanonicalTransitionError("canonical Gate state is missing or unsafe")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalTransitionError("canonical Gate state is malformed") from exc
    if not isinstance(value, dict):
        raise CanonicalTransitionError("canonical Gate state must be an object")
    return validate_canonical_gate_state(value, **expected)

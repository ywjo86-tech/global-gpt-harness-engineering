from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

HISTORICAL_GRAPHIFY_BASELINE_REF = "958d335c2d85dfbbe4ed5a45bf6d78f14bdc9c37"
DEFAULT_BASELINE_REF = "fffe93a330d59c8dd91f60abde2bf4c53cd0542e"

PROTECTED_PATHS = (
    "runtime/orchestrator/stage_gate.py",
    "runtime/orchestrator/completion_contract.py",
    "runtime/orchestrator/execution_contract.py",
    "runtime/orchestrator/worker_authority.py",
    "tests/test_worker_authority.py",
    "AGENTS.md",
    ".gitignore",
    "runtime/orchestrator/provider_router.py",
    "runtime/orchestrator/read_only_inspector.py",
    "tests/test_read_only_inspect.py",
    "runtime/orchestrator/completion_authority.py",
)

EXPECTED_ABSENT_PATHS = (".codex/hooks.json",)
PROTECTED_PREFIXES = ("runtime/orchestrator/", ".codex/")
CONTROLLED_CHANGE_SEQUENCE = (
    "Change Request",
    "Impact Analysis",
    "Controlled Change",
    "Regression Test",
    "Baseline Reconfirmation",
)

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(root: Path, relative_path: str) -> Path | None:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _git_commit_exists(root: Path, commit_sha: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _git_blob(root: Path, baseline_ref: str, relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _normalize_requested_path(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    normalized = candidate.as_posix().lstrip("./")
    return normalized or None


def _is_protected_request(relative_path: str) -> bool:
    if relative_path in PROTECTED_PATHS or relative_path in {"AGENTS.md", ".gitignore"}:
        return True
    return any(relative_path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _escalation_record(reasons: list[str], protected_requests: list[str]) -> dict[str, Any]:
    return {
        "record_type": "ControlledChangeEscalationRecord",
        "controlled_change_required": True,
        "phase2_can_execute_change": False,
        "requested_protected_paths": protected_requests,
        "reasons": reasons,
        "required_external_sequence": list(CONTROLLED_CHANGE_SEQUENCE),
        "baseline_reconfirmation_required": True,
    }


def verify_controlled_baseline(
    project_root: str | Path,
    baseline_ref: str = DEFAULT_BASELINE_REF,
    *,
    requested_change_paths: Iterable[str] = (),
    protected_paths: Iterable[str] = PROTECTED_PATHS,
    expected_absent_paths: Iterable[str] = EXPECTED_ABSENT_PATHS,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    reasons: list[str] = []
    control_reasons: list[str] = []
    verified_hashes: dict[str, dict[str, str]] = {}
    requested_paths: list[str] = []
    protected_requests: list[str] = []

    commit_exists = _git_commit_exists(root, baseline_ref)
    if not commit_exists:
        reasons.append("baseline_git_commit_missing")

    for relative_path in protected_paths:
        target = _inside(root, relative_path)
        baseline_blob = _git_blob(root, baseline_ref, relative_path) if commit_exists else None
        if baseline_blob is None:
            reasons.append(f"baseline_protected_path_missing:{relative_path}")
            continue
        if target is None or not target.is_file():
            reason = f"current_protected_path_missing:{relative_path}"
            reasons.append(reason)
            control_reasons.append(reason)
            continue
        baseline_hash = _sha256_bytes(baseline_blob)
        current_hash = _sha256_bytes(target.read_bytes())
        verified_hashes[relative_path] = {
            "baseline_sha256": baseline_hash,
            "current_sha256": current_hash,
        }
        if baseline_hash != current_hash:
            reason = f"protected_hash_mismatch:{relative_path}"
            reasons.append(reason)
            control_reasons.append(reason)

    for relative_path in expected_absent_paths:
        target = _inside(root, relative_path)
        if target is None:
            reasons.append(f"expected_absent_path_outside_project:{relative_path}")
        elif target.exists():
            reason = f"expected_absent_path_present:{relative_path}"
            reasons.append(reason)
            control_reasons.append(reason)

    for value in requested_change_paths:
        normalized = _normalize_requested_path(str(value))
        if normalized is None:
            reasons.append(f"invalid_requested_change_path:{value}")
            continue
        requested_paths.append(normalized)
        if _is_protected_request(normalized):
            protected_requests.append(normalized)
            reason = f"requested_protected_change:{normalized}"
            reasons.append(reason)
            control_reasons.append(reason)

    controlled_change_required = bool(control_reasons)
    if controlled_change_required:
        guard_status = "CONTROLLED_CHANGE_REQUIRED"
    elif reasons:
        guard_status = "GUARD_FAILED_CLOSED"
    else:
        guard_status = "CLEAR"

    record: dict[str, Any] = {
        "record_type": "ControlledBaselineGuardRecord",
        "baseline_ref": baseline_ref,
        "guard_status": guard_status,
        "verification_status": "VERIFIED" if guard_status == "CLEAR" else "BLOCKED",
        "protected_paths": list(protected_paths),
        "expected_absent_paths": list(expected_absent_paths),
        "verified_hashes": verified_hashes,
        "requested_change_paths": requested_paths,
        "requested_protected_paths": protected_requests,
        "controlled_change_required": controlled_change_required,
        "entry_eligible": guard_status == "CLEAR",
        "reasons": reasons,
        "external_controlled_change_sequence": list(CONTROLLED_CHANGE_SEQUENCE),
        "escalation_record": (
            _escalation_record(control_reasons, protected_requests)
            if controlled_change_required
            else None
        ),
    }

    if output_path is not None:
        destination = Path(output_path)
        if not destination.is_absolute():
            destination = root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return record

"""Read-only production recovery decision shared by dry-run and execution."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


class ProductionDecisionError(ValueError):
    pass


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ProductionDecisionError(f"unsafe or missing persisted artifact: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionDecisionError(f"malformed persisted artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ProductionDecisionError(f"persisted artifact is not an object: {path.name}")
    return value


def _sealed(path: Path, sidecar: Path | None = None) -> str:
    digest = _sha(path)
    if sidecar is not None:
        if not sidecar.is_file() or sidecar.is_symlink() or sidecar.read_text(encoding="ascii").strip() != digest:
            raise ProductionDecisionError(f"persisted sidecar mismatch: {path.name}")
    return digest


def _safe_scope(scope: object) -> list[str]:
    if not isinstance(scope, list) or not scope:
        raise ProductionDecisionError("owned scope is missing")
    result: list[str] = []
    for item in scope:
        if not isinstance(item, str) or not item or "\\" in item:
            raise ProductionDecisionError("owned scope is unsafe")
        value = PurePosixPath(item)
        if value.is_absolute() or ".." in value.parts or value.as_posix() != item:
            raise ProductionDecisionError("owned scope is unsafe")
        result.append(item)
    if len(result) != len(set(result)):
        raise ProductionDecisionError("owned scope contains duplicates")
    return result


def _process_state(process: Mapping[str, Any] | None) -> tuple[str, bool]:
    if not process:
        return "TERMINATED", False
    pid = process.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return "TERMINATED", False
    recorded = process.get("started_at")
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return "TERMINATED", False
    # A PID without matching durable start identity is stale, never live.
    if not isinstance(recorded, str) or not recorded:
        return "STALE", False
    probe = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, check=False)
    actual = probe.stdout.strip()
    if probe.returncode != 0 or not actual or actual != recorded:
        return "STALE", False
    return "LIVE", True


def build_production_decision(*, project_root: str | Path, harness_root: str | Path,
                              project_id: str, gate_id: str, run_id: str, mode: str,
                              current_lv: str, inherited_completed_lvs: Sequence[str],
                              remaining_lvs: Sequence[str]) -> dict[str, Any]:
    """Resolve one production action without modifying files, Git, or processes."""
    root = Path(project_root).resolve()
    artifact = Path(harness_root).resolve() / "_workspace" / "orchestration-runs" / run_id / current_lv
    package_path = artifact / "package.manifest.json"
    preflight_path = artifact / "preflight" / "preflight.evidence.json"
    request_path = artifact / "worker.request.json"
    package_sha = _sealed(package_path, artifact / "package.manifest.sha256")
    preflight_sha = _sealed(preflight_path, artifact / "preflight" / "preflight.evidence.sha256")
    request_sha = _sealed(request_path)
    package = _json(package_path); preflight = _json(preflight_path); request = _json(request_path)
    extra = request.get("extra_context")
    if not isinstance(extra, dict):
        raise ProductionDecisionError("worker request context is missing")
    expected = (project_id, gate_id, current_lv, run_id)
    if (package.get("project_id"), package.get("gate_id"), package.get("lv_id"), package.get("run_id")) != expected:
        raise ProductionDecisionError("package production binding mismatch")
    if (preflight.get("project_id"), preflight.get("gate_id"), preflight.get("lv_id"), preflight.get("run_id")) != expected:
        raise ProductionDecisionError("preflight production binding mismatch")
    if (extra.get("gate_id"), extra.get("lv_id"), extra.get("run_id")) != expected[1:]:
        raise ProductionDecisionError("worker request production binding mismatch")
    if extra.get("package_manifest_sha256") != package_sha or extra.get("preflight_evidence_sha256") != preflight_sha:
        raise ProductionDecisionError("worker request artifact binding mismatch")
    attempt = extra.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ProductionDecisionError("worker request attempt is invalid")
    scope = _safe_scope(package.get("owned_files"))
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    changed = [line[3:] for line in status if len(line) > 3]
    outside = [path for path in changed if path not in scope]
    if outside or (changed and set(changed) != set(scope)):
        raise ProductionDecisionError("partial workspace does not match owned scope")
    process_path = artifact / "executor.process.json"
    process = _json(process_path) if process_path.exists() else None
    process_state, live = _process_state(process)
    if live:
        selected="WAIT_EXISTING_WORKER"; recovery="LIVE_BOUND_WORKER"
    elif changed:
        selected="OFFICIAL_PARTIAL_ADOPTION"; recovery="TERMINATED_ADOPTABLE_PARTIAL"
    else:
        result_path=artifact/"worker.result.json"
        result=_json(result_path)
        if (result.get("project_id"),result.get("gate_id"),result.get("lv_id"),result.get("run_id")) != expected:
            raise ProductionDecisionError("persisted worker result binding mismatch")
        selected="REPLAY_SEALED_WORKER_RESULT"; recovery="ADOPTION_CHECKPOINTED"
    digest = hashlib.sha256(json.dumps(scope, sort_keys=False, separators=(",", ":")).encode()).hexdigest()
    return {
        "project_id": project_id, "gate_id": gate_id, "run_id": run_id, "mode": mode,
        "current_lv": current_lv, "first_incomplete_lv": current_lv,
        "inherited_completed_lvs": list(inherited_completed_lvs), "remaining_lvs": list(remaining_lvs),
        "attempt": attempt, "recovery_state": recovery, "selected_action": selected,
        "worker_process_state": process_state, "duplicate_worker_detected": live,
        "duplicate_worker_blocked": True, "owned_scope": scope, "owned_scope_digest": digest,
        "package_sha256": package_sha, "preflight_sha256": preflight_sha,
        "worker_request_sha256": request_sha, "mutation_performed": False,
        "next_gate_state": "USER_APPROVAL_REQUIRED", "hard_stop_at_gate_boundary": True,
    }

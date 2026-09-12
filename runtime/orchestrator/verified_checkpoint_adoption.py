"""Explicit, evidence-backed adoption of an approved product checkpoint."""
from __future__ import annotations

import hashlib
import json
import os
import argparse
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .production_approval import load_v2_event_log


ADOPTION_MODE = "VERIFIED_CHECKPOINT_ADOPTION"
ADOPTION_SCHEMA = "orchestration.verified-checkpoint-adoption.v1"


class VerifiedCheckpointAdoptionError(ValueError):
    """A checkpoint cannot be adopted without complete independent evidence."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise VerifiedCheckpointAdoptionError("checkpoint Git provenance is unavailable")
    return completed.stdout.strip()


def _safe_paths(values: object, *, label: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise VerifiedCheckpointAdoptionError(f"{label} is missing")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item or "\\" in item:
            raise VerifiedCheckpointAdoptionError(f"{label} is unsafe")
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != item:
            raise VerifiedCheckpointAdoptionError(f"{label} is unsafe")
        result.append(item)
    if len(result) != len(set(result)):
        raise VerifiedCheckpointAdoptionError(f"{label} contains duplicates")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise VerifiedCheckpointAdoptionError(f"unsafe or missing artifact: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerifiedCheckpointAdoptionError(f"malformed artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise VerifiedCheckpointAdoptionError(f"artifact is not an object: {path.name}")
    return value


def _command(root: Path, argv: list[str]) -> dict[str, Any]:
    completed = subprocess.run(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120)
    return {
        "command": argv,
        "exit_code": completed.returncode,
        "timeout": False,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
    }


def _validate_event(manifest: Mapping[str, Any], event: Mapping[str, Any], approval_event_id: str) -> None:
    expected = (manifest.get("project_id"), manifest.get("gate_id"), manifest.get("lv_id"))
    if event.get("event_id") != approval_event_id or (event.get("project_id"), event.get("gate_id")) != expected[:2]:
        raise VerifiedCheckpointAdoptionError("approval event binding mismatch")
    scope = event.get("owned_file_scope", {}).get(expected[2]) if isinstance(event.get("owned_file_scope"), dict) else None
    if scope != manifest.get("owned_files"):
        raise VerifiedCheckpointAdoptionError("approval owned scope mismatch")
    if event.get("plan_sha256") != manifest.get("canonical_plan_sha256"):
        raise VerifiedCheckpointAdoptionError("approval plan binding mismatch")
    if manifest.get("approval_record_hash") and event.get("record_hash") != manifest.get("approval_record_hash"):
        raise VerifiedCheckpointAdoptionError("approval record binding mismatch")


def build_verified_checkpoint_result(*, project_root: str | Path, package_root: str | Path,
                                     approval_log: str | Path, approval_event_id: str) -> dict[str, Any]:
    """Revalidate a scope-limited approved checkpoint and return sealed-result content.

    This never invokes a Worker and never mutates the project.  The caller is
    responsible for atomically writing the returned result into the sealed run.
    """
    root = Path(project_root).resolve()
    package = Path(package_root).resolve()
    manifest = _read_json(package / "package.manifest.json")
    events = load_v2_event_log(approval_log)
    selected = [event for event in events if event.get("event_id") == approval_event_id]
    if len(selected) != 1:
        raise VerifiedCheckpointAdoptionError("approval event is missing or ambiguous")
    event = selected[0]
    _validate_event(manifest, event, approval_event_id)
    owned = _safe_paths(manifest.get("owned_files"), label="owned scope")
    checkpoint = event.get("baseline_head")
    if not isinstance(checkpoint, str) or len(checkpoint) < 40:
        raise VerifiedCheckpointAdoptionError("approval checkpoint is invalid")
    parent = _git(root, "rev-parse", f"{checkpoint}^")
    current_head = _git(root, "rev-parse", "HEAD")
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", checkpoint, current_head], check=False).returncode != 0:
        raise VerifiedCheckpointAdoptionError("approved checkpoint is not an ancestor of HEAD")
    changed = sorted(filter(None, _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint).splitlines()))
    if changed != sorted(owned):
        raise VerifiedCheckpointAdoptionError("checkpoint changed-file scope does not exactly match approval")
    later = set(filter(None, _git(root, "diff", "--name-only", f"{checkpoint}..{current_head}").splitlines()))
    if later.intersection(owned):
        raise VerifiedCheckpointAdoptionError("approved checkpoint owned files changed after checkpoint")
    if _git(root, "status", "--porcelain=v1", "-uall"):
        raise VerifiedCheckpointAdoptionError("project worktree is not clean")
    python = root / ".venv" / "bin" / "python"
    pytest = root / ".venv" / "bin" / "pytest"
    tests = [path for path in owned if path.startswith("tests/") and path.endswith(".py")]
    if not python.is_file() or not pytest.is_file() or not tests:
        raise VerifiedCheckpointAdoptionError("registered project test toolchain is unavailable")
    commands = {
        "checkpoint_provenance": _command(root, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint]),
        "focused_test": _command(root, [str(pytest), "-q", *tests]),
        "full_regression": _command(root, [str(pytest), "-q"]),
        "compile_import": _command(root, [str(python), "-m", "compileall", "-q", *owned]),
        "git_diff_check": _command(root, ["git", "diff", "--check"]),
    }
    if any(value["exit_code"] != 0 or value["timeout"] for value in commands.values()):
        raise VerifiedCheckpointAdoptionError("independent checkpoint validation failed")
    current_tree = _git(root, "rev-parse", "HEAD^{tree}")
    baseline_tree = _git(root, "rev-parse", f"{parent}^{{tree}}")
    package_sha = hashlib.sha256((package / "package.manifest.json").read_bytes()).hexdigest()
    result: dict[str, Any] = {
        "schema_version": "orchestration.product-completion-evidence.v1",
        "status": "completed",
        "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
        "run_id": manifest["run_id"], "approval_event_id": approval_event_id,
        "plan_sha256": manifest["canonical_plan_sha256"], "attempt": 1,
        "completion_mode": ADOPTION_MODE, "execution_kind": "CHECKPOINT_ADOPTION",
        "owned_files": owned, "changed_files": changed,
        "baseline_head": parent, "baseline_tree": baseline_tree,
        "current_head": current_head, "current_tree": current_tree,
        "checkpoint_commit": checkpoint, "commands": commands,
        "tests": list(manifest.get("completion_checks", [])),
        "staged_changes": False, "unstaged_changes": False, "review_verdict": "PENDING",
        "package_sha256": package_sha,
        "preflight_evidence_sha256": hashlib.sha256((package / "preflight" / "preflight.evidence.json").read_bytes()).hexdigest(),
        "validation_events": ["CHECKPOINT_PROVENANCE_VERIFIED", "INDEPENDENT_VALIDATION_COMPLETED", "WORKER_RESULT_SEALED"],
        "adoption": {
            "schema_version": ADOPTION_SCHEMA, "approval_event_id": approval_event_id,
            "approval_record_hash": event["record_hash"], "checkpoint_commit": checkpoint,
            "checkpoint_parent": parent, "current_head": current_head,
            "source_provenance": "GIT_COMMIT_EXACT_SCOPE", "worker_provenance": "NOT_APPLICABLE_CHECKPOINT_ADOPTION",
            "independent_validation": "PASSED", "review_required": True,
        },
        "artifact_sha_chain": {"manifest": package_sha, "approval": event["record_hash"], "commands": _sha(commands)},
        "hard_stop": True,
    }
    result["evidence_sha256"] = _sha(result)
    return result


def write_verified_checkpoint_result(**kwargs: Any) -> dict[str, Any]:
    package = Path(kwargs["package_root"]).resolve()
    target = package / "worker.result.json"
    if target.exists() or target.is_symlink():
        raise VerifiedCheckpointAdoptionError("sealed worker result already exists")
    result = build_verified_checkpoint_result(**kwargs)
    data = _canonical(result)
    fd, temporary = tempfile.mkstemp(prefix=".worker.result.", dir=package)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"status": "WRITTEN", "mutation_performed": True, "worker_result_sha256": hashlib.sha256(data).hexdigest(),
            "checkpoint_commit": result["checkpoint_commit"], "changed_files": result["changed_files"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adopt an approved, independently verified checkpoint")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--approval-log", required=True)
    parser.add_argument("--approval-event-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(write_verified_checkpoint_result(
        project_root=args.project_root, package_root=args.package_root,
        approval_log=args.approval_log, approval_event_id=args.approval_event_id,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

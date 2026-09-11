from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from runtime.agents import get_agent_class
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest
from runtime.orchestrator.result_normalizer import normalize_worker_result, render_worker_handoff_markdown
from runtime.orchestrator.lv_execution_package import canonical_json_bytes, WORKER_RESULT_SCHEMA_VERSION


class WorkerRunnerError(ValueError):
    """Fail-closed worker request/result boundary error."""


def _safe_boundary_path(path: Path, *, must_exist: bool = False) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise WorkerRunnerError("worker path must be an absolute non-symlink path")
    resolved = path.resolve()
    if resolved != path:
        raise WorkerRunnerError("worker path contains symlinked components")
    if must_exist and (not path.exists() or not path.is_file()):
        raise WorkerRunnerError("worker request is not a regular file")
    return path


def _load_request(path: Path) -> WorkerRequest:
    _safe_boundary_path(path, must_exist=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    task = TaskSlice(**payload["task"])
    return WorkerRequest(
        project_root=payload["project_root"],
        task=task,
        contract_summary=payload["contract_summary"],
        state_snapshot=payload["state_snapshot"],
        extra_context=payload.get("extra_context", {}),
    )


def _write_markdown(result: dict[str, object], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "handoff_report.md"
    report_path.write_text(render_worker_handoff_markdown(result), encoding="utf-8")
    legacy_path = output_dir / "worker_handoff.md"
    legacy_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a single orchestration worker.")
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args(argv)

    request_path = Path(args.request_file)
    result_path = Path(args.result_file)
    _safe_boundary_path(request_path, must_exist=True)
    if request_path == result_path:
        raise WorkerRunnerError("request and result paths must differ")
    _safe_boundary_path(result_path)
    if result_path.exists() and (result_path.is_symlink() or not result_path.is_file()):
        raise WorkerRunnerError("worker result path is unsafe")
    request = _load_request(request_path)
    if request.extra_context.get("execution_mode") == "production":
        from runtime.orchestrator.production_worker_executor import execute_production_worker
        result_payload = execute_production_worker(request)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.exists():
            raise WorkerRunnerError("production worker result already exists")
        result_path.write_bytes(canonical_json_bytes(result_payload))
        return 0
    agent_class = get_agent_class(request.task.assigned_agent)
    agent = agent_class()
    result = agent.run(request)
    result_payload = normalize_worker_result(
        result.to_dict(),
        task=request.task,
        source="worker",
        mode=request.extra_context.get("execution_mode", "mock"),
        prompt_path=request.task.task_prompt_path,
        output_dir=request.task.output_dir,
        run_id=request.extra_context.get("run_id", ""),
        run_root=request.extra_context.get("run_root", ""),
    )
    # Gate lifecycle consumes explicit, truthful arrays rather than inferring
    # evidence from worker prose.  The registered deterministic worker has no
    # mutation authority, so these are derived from its request contract.
    result_payload["changed_files"] = []
    result_payload["created_files"] = []
    result_payload["modified_files"] = []
    result_payload["deleted_files"] = []
    result_payload["tests"] = list(request.task.validation_criteria)
    result_payload["commands_summary"] = []
    result_payload["violations"] = []
    result_payload["error"] = None if result_payload.get("status") == "completed" else {"message": "worker failed"}
    result_payload["runtime_sandbox_approval_state"] = {"source": "external_codex_runtime", "state": "allowed_by_active_policy", "business_approval_reused": False, "verified_by_harness": False}
    extra = request.extra_context
    result_payload.update({
        "schema_version": WORKER_RESULT_SCHEMA_VERSION,
        "run_id": extra.get("run_id", result_payload.get("run_id", "")),
        "package_manifest_sha256": extra.get("package_manifest_sha256", ""),
        "gate_id": extra.get("gate_id", ""),
        "lv_id": extra.get("lv_id", request.task.thread_id),
        "attempt": int(extra.get("attempt", 1)),
        "preflight_evidence_sha256": extra.get("preflight_evidence_sha256", ""),
        "worker_type": "manual",
        "owned_files": list(request.task.editable_scope),
        "source_head_before": extra.get("source_snapshot", {}).get("source_head", ""),
        "source_head_after": extra.get("source_snapshot", {}).get("source_head", ""),
        "source_tree_before": extra.get("source_snapshot", {}).get("source_tree", ""),
        "source_tree_after": extra.get("source_snapshot", {}).get("source_tree", ""),
        "source_index_before": extra.get("source_snapshot", {}).get("source_index_fingerprint", ""),
        "source_index_after": extra.get("source_snapshot", {}).get("source_index_fingerprint", ""),
        "source_worktree_before": extra.get("source_snapshot", {}).get("source_worktree_fingerprint", ""),
        "source_worktree_after": extra.get("source_snapshot", {}).get("source_worktree_fingerprint", ""),
        "started_at": extra.get("started_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "completed_at": extra.get("completed_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.exists() and result_path.is_symlink():
        raise WorkerRunnerError("worker result path became a symlink")
    result_bytes = canonical_json_bytes(result_payload)
    # The digest binds the exact worker payload without making the payload self-referential.
    result_payload["result_sha256"] = hashlib.sha256(result_bytes).hexdigest()
    result_bytes = canonical_json_bytes(result_payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(result_path, flags, 0o600)
    try:
        os.write(fd, result_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    _write_markdown(result_payload, result_path.parent)
    return 0 if not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

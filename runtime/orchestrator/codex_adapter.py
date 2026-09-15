from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .result_normalizer import normalize_worker_result, render_worker_handoff_markdown
from .execution_modes import CODEX_CLI, MANUAL, MOCK, normalize_execution_mode
from .codex_launcher import (
    CodexLauncherError,
    CodexProcessResult,
    execute_codex_invocation,
    probe_codex_cli_capabilities,
    resolve_codex_launcher,
)


class CodexAdapterRuntimeError(RuntimeError):
    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


def detect_codex_cli() -> bool:
    env_command = os.getenv("CODEX_CLI_COMMAND", "").strip()
    if env_command:
        return True
    return shutil.which("codex") is not None


def _default_project_root(task_prompt_path: Path) -> Path:
    return task_prompt_path.expanduser().resolve(strict=False).parent


def _write_output_schema(output_dir: Path) -> Path:
    schema_path = output_dir / "codex_output_schema.json"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "thread_id",
            "agent_name",
            "status",
            "summary",
            "findings",
            "warnings",
            "errors",
            "artifacts",
            "next_step",
        ],
        "properties": {
            "thread_id": {"type": "string"},
            "agent_name": {"type": "string"},
            "status": {"type": "string"},
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "errors": {"type": "array", "items": {"type": "string"}},
            "artifacts": {"type": "array", "items": {"type": "string"}},
            "next_step": {"type": "string"},
        },
    }
    schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    return schema_path


def _write_launcher_log(
    output_dir: Path,
    *,
    argv: Iterable[str] = (),
    process: CodexProcessResult | None = None,
    failure_class: str | None = None,
    status: str = "",
    message: str = "",
) -> Path:
    log_path = output_dir / "codex_launcher.log"
    lines = [
        "launcher: codex exec",
        f"status: {status}",
        f"failure_class: {failure_class or ''}",
        f"argv: {' '.join(str(item) for item in argv)}",
    ]
    if process is not None:
        lines.extend(
            [
                f"returncode: {process.returncode}",
                f"timed_out: {process.timed_out}",
                f"cancelled: {process.cancelled}",
                f"killed: {process.killed}",
                f"duration_seconds: {process.duration_seconds}",
                f"final_output_path: {process.final_output_path}",
                f"final_output_exists: {process.final_output_exists}",
                f"structured_output_valid: {process.structured_output_valid}",
                "",
                "stdout",
                process.stdout or "",
                "",
                "stderr",
                process.stderr or "",
            ]
        )
    elif message:
        lines.extend(["", "message", message])
    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return log_path


def _write_canonical_worker_files(
    payload: dict[str, Any],
    *,
    prompt_path: Path,
    output_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    payload = dict(payload)
    payload.setdefault("project_root", str(project_root))
    normalized = normalize_worker_result(
        payload,
        source=CODEX_CLI,
        mode=CODEX_CLI,
        prompt_path=str(prompt_path),
        output_dir=str(output_dir),
    )
    result_path = output_dir / "result.json"
    handoff_path = output_dir / "handoff_report.md"
    result_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(render_worker_handoff_markdown(normalized), encoding="utf-8")
    (output_dir / "worker_handoff.md").write_text(handoff_path.read_text(encoding="utf-8"), encoding="utf-8")
    return normalized


def _manual_fallback(
    task_prompt_path: str | Path,
    output_dir: str | Path,
    *,
    reason: str,
    backend_failure_class: str | None = None,
    launcher_log_path: str = "",
) -> dict[str, Any]:
    fallback = create_manual_task(task_prompt_path, output_dir)
    fallback.update(
        {
            "status": "manual_fallback",
            "reason": reason,
        }
    )
    if backend_failure_class:
        fallback["backend_failure_class"] = backend_failure_class
    if launcher_log_path:
        fallback["launcher_log_path"] = launcher_log_path
    return fallback


def create_manual_task(task_prompt_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    prompt_path = Path(task_prompt_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manual_path = output_dir / "manual_execution.md"
    manual_path.write_text(
        "\n".join(
            [
                "# Manual Codex Execution",
                "",
                f"Prompt file: {prompt_path}",
                f"Output directory: {output_dir}",
                "",
                "Instructions",
                "1. Copy the task prompt into Codex.",
                "2. Save `handoff_report.md` to the output directory.",
                "3. Save `result.json` if possible.",
                "4. Run `collect` after the output files are saved.",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    return {
        "mode": MANUAL,
        "status": "manual_pending",
        "manual_execution_path": str(manual_path),
        "prompt_path": str(prompt_path),
        "output_dir": str(output_dir),
    }


def run_codex_cli(
    task_prompt_path: str | Path,
    output_dir: str | Path,
    *,
    project_root: str | Path | None = None,
    required_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    prompt_path = Path(task_prompt_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    project_root_path = Path(project_root) if project_root is not None else _default_project_root(prompt_path)
    schema_path = _write_output_schema(target_dir)
    manifest = probe_codex_cli_capabilities(
        executable_resolver=shutil.which,
        runner=lambda argv: subprocess.run(argv, capture_output=True, text=True, check=False),
    )
    invocation = resolve_codex_launcher(
        manifest,
        project_root_path,
        target_dir,
        required_capabilities=required_capabilities,
        output_schema_path=schema_path,
    )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    process = execute_codex_invocation(invocation, prompt_text)
    log_path = _write_launcher_log(target_dir, argv=invocation.argv, process=process, failure_class=process.failure_class, status=process.status)
    if process.status != "SUCCESS":
        failure = process.failure_class or process.status
        raise CodexAdapterRuntimeError(failure, f"codex launcher failed for {prompt_path}: {failure}. See {log_path} for details.")

    final_output_path = Path(process.final_output_path)
    payload = json.loads(final_output_path.read_text(encoding="utf-8"))
    _write_canonical_worker_files(payload, prompt_path=prompt_path, output_dir=target_dir, project_root=project_root_path)
    return {
        "mode": CODEX_CLI,
        "status": "completed",
        "command": list(invocation.argv),
        "log_path": str(log_path),
        "launcher_log_path": str(log_path),
        "backend_failure_class": None,
        "sandbox_mode": invocation.sandbox_mode,
        "prompt_path": str(prompt_path),
        "output_dir": str(target_dir),
    }


def run_task_prompt(
    task_prompt_path: str | Path,
    output_dir: str | Path,
    mode: str,
    *,
    project_root: str | Path | None = None,
    required_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    normalized = normalize_execution_mode(mode)
    if normalized == MOCK:
        return {
            "mode": MOCK,
            "status": "delegated_to_local_worker",
            "prompt_path": str(Path(task_prompt_path)),
            "output_dir": str(Path(output_dir)),
        }
    if normalized == MANUAL:
        return create_manual_task(task_prompt_path, output_dir)
    if not detect_codex_cli():
        return _manual_fallback(
            task_prompt_path,
            output_dir,
            reason="codex CLI not detected",
            backend_failure_class="CLI_NOT_FOUND",
        )
    try:
        return run_codex_cli(
            task_prompt_path,
            output_dir,
            project_root=project_root,
            required_capabilities=required_capabilities,
        )
    except CodexLauncherError as exc:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = _write_launcher_log(target_dir, failure_class=exc.failure_class, status=exc.status, message=str(exc))
        return _manual_fallback(
            task_prompt_path,
            output_dir,
            reason=str(exc),
            backend_failure_class=exc.failure_class,
            launcher_log_path=str(log_path),
        )
    except CodexAdapterRuntimeError as exc:
        target_dir = Path(output_dir)
        log_path = target_dir / "codex_launcher.log"
        return _manual_fallback(
            task_prompt_path,
            output_dir,
            reason=str(exc),
            backend_failure_class=exc.failure_class,
            launcher_log_path=str(log_path) if log_path.exists() else "",
        )
    except Exception as exc:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        failure_class = getattr(exc, "failure_class", None)
        log_path = _write_launcher_log(
            target_dir,
            failure_class=failure_class,
            status="manual_fallback",
            message=str(exc),
        )
        return _manual_fallback(
            task_prompt_path,
            output_dir,
            reason=str(exc),
            backend_failure_class=failure_class,
            launcher_log_path=str(log_path),
        )

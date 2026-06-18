from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .result_normalizer import normalize_worker_result, render_worker_handoff_markdown
from .execution_modes import CODEX_CLI, MANUAL, MOCK, normalize_execution_mode


def detect_codex_cli() -> bool:
    env_command = os.getenv("CODEX_CLI_COMMAND", "").strip()
    if env_command:
        return True
    return shutil.which("codex") is not None


def _build_command(task_prompt_path: Path, output_dir: Path) -> list[str]:
    env_command = os.getenv("CODEX_CLI_COMMAND", "").strip()
    if env_command:
        return shlex.split(env_command.format(prompt=str(task_prompt_path), output_dir=str(output_dir)))
    codex_executable = shutil.which("codex")
    if not codex_executable:
        raise FileNotFoundError("codex CLI is not available on PATH.")
    return [
        codex_executable,
        "run",
        "--prompt-file",
        str(task_prompt_path),
        "--output-dir",
        str(output_dir),
    ]


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


def run_codex_cli(task_prompt_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    prompt_path = Path(task_prompt_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    command = _build_command(prompt_path, target_dir)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    log_path = target_dir / "codex_cli.log"
    log_path.write_text(
        "\n".join(
            [
                f"command: {' '.join(command)}",
                f"returncode: {completed.returncode}",
                "",
                "stdout",
                completed.stdout or "",
                "",
                "stderr",
                completed.stderr or "",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"codex CLI failed for {prompt_path}. See {log_path} for details. "
            "Fallback to manual mode is recommended."
        )
    result_path = target_dir / "result.json"
    if result_path.exists():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            normalized = normalize_worker_result(
                payload,
                source=CODEX_CLI,
                mode=CODEX_CLI,
                prompt_path=str(prompt_path),
                output_dir=str(target_dir),
            )
            result_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
            (target_dir / "handoff_report.md").write_text(render_worker_handoff_markdown(normalized), encoding="utf-8")
            (target_dir / "worker_handoff.md").write_text(
                (target_dir / "handoff_report.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - defensive normalization fallback
            (target_dir / "codex_cli_normalization.log").write_text(
                f"normalization_failed: {exc}\n",
                encoding="utf-8",
            )
    return {
        "mode": CODEX_CLI,
        "status": "completed",
        "command": command,
        "log_path": str(log_path),
        "prompt_path": str(prompt_path),
        "output_dir": str(target_dir),
    }


def run_task_prompt(task_prompt_path: str | Path, output_dir: str | Path, mode: str) -> dict[str, Any]:
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
        fallback = create_manual_task(task_prompt_path, output_dir)
        fallback.update(
            {
                "mode": MANUAL,
                "status": "manual_fallback",
                "reason": "codex CLI not detected",
            }
        )
        return fallback
    try:
        return run_codex_cli(task_prompt_path, output_dir)
    except Exception as exc:
        fallback = create_manual_task(task_prompt_path, output_dir)
        fallback.update(
            {
                "status": "manual_fallback",
                "reason": str(exc),
            }
        )
        return fallback

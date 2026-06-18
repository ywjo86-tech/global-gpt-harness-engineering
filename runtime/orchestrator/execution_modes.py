from __future__ import annotations

from dataclasses import dataclass


MOCK = "mock"
MANUAL = "manual"
CODEX_CLI = "codex-cli"
SUPPORTED_EXECUTION_MODES = (MOCK, MANUAL, CODEX_CLI)


@dataclass(slots=True)
class ExecutionModeInfo:
    mode: str
    description: str
    codex_cli_eligible: bool
    manual_fallback: bool


def normalize_execution_mode(mode: str | None) -> str:
    normalized = (mode or MOCK).strip().lower().replace("_", "-")
    if normalized in {"codex", "codexcli"}:
        normalized = CODEX_CLI
    if normalized not in SUPPORTED_EXECUTION_MODES:
        raise ValueError(f"Unsupported execution mode: {mode}")
    return normalized


def mode_info(mode: str | None) -> ExecutionModeInfo:
    normalized = normalize_execution_mode(mode)
    if normalized == MOCK:
        return ExecutionModeInfo(
            mode=normalized,
            description="Local mock workers execute task slices in-process.",
            codex_cli_eligible=False,
            manual_fallback=False,
        )
    if normalized == MANUAL:
        return ExecutionModeInfo(
            mode=normalized,
            description="Codex prompts are generated for human-driven execution.",
            codex_cli_eligible=False,
            manual_fallback=True,
        )
    return ExecutionModeInfo(
        mode=normalized,
        description="Best-effort Codex CLI execution with manual fallback.",
        codex_cli_eligible=True,
        manual_fallback=True,
    )


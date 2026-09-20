"""Safe configuration for the authority-free diagnostic intelligence plane."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class DiagnosticConfigError(ValueError):
    pass


_VALID_MODES = frozenset({"OFF", "SHADOW", "ADVISORY"})


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise DiagnosticConfigError(f"{name} must be positive")
    return parsed


@dataclass(frozen=True, slots=True)
class DiagnosticConfig:
    enabled: bool = False
    mode: str = "OFF"
    max_result_bytes: int = 262144
    max_context_chars: int = 12000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DiagnosticConfig":
        source = dict(os.environ if env is None else env)
        raw_enabled = str(source.get("GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED", "false")).strip().lower()
        if raw_enabled not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise DiagnosticConfigError("GCH_DIAGNOSTIC_INTELLIGENCE_ENABLED is invalid")
        enabled = raw_enabled in {"true", "1", "yes", "on"}
        requested_mode = str(source.get("GCH_DIAGNOSTIC_INTELLIGENCE_MODE", "OFF")).strip().upper()
        if enabled and requested_mode not in _VALID_MODES:
            raise DiagnosticConfigError("unsupported diagnostic mode")
        mode = requested_mode if enabled else "OFF"
        if enabled and mode == "OFF":
            enabled = False
        return cls(
            enabled=enabled,
            mode=mode,
            max_result_bytes=_positive_int(
                str(source.get("GCH_DIAGNOSTIC_MAX_RESULT_BYTES", "262144")),
                "GCH_DIAGNOSTIC_MAX_RESULT_BYTES",
            ),
            max_context_chars=_positive_int(
                str(source.get("GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS", "12000")),
                "GCH_DIAGNOSTIC_MAX_CONTEXT_CHARS",
            ),
        )

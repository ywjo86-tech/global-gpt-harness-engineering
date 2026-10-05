"""Privacy-bounded model usage evidence helpers."""
from __future__ import annotations

from typing import Any, Mapping

_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class ModelUsageEvidenceError(ValueError):
    pass


def normalize_turn_usage(value: Mapping[str, Any]) -> dict[str, int]:
    """Validate and normalize the numeric-only Codex turn usage envelope."""
    if not isinstance(value, Mapping):
        raise ModelUsageEvidenceError("turn usage mapping required")
    required = {
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    }
    optional = {"cache_write_input_tokens"}
    if not required.issubset(value) or set(value) - required - optional:
        raise ModelUsageEvidenceError("turn usage shape invalid")
    result: dict[str, int] = {}
    for key in _USAGE_FIELDS:
        raw = value.get(key, 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ModelUsageEvidenceError(f"turn usage {key} invalid")
        result[key] = raw
    return result

from __future__ import annotations

import json
from datetime import datetime

import pytest

from runtime.orchestrator.production_worker_executor import (
    StructuredEventError,
    _parse_structured_jsonl,
)


def _usage() -> dict[str, int]:
    return {
        "input_tokens": 100,
        "cached_input_tokens": 10,
        "cache_write_input_tokens": 0,
        "output_tokens": 20,
        "reasoning_output_tokens": 5,
    }


def _stream(usage: dict[str, int]) -> bytes:
    events = (
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "turn.completed", "usage": usage},
    )
    return b"\n".join(json.dumps(event).encode() for event in events)


def test_successful_turn_exposes_numeric_only_usage_metadata():
    value = _parse_structured_jsonl(_stream(_usage()))
    assert value["turn_usage"] == _usage()
    assert value["turn_usage_source"] == "CODEX_TURN_COMPLETED"
    observed = datetime.fromisoformat(value["turn_usage_observed_at"])
    assert observed.tzinfo is not None
    raw = json.dumps(value)
    for forbidden in ("prompt", "response", "provider", "model_ref", "credential"):
        assert forbidden not in raw


def test_invalid_usage_remains_fail_closed():
    usage = _usage()
    usage["input_tokens"] = -1
    with pytest.raises(StructuredEventError):
        _parse_structured_jsonl(_stream(usage))

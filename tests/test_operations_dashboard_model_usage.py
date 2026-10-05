from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.model_usage_registry_cli import main as registry_main
from runtime.orchestrator.operations_dashboard_model_usage import (
    MODEL_USAGE_SOURCE_V1,
    OperationsDashboardModelUsageError,
    initialize_model_usage_registry,
    read_operations_dashboard_model_usage,
    validate_model_usage_projection,
)
from runtime.orchestrator.operations_dashboard_source import (
    build_live_operations_dashboard_projection,
)
from runtime.orchestrator.production_worker_executor import _parse_structured_jsonl


def _usage(input_tokens=100, output_tokens=20):
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": 10,
        "cache_write_input_tokens": 0,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": 5,
    }


def _process(path: Path, observed_at: str, usage: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "orchestration.production-worker-process.v1",
        "structured_strict": True,
        "structured_events": {
            "structured_terminal_status": "SUCCEEDED",
            "turn_usage_source": "CODEX_TURN_COMPLETED",
            "turn_usage_observed_at": observed_at,
            "turn_usage": usage,
        },
    }))


class ModelUsageProjectionTests(unittest.TestCase):
    def test_structured_parser_preserves_numeric_usage_only(self):
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": _usage()},
        )
        parsed = _parse_structured_jsonl(
            b"\n".join(json.dumps(event).encode() for event in events)
        )
        self.assertEqual(parsed["turn_usage"], _usage())
        self.assertEqual(parsed["turn_usage_source"], "CODEX_TURN_COMPLETED")
        self.assertTrue(parsed["turn_usage_observed_at"])
        raw = json.dumps(parsed)
        self.assertNotIn("prompt", raw)
        self.assertNotIn("response", raw)
        self.assertNotIn("provider", raw)
        self.assertNotIn("model_ref", raw)

    def test_missing_registry_is_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            value = read_operations_dashboard_model_usage(
                td, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
            )
            self.assertEqual(value["source_state"], "UNAVAILABLE")
            self.assertIsNone(value["usage"])
            self.assertEqual(value["cost"]["reason"], "NO_CANONICAL_USAGE_SOURCE")

    def test_registry_empty_is_canonical_zero_after_instrumentation(self):
        with tempfile.TemporaryDirectory() as td:
            initialize_model_usage_registry(
                td,
                activated_at="2026-10-05T00:00:00+09:00",
                registry_ref="usage-registry:test",
            )
            value = read_operations_dashboard_model_usage(
                td, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
            )
            self.assertEqual(value["source_state"], MODEL_USAGE_SOURCE_V1)
            self.assertEqual(value["usage"]["execution_count"], 0)
            self.assertEqual(value["usage"]["input_output_tokens"], 0)
            self.assertEqual(value["cost"], {
                "status": "UNAVAILABLE",
                "estimated_usd": None,
                "reason": "NO_VERIFIED_RATE_CARD",
            })

    def test_today_kst_usage_aggregates_only_post_activation_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            initialize_model_usage_registry(
                root,
                activated_at="2026-10-05T09:00:00+09:00",
                registry_ref="usage-registry:test",
            )
            base = root / "_workspace" / "orchestration-runs"
            _process(
                base / "r1" / "TASK-1" / "executor.process.json",
                "2026-10-05T01:00:00+00:00",
                _usage(100, 20),
            )
            _process(
                base / "r2" / "TASK-2" / "executor.process.json",
                "2026-10-05T05:00:00+00:00",
                _usage(300, 40),
            )
            _process(
                base / "old" / "TASK-X" / "executor.process.json",
                "2026-10-04T10:00:00+00:00",
                _usage(900, 900),
            )
            value = read_operations_dashboard_model_usage(
                root, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
            )
            usage = value["usage"]
            self.assertEqual(usage["execution_count"], 2)
            self.assertEqual(usage["input_tokens"], 400)
            self.assertEqual(usage["output_tokens"], 60)
            self.assertEqual(usage["input_output_tokens"], 460)
            self.assertEqual(usage["cached_input_tokens"], 20)
            self.assertEqual(usage["reasoning_output_tokens"], 10)

    def test_corrupt_instrumented_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            initialize_model_usage_registry(
                root,
                activated_at="2026-10-05T00:00:00+09:00",
                registry_ref="usage-registry:test",
            )
            path = root / "_workspace" / "orchestration-runs" / "r1" / "TASK" / "executor.process.json"
            _process(path, "2026-10-05T01:00:00+00:00", _usage())
            value = json.loads(path.read_text())
            value["structured_events"]["turn_usage"]["input_tokens"] = -1
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(OperationsDashboardModelUsageError, "turn evidence invalid"):
                read_operations_dashboard_model_usage(
                    root, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
                )

    def test_future_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            initialize_model_usage_registry(
                root,
                activated_at="2026-10-05T00:00:00+09:00",
                registry_ref="usage-registry:test",
            )
            _process(
                root / "_workspace" / "orchestration-runs" / "r1" / "TASK" / "executor.process.json",
                "2026-10-05T09:01:00+00:00",
                _usage(),
            )
            with self.assertRaisesRegex(OperationsDashboardModelUsageError, "future"):
                read_operations_dashboard_model_usage(
                    root, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
                )

    def test_cost_cannot_be_invented_without_verified_rate_card(self):
        with self.assertRaisesRegex(
            OperationsDashboardModelUsageError, "unverified model cost"
        ):
            validate_model_usage_projection({
                "source_state": MODEL_USAGE_SOURCE_V1,
                "period": "TODAY_ASIA_SEOUL",
                "usage": {
                    "execution_count": 1,
                    **_usage(),
                    "input_output_tokens": 120,
                },
                "cost": {
                    "status": "AVAILABLE",
                    "estimated_usd": 1.23,
                    "reason": "GUESSED",
                },
            })

    def test_live_dashboard_embeds_model_usage_under_resources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "operations-v2").mkdir(parents=True)
            for name, value in {
                "attention-health.json": {"result": "PASS"},
                "reconcile-timer-health.json": {"result": "PASS"},
                "post-change-gate.json": {"status": "PASS"},
                "operational-acceptance.json": {"status": "ACCEPTED"},
            }.items():
                (root / "operations-v2" / name).write_text(json.dumps(value))
            initialize_model_usage_registry(
                root,
                activated_at="2026-10-05T00:00:00+09:00",
                registry_ref="usage-registry:test",
            )
            _process(
                root / "_workspace" / "orchestration-runs" / "r1" / "TASK" / "executor.process.json",
                "2026-10-05T01:00:00+00:00",
                _usage(),
            )
            projection = build_live_operations_dashboard_projection(
                root, now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
            )
            model_usage = projection["system_resources"]["model_usage_cost"]
            self.assertEqual(model_usage["source_state"], MODEL_USAGE_SOURCE_V1)
            self.assertEqual(model_usage["usage"]["input_output_tokens"], 120)
            self.assertEqual(model_usage["cost"]["status"], "UNAVAILABLE")

    def test_registry_cli_init_and_validate(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(registry_main([
                "--state-root", td, "init",
                "--activated-at", "2026-10-05T09:00:00+09:00",
                "--registry-ref", "usage-registry:test",
            ]), 0)
            self.assertEqual(registry_main([
                "--state-root", td, "validate",
            ]), 0)


if __name__ == "__main__":
    unittest.main()

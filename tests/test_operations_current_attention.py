from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.orchestrator.operations_current_attention import (
    CURRENT_ATTENTION_SOURCE_V1,
    CurrentAttentionProjectionError,
    attention_projection_to_dashboard_alerts,
    build_current_attention_projection,
    read_current_attention_projection,
    record_current_attention_projection,
)


NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def blocker() -> dict[str, str]:
    return {
        "project_id": "P",
        "run_id": "R",
        "state": "BLOCKED",
        "kind": "BLOCKED",
        "reason": "RETRY_BUDGET_EXHAUSTED",
        "current_gate": "GATE-001",
        "delivery_class": "DEFERRED_INCIDENT",
        "event_id": "a" * 64,
    }


class OperationsCurrentAttentionTests(unittest.TestCase):
    def test_projection_is_bounded_digest_bound_and_alertable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            value = build_current_attention_projection(
                runtime_source_identity="head:abc",
                blockers=[blocker()],
                observed_at=NOW,
            )
            target = tmp_path / "operations-v2" / "current-attention.json"
            record_current_attention_projection(target, value)
            loaded = read_current_attention_projection(
                tmp_path,
                now=NOW + timedelta(seconds=30),
                expected_runtime_source="head:abc",
            )
            self.assertEqual(loaded["source_state"], CURRENT_ATTENTION_SOURCE_V1)
            self.assertEqual(loaded["items"][0]["reason"], "RETRY_BUDGET_EXHAUSTED")
            alerts = attention_projection_to_dashboard_alerts(loaded)
            self.assertEqual(alerts[0]["severity"], "ERROR")
            self.assertEqual(alerts[0]["kind"], "USER_ATTENTION")

    def test_projection_fails_closed_on_stale_runtime_mismatch_and_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            value = build_current_attention_projection(
                runtime_source_identity="head:abc",
                blockers=[blocker()],
                observed_at=NOW,
            )
            target = tmp_path / "operations-v2" / "current-attention.json"
            record_current_attention_projection(target, value)
            self.assertEqual(
                read_current_attention_projection(
                    tmp_path,
                    now=NOW + timedelta(seconds=181),
                    expected_runtime_source="head:abc",
                )["source_state"],
                "STALE",
            )
            self.assertEqual(
                read_current_attention_projection(
                    tmp_path,
                    now=NOW + timedelta(seconds=30),
                    expected_runtime_source="head:def",
                )["source_state"],
                "RUNTIME_MISMATCH",
            )
            raw = json.loads(target.read_text())
            raw["items"][0]["reason"] = "tampered"
            target.write_text(json.dumps(raw))
            self.assertEqual(
                read_current_attention_projection(
                    tmp_path,
                    now=NOW + timedelta(seconds=30),
                    expected_runtime_source="head:abc",
                )["source_state"],
                "INVALID",
            )

    def test_projection_contains_no_control_authority_or_raw_payload(self):
        value = build_current_attention_projection(
            runtime_source_identity="head:abc",
            blockers=[{
                **blocker(),
                "control_authority": "MUST_NOT_LEAK",
                "raw_payload": {"secret": "MUST_NOT_LEAK"},
            }],
            observed_at=NOW,
        )
        encoded = json.dumps(value, sort_keys=True)
        self.assertNotIn("MUST_NOT_LEAK", encoded)
        self.assertNotIn("control_authority", encoded)
        self.assertNotIn("raw_payload", encoded)

    def test_projection_rejects_unsafe_output_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            value = build_current_attention_projection(
                runtime_source_identity="head:abc",
                blockers=[blocker()],
                observed_at=NOW,
            )
            real = tmp_path / "real.json"
            real.write_text("{}")
            link = tmp_path / "attention.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(CurrentAttentionProjectionError, "unsafe"):
                record_current_attention_projection(link, value)

    def test_current_attention_public_reason_redacts_secret_and_home_path(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ, {"SAMPLE_API_TOKEN": "supersecret123"}
        ):
            tmp_path = Path(td)
            projection = build_current_attention_projection(
                runtime_source_identity="runtime:new",
                blockers=[{
                    "project_id": "P",
                    "run_id": "R",
                    "state": "BLOCKED",
                    "kind": "FAIL",
                    "reason": "token=supersecret123 failed at /home/ywjo/private/file.txt",
                }],
            )
            reason = projection["items"][0]["reason"]
            self.assertNotIn("supersecret123", reason)
            self.assertNotIn("/home/ywjo", reason)
            self.assertIn("<redacted>", reason)
            self.assertIn("<path>", reason)


if __name__ == "__main__":
    unittest.main()

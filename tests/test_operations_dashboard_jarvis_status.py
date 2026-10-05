from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.operations_dashboard_jarvis_status import (
    CANONICAL_SOURCE,
    read_operations_dashboard_jarvis_status,
)
from runtime.orchestrator.operations_dashboard_source import build_live_operations_dashboard_projection

HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def snapshot(stamp="2026-10-05T07:00:00+00:00", head=HEAD):
    value = {
        "schema_version": "jarvis.memory-llmwiki-compact-status.v1",
        "producer_source_head": head,
        "generated_at": stamp,
        "memory": "AVAILABLE",
        "llmwiki": "AVAILABLE",
        "memory_read_only": True,
        "llmwiki_read_only": True,
        "write_policy": "APPROVAL_REQUIRED",
        "raw_text_included": False,
        "source_state": CANONICAL_SOURCE,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value["status_sha256"] = hashlib.sha256(raw).hexdigest()
    return value


def write_snapshot(root, value):
    path = Path(root) / "operations-v2" / "jarvis-memory-compact-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


class JarvisCompactStatusAdapterTests(unittest.TestCase):
    def test_missing_snapshot_is_unbound(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(read_operations_dashboard_jarvis_status(td))

    def test_fresh_valid_snapshot_projects_only_bounded_fields(self):
        with tempfile.TemporaryDirectory() as td:
            write_snapshot(td, snapshot())
            value = read_operations_dashboard_jarvis_status(
                td,
                now=datetime(2026, 10, 5, 7, 1, tzinfo=timezone.utc),
                expected_producer_head=HEAD,
            )
            self.assertEqual(value, {
                "webapp": "UNKNOWN",
                "memory": "AVAILABLE",
                "llmwiki": "AVAILABLE",
                "source_state": CANONICAL_SOURCE,
            })

    def test_expected_head_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            write_snapshot(td, snapshot())
            value = read_operations_dashboard_jarvis_status(
                td,
                now=datetime(2026, 10, 5, 7, 1, tzinfo=timezone.utc),
                expected_producer_head=OTHER_HEAD,
            )
            self.assertEqual(value["memory"], "UNAVAILABLE")
            self.assertEqual(value["llmwiki"], "UNAVAILABLE")
            self.assertEqual(value["source_state"], "MISMATCH_JARVIS_MEMORY_COMPACT_V1")

    def test_stale_snapshot_fails_closed_without_breaking_dashboard(self):
        with tempfile.TemporaryDirectory() as td:
            write_snapshot(td, snapshot())
            value = read_operations_dashboard_jarvis_status(
                td, now=datetime(2026, 10, 5, 7, 10, tzinfo=timezone.utc)
            )
            self.assertEqual(value["memory"], "UNAVAILABLE")
            self.assertEqual(value["llmwiki"], "UNAVAILABLE")
            self.assertEqual(value["source_state"], "STALE_JARVIS_MEMORY_COMPACT_V1")

    def test_tampered_snapshot_is_invalid_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            value = snapshot()
            value["memory"] = "UNAVAILABLE"
            write_snapshot(td, value)
            projected = read_operations_dashboard_jarvis_status(
                td, now=datetime(2026, 10, 5, 7, 1, tzinfo=timezone.utc)
            )
            self.assertEqual(projected["source_state"], "INVALID_JARVIS_MEMORY_COMPACT_V1")
            self.assertEqual(projected["memory"], "UNAVAILABLE")

    def test_symlink_snapshot_is_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "real.json"
            real.write_text(json.dumps(snapshot()))
            path = root / "operations-v2" / "jarvis-memory-compact-status.json"
            path.parent.mkdir()
            path.symlink_to(real)
            projected = read_operations_dashboard_jarvis_status(td)
            self.assertEqual(projected["source_state"], "INVALID_JARVIS_MEMORY_COMPACT_V1")

    def test_live_projection_consumes_compact_status(self):
        with tempfile.TemporaryDirectory() as td:
            write_snapshot(td, snapshot())
            projection = build_live_operations_dashboard_projection(
                td, now=datetime(2026, 10, 5, 7, 1, tzinfo=timezone.utc)
            )
            self.assertEqual(projection["jarvis_status"]["memory"], "AVAILABLE")
            self.assertEqual(projection["jarvis_status"]["llmwiki"], "AVAILABLE")
            self.assertEqual(projection["jarvis_status"]["source_state"], CANONICAL_SOURCE)


if __name__ == "__main__":
    unittest.main()

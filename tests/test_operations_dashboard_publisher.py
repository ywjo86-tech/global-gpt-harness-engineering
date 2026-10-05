from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone


from runtime.orchestrator.operations_dashboard_projection import (
    build_operations_dashboard_projection,
)
from runtime.orchestrator.operations_dashboard_publisher import (
    OperationsDashboardPublisherError,
    publish_operations_dashboard_projection,
)


def _projection():
    return build_operations_dashboard_projection(
        [],
        system_health={
            "attention": "PASS",
            "reconcile": "PASS",
            "post_change": "PASS",
            "acceptance": "ACCEPTED",
        },
        system_resources={
            "cpu_percent": 10,
            "memory_percent": 20,
            "storage_percent": 30,
            "source": "fixture",
        },
        now=datetime(2026, 10, 4, 5, tzinfo=timezone.utc),
    )


class OperationsDashboardPublisherTests(unittest.TestCase):
    def test_publisher_writes_verified_projection_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "operations-v2" / "ai-office-dashboard-v2.json"
            value = _projection()

            result = publish_operations_dashboard_projection(value, output_path=output)

            self.assertEqual(result, output)
            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(loaded, value)
            self.assertFalse(list(output.parent.glob(output.name + ".*")))

    def test_publisher_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "real.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "dashboard.json"
            link.symlink_to(target)

            with self.assertRaisesRegex(OperationsDashboardPublisherError, "symlink"):
                publish_operations_dashboard_projection(_projection(), output_path=link)

    def test_publisher_rejects_tampered_projection(self):
        value = _projection()
        value["summary"]["issues"] = 7

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(
                OperationsDashboardPublisherError,
                "digest mismatch",
            ):
                publish_operations_dashboard_projection(
                    value,
                    output_path=Path(td) / "dashboard.json",
                )


if __name__ == "__main__":
    unittest.main()

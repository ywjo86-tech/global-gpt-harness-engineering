from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.operations_dashboard_projection import (
    build_operations_dashboard_projection,
)
from runtime.orchestrator.operations_dashboard_publication import (
    DASHBOARD_PUBLICATION_RECEIPT_SCHEMA_V1,
    DASHBOARD_PUBLISHER_COMPONENT,
    OperationsDashboardPublicationError,
    build_dashboard_publication_receipt,
    publish_operations_dashboard_bundle,
    validate_dashboard_publication_receipt,
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
        now=datetime(
            2026, 10, 5, 0, tzinfo=timezone.utc
        ),
    )


class OperationsDashboardPublicationTests(unittest.TestCase):
    def test_receipt_binds_projection_and_publisher(self):
        projection = _projection()
        receipt = build_dashboard_publication_receipt(
            projection,
            publisher_source_head="a" * 40,
            published_at=datetime(
                2026, 10, 5, 0, 1, tzinfo=timezone.utc
            ),
        )
        self.assertEqual(
            receipt["schema_version"],
            DASHBOARD_PUBLICATION_RECEIPT_SCHEMA_V1,
        )
        self.assertEqual(
            receipt["publisher_component"],
            DASHBOARD_PUBLISHER_COMPONENT,
        )
        self.assertEqual(
            receipt["publisher_source_head"],
            "a" * 40,
        )
        self.assertEqual(
            receipt["projection_sha256"],
            projection["projection_sha256"],
        )
        validate_dashboard_publication_receipt(
            receipt,
            projection=projection,
        )

    def test_receipt_digest_tamper_is_rejected(self):
        receipt = build_dashboard_publication_receipt(
            _projection(),
            publisher_source_head="a" * 40,
        )
        receipt["publisher_source_head"] = "b" * 40
        with self.assertRaisesRegex(
            OperationsDashboardPublicationError,
            "digest mismatch",
        ):
            validate_dashboard_publication_receipt(receipt)

    def test_receipt_projection_binding_mismatch_is_rejected(self):
        first = _projection()
        second = json.loads(json.dumps(first))
        second["generated_at"] = (
            "2026-10-05T00:02:00+00:00"
        )
        unsigned = {
            key: value
            for key, value in second.items()
            if key != "projection_sha256"
        }
        import hashlib
        second["projection_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        receipt = build_dashboard_publication_receipt(
            first,
            publisher_source_head="a" * 40,
        )
        with self.assertRaisesRegex(
            OperationsDashboardPublicationError,
            "binding mismatch",
        ):
            validate_dashboard_publication_receipt(
                receipt,
                projection=second,
            )

    def test_bundle_writes_projection_then_bound_receipt(self):
        projection = _projection()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "dashboard.json"
            p, r = publish_operations_dashboard_bundle(
                projection,
                output_path=output,
                publisher_source_head="a" * 40,
            )
            self.assertEqual(p, output)
            self.assertTrue(p.is_file())
            self.assertTrue(r.is_file())
            loaded_projection = json.loads(
                p.read_text(encoding="utf-8")
            )
            loaded_receipt = json.loads(
                r.read_text(encoding="utf-8")
            )
            validate_dashboard_publication_receipt(
                loaded_receipt,
                projection=loaded_projection,
            )

    def test_bundle_rejects_symlink_receipt(self):
        projection = _projection()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "real.json"
            real.write_text("{}", encoding="utf-8")
            receipt = root / "receipt.json"
            receipt.symlink_to(real)
            with self.assertRaisesRegex(
                OperationsDashboardPublicationError,
                "symlink",
            ):
                publish_operations_dashboard_bundle(
                    projection,
                    output_path=root / "dashboard.json",
                    receipt_path=receipt,
                    publisher_source_head="a" * 40,
                )


if __name__ == "__main__":
    unittest.main()

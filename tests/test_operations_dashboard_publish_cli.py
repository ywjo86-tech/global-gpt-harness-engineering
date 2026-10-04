from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operations_dashboard_publication import (
    validate_dashboard_publication_receipt,
)
from runtime.orchestrator.operations_dashboard_publish_cli import (
    main,
)


class OperationsDashboardPublishCliTests(unittest.TestCase):
    def test_cli_publishes_projection_and_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state"
            state.mkdir()
            output = root / "dashboard.json"
            receipt = root / "dashboard.receipt.json"

            code = main(
                [
                    "--state-root",
                    str(state),
                    "--publisher-source-head",
                    "a" * 40,
                    "--output",
                    str(output),
                    "--receipt-output",
                    str(receipt),
                ]
            )

            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())
            self.assertTrue(receipt.is_file())
            projection = json.loads(
                output.read_text(encoding="utf-8")
            )
            publication = json.loads(
                receipt.read_text(encoding="utf-8")
            )
            self.assertEqual(
                projection["source_contract"],
                "orchestration.operations-dashboard-aggregate.v2",
            )
            validate_dashboard_publication_receipt(
                publication,
                projection=projection,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poc.graphify.comparator import Scenario, run_comparison
from poc.graphify.contracts import ProviderResult

SHA = "4" * 40


class _Provider:
    def __init__(self, provider_id: str, source_files: tuple[str, ...]):
        self.provider_id = provider_id
        self.source_files = source_files

    def query(self, request):
        return ProviderResult(
            self.provider_id,
            request.scenario_id,
            request.source_ref,
            "completed",
            " ".join(self.source_files),
            source_files=self.source_files,
            confidence="EXTRACTED" if self.provider_id == "graphify" else "CANONICAL",
        )


class GraphifyComparatorTests(unittest.TestCase):
    def test_comparison_preserves_negative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "runtime" / "x.py"
            source.parent.mkdir(parents=True)
            source.write_text("x=1\n")
            report = run_comparison(
                _Provider("graphify", ("runtime/x.py",)),
                _Provider("existing_inspection", ()),
                [Scenario("S1", "x", "runtime/x.py")],
                source_ref=SHA,
                source_root=root,
            )
            self.assertEqual(report["metrics"]["graphify"]["verified_count"], 1)
            self.assertEqual(report["metrics"]["existing_inspection"]["verified_count"], 0)
            self.assertEqual(len(report["negative_evidence"]), 1)


if __name__ == "__main__":
    unittest.main()

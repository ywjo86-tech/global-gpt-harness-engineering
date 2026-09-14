from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poc.graphify.canonical_verifier import verify_graph_manifest, verify_provider_result
from poc.graphify.contracts import ProviderResult

SHA = "3" * 40


class CanonicalVerifierTests(unittest.TestCase):
    def test_expected_source_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "runtime" / "x.py"
            source.parent.mkdir(parents=True)
            source.write_text("x=1\n")
            result = ProviderResult(
                "graphify", "S", SHA, "completed", "runtime/x.py",
                source_files=("runtime/x.py",),
            )
            record = verify_provider_result(
                result, expected_source="runtime/x.py",
                expected_source_ref=SHA, source_root=root,
            )
            self.assertTrue(record["verified"])

    def test_stale_or_missing_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = ProviderResult(
                "graphify", "S", SHA, "completed", "", freshness_state="STALE"
            )
            record = verify_provider_result(
                result, expected_source="missing.py",
                expected_source_ref=SHA, source_root=temp_dir,
            )
            self.assertFalse(record["verified"])
            self.assertIn("stale_or_unknown_result", record["reasons"])

    def test_graph_manifest_requires_all_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps({"a.py": {"ast_hash": "x"}}))
            self.assertTrue(
                verify_graph_manifest(path, required_sources=["a.py"])["freshness_verified"]
            )
            self.assertFalse(
                verify_graph_manifest(path, required_sources=["a.py", "b.py"])["freshness_verified"]
            )


if __name__ == "__main__":
    unittest.main()

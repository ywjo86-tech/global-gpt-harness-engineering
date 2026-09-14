from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.graphify.baseline_adapter import ExistingInspectionAdapter
from poc.graphify.contracts import ProviderQueryRequest, ProviderResult
from poc.graphify.graphify_adapter import GraphifyAdapter

SHA = "2" * 40


class GraphifyAdapterContractTests(unittest.TestCase):
    def test_request_requires_canonical_source_ref(self) -> None:
        with self.assertRaises(ValueError):
            ProviderQueryRequest("s1", "find symbol", "bad").validate()

    def test_provider_result_rejects_write(self) -> None:
        with self.assertRaises(ValueError):
            ProviderResult(
                "graphify", "s1", SHA, "completed", "x", write_performed=True
            ).validate()

    def test_graphify_adapter_normalizes_read_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cli = root / "graphify"
            graph = root / "graph.json"
            cli.write_text("stub")
            graph.write_text("{}")
            captured = {}
            def runner(command, **kwargs):
                captured["command"] = command
                captured["env"] = kwargs["env"]
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="NODE x [src=runtime/orchestrator/provider_router.py loc=L1]\n",
                    stderr="",
                )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "secret"}):
                adapter = GraphifyAdapter(
                    cli, graph, isolated_home=root / "home", runner=runner
                )
                result = adapter.query(
                    ProviderQueryRequest("s1", "provider router", SHA, 500)
                )
            self.assertEqual(result.provider_id, "graphify")
            self.assertFalse(result.write_performed)
            self.assertEqual(
                result.source_files, ("runtime/orchestrator/provider_router.py",)
            )
            self.assertNotIn("OPENAI_API_KEY", captured["env"])
            self.assertEqual(captured["command"][1], "query")

    def test_existing_inspection_adapter_preserves_no_write(self) -> None:
        report = {
            "inspection_mode": "read_only_no_write",
            "write_operations_performed": False,
            "project_static_inspect": {"current_phase": "X"},
        }
        with patch("poc.graphify.baseline_adapter.inspect_read_only", return_value=report):
            result = ExistingInspectionAdapter(".").query(
                ProviderQueryRequest("s2", "current phase", SHA)
            )
        self.assertEqual(result.provider_id, "existing_inspection")
        self.assertFalse(result.write_performed)
        self.assertEqual(result.confidence, "CANONICAL")


if __name__ == "__main__":
    unittest.main()

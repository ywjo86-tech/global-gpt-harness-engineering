from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.contract_adapter import load_project_mapping, validate_mapping_sources
from runtime.orchestrator.gate_orchestrator import load_gate_plan, onboarding_dry_run

ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_PLAN = (
    ROOT / "docs/history/upgrades/2026-09-18-AI-OFFICE-HARNESS-PH5/"
    "DEVELOPMENT_PLAN.pre-AI-OFFICE-HARNESS-PH5.7a5758cae4976ade902ffd4cde920cddea9390c7fb25fbc33eb7b3854604601f.txt"
)
HISTORICAL_MAPPING = ROOT / "runtime/orchestrator/contract_mappings/MULTI_PROVIDER_FOUNDATION.json"


def historical_mapping_root(directory: str) -> Path:
    root = Path(directory).resolve()
    payload = json.loads(HISTORICAL_MAPPING.read_text(encoding="utf-8"))
    archived = ARCHIVED_PLAN.relative_to(ROOT).as_posix()
    payload["canonical_implementation_source"]["path"] = archived
    payload["approved_source_reference"]["path"] = archived
    payload["contract_paths"]["development_plan"] = archived
    (root / "MULTI_PROVIDER_FOUNDATION.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return root


class MultiProviderFullPlanOnboardingTests(unittest.TestCase):
    def test_historical_project_mapping_and_required_contracts_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mapping_root = historical_mapping_root(td)
            with patch.dict(os.environ, {"HARNESS_CONTRACT_MAPPING_ROOT": str(mapping_root)}, clear=False):
                result = onboarding_dry_run(ROOT, "MULTI_PROVIDER_FOUNDATION")
                self.assertTrue(result["contract_files_ready"], result)
                self.assertTrue(result["mapping_registered"], result)
                self.assertTrue(result["mapping_ready"], result)
                self.assertEqual(result["missing_contracts"], [])
                mapping = load_project_mapping(ROOT)
                self.assertIsNotNone(mapping)
                assert mapping is not None
                self.assertEqual(validate_mapping_sources(mapping), [])
                self.assertEqual(mapping.project_id, "MULTI_PROVIDER_FOUNDATION")
                self.assertEqual(mapping.canonical_source, ARCHIVED_PLAN.resolve())

    def test_historical_remaining_gates_project_exact_task_order(self) -> None:
        expected = {
            "GATE-008": ["TASK-010", "TASK-011", "TASK-012", "TASK-013", "TASK-014"],
            "GATE-009": ["TASK-015"],
            "GATE-010": ["TASK-016"],
        }
        with tempfile.TemporaryDirectory() as td:
            mapping_root = historical_mapping_root(td)
            with patch.dict(os.environ, {"HARNESS_CONTRACT_MAPPING_ROOT": str(mapping_root)}, clear=False):
                for gate_id, tasks in expected.items():
                    with self.subTest(gate_id=gate_id):
                        plan = load_gate_plan(ROOT, gate_id)
                        self.assertEqual([item.lv_id for item in plan.lvs], tasks)
                        self.assertTrue(all(item.required_capabilities for item in plan.lvs))
                        self.assertTrue(all(item.owned_files for item in plan.lvs))


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import GateLV, GatePlan
from runtime.orchestrator.production_resume import (
    ResumeBridgeError, build_resume_bridge, validate_resume_bridge,
)


class ProductionResumeBridgeTests(unittest.TestCase):
    def _plan(self):
        return GatePlan("project", "", "GATE-1", "IMPLEMENTATION_PLAN.md", "a" * 64, [
            GateLV("GATE-1", "LV-1", 1, "one", [], [], [], "sequential", []),
            GateLV("GATE-1", "LV-2", 2, "two", [], [], [], "sequential", []),
        ])

    def test_bridge_promotes_immutable_evidence_and_finds_first_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = root / "_workspace/orchestration-runs/run-1"; run.mkdir(parents=True)
            manifest = {"gate_id": "GATE-1", "lv_id": "LV-1", "canonical_plan_sha256": "a" * 64}
            (run / "package.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            review = root / "_workspace/orchestration-results/run-1"; review.mkdir(parents=True)
            (review / "reviewer.report.json").write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
            with patch("runtime.orchestrator.production_resume.load_gate_plan", return_value=self._plan()):
                bridge = build_resume_bridge(root, root, "GATE-1", plan_sha256="a" * 64)
            self.assertEqual(bridge["first_incomplete_lv"], "LV-2")
            self.assertEqual(bridge["completed"][0]["status"], "COMPLETE")
            self.assertTrue(validate_resume_bridge(bridge, project_id="project", gate_id="GATE-1", plan_sha256="a" * 64))

    def test_tampered_bridge_is_rejected(self):
        with self.assertRaises(ResumeBridgeError):
            validate_resume_bridge({"schema_version": "orchestration.production-resume-bridge.v1",
                                    "project_id": "project", "gate_id": "GATE-1", "plan_sha256": "a" * 64,
                                    "completed": [], "remaining": [], "first_incomplete_lv": None,
                                    "source_immutable": True, "bridge_sha256": "0" * 64},
                                   project_id="project", gate_id="GATE-1", plan_sha256="a" * 64)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class HarnessStateRootTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("runtime.orchestrator.harness_state_root")
        except ModuleNotFoundError as exc:
            self.fail(f"stable state-root module is missing: {exc}")

    def test_default_state_root_is_not_project_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); project = base / "project"; project.mkdir()
            old_gch = os.environ.pop("GCH_STATE_ROOT", None)
            old_xdg = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = str(base / "state")
            try:
                root = self.api().resolve_harness_state_root(project_root=project)
            finally:
                if old_gch is not None: os.environ["GCH_STATE_ROOT"] = old_gch
                if old_xdg is None: os.environ.pop("XDG_STATE_HOME", None)
                else: os.environ["XDG_STATE_HOME"] = old_xdg
            self.assertEqual(root, (base / "state/global-gpt-harness").resolve())
            self.assertNotEqual(root, project.resolve())

    def test_gch_state_root_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); project = base / "project"; project.mkdir()
            chosen = base / "durable"
            env = {"GCH_STATE_ROOT": str(chosen), "XDG_STATE_HOME": str(base / "ignored")}
            root = self.api().resolve_harness_state_root(project_root=project, environ=env)
            self.assertEqual(root, chosen.resolve())

    def test_worktree_nested_state_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d) / "project"; project.mkdir()
            with self.assertRaisesRegex(ValueError, "independent of project worktree"):
                self.api().resolve_harness_state_root(
                    project_root=project, environ={"GCH_STATE_ROOT": str(project / ".state")})

    def test_symlinked_state_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); project = base / "project"; project.mkdir()
            real = base / "real"; real.mkdir(); link = base / "state-link"; link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.api().resolve_harness_state_root(project_root=project, environ={"GCH_STATE_ROOT": str(link)})

    def test_job_state_root_preserves_legacy_fallback(self):
        api = self.api()
        legacy = {"harness_root": "/tmp/legacy"}
        modern = {"harness_root": "/tmp/runtime", "harness_state_root": "/tmp/state"}
        self.assertEqual(api.job_state_root(legacy), Path("/tmp/legacy").resolve())
        self.assertEqual(api.job_state_root(modern), Path("/tmp/state").resolve())

    def test_discovery_deduplicates_stable_and_legacy_by_authority(self):
        from runtime.orchestrator.production_full_plan_boot import discover_registered_jobs
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); stable = base / "stable"; legacy = base / "legacy"
            for root in (stable, legacy):
                path = root / "_workspace/production-full-plan-jobs/P/R.job.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({
                    "schema_version": "orchestration.production-full-plan-job.v1",
                    "project_root": str(base), "harness_root": str(legacy),
                    "harness_state_root": str(stable), "project_id": "P", "run_id": "R",
                    "authority_core_sha256": "a" * 64,
                    "gates": [{"gate_id":"G","approval_evidence":"a","requirements_sha256":"b"*64,"branch":"main","head":"c"*40,"full_plan_opt_in":True,"project_final_validation":True}],
                }))
            rows = discover_registered_jobs(stable, legacy_roots=(legacy,))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].resolve(), (stable / "_workspace/production-full-plan-jobs/P/R.job.json").resolve())


if __name__ == "__main__":
    unittest.main()

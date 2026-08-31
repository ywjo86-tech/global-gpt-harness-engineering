import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_decision import ProductionDecisionError, build_production_decision


def write(path: Path, value: dict, sidecar: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(data); digest = hashlib.sha256(data).hexdigest()
    if sidecar: path.with_suffix(".sha256").write_text(digest)
    return digest


class ProductionDecisionTests(unittest.TestCase):
    def fixture(self, root: Path, *, attempt: int = 1):
        project = root / "project"; project.mkdir()
        subprocess.run(["git", "init", "-q", project], check=True)
        subprocess.run(["git", "-C", project, "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", project, "config", "user.name", "Fixture"], check=True)
        (project / "base").write_text("base"); subprocess.run(["git", "-C", project, "add", "base"], check=True)
        subprocess.run(["git", "-C", project, "commit", "-qm", "base"], check=True)
        (project / "app").mkdir(); (project / "tests").mkdir()
        (project / "app/a.py").write_text("x"); (project / "tests/test_a.py").write_text("x")
        run="fixture-run"; lv="L1"; art=root/"_workspace/orchestration-runs"/run/lv
        package={"project_id":"fixture","gate_id":"G1","lv_id":lv,"run_id":run,
                 "owned_files":["app/a.py","tests/test_a.py"]}
        package_sha=write(art/"package.manifest.json",package,True)
        preflight={"project_id":"fixture","gate_id":"G1","lv_id":lv,"run_id":run}
        preflight_sha=write(art/"preflight/preflight.evidence.json",preflight,True)
        request={"extra_context":{"gate_id":"G1","lv_id":lv,"run_id":run,"attempt":attempt,
                 "package_manifest_sha256":package_sha,"preflight_evidence_sha256":preflight_sha}}
        write(art/"worker.request.json",request)
        args=dict(project_root=project,harness_root=root,project_id="fixture",gate_id="G1",run_id=run,
                  mode="GATE_BY_GATE",current_lv=lv,inherited_completed_lvs=["L0"],remaining_lvs=[lv,"L2"])
        return args, art

    def test_official_adoption_decision_and_inheritance(self):
        with tempfile.TemporaryDirectory() as d:
            args,_=self.fixture(Path(d)); out=build_production_decision(**args)
            self.assertEqual(out["selected_action"],"OFFICIAL_PARTIAL_ADOPTION")
            self.assertEqual(out["recovery_state"],"TERMINATED_ADOPTABLE_PARTIAL")
            self.assertEqual(out["inherited_completed_lvs"],["L0"]); self.assertFalse(out["mutation_performed"])

    def test_live_worker_waits_and_blocks_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            args,art=self.fixture(Path(d)); write(art/"executor.process.json",{"pid":123,"started_at":"same"})
            with patch("runtime.orchestrator.production_decision._process_state",return_value=("LIVE",True)):
                out=build_production_decision(**args)
            self.assertEqual(out["selected_action"],"WAIT_EXISTING_WORKER"); self.assertTrue(out["duplicate_worker_detected"]); self.assertTrue(out["duplicate_worker_blocked"])

    def test_stale_process_is_not_live(self):
        with tempfile.TemporaryDirectory() as d:
            args,art=self.fixture(Path(d)); write(art/"executor.process.json",{"pid":123,"started_at":"old"})
            with patch("runtime.orchestrator.production_decision._process_state",return_value=("STALE",False)):
                out=build_production_decision(**args)
            self.assertEqual(out["worker_process_state"],"STALE"); self.assertFalse(out["duplicate_worker_detected"])

    def test_invalid_scope_and_attempt_fail(self):
        with tempfile.TemporaryDirectory() as d:
            args,_=self.fixture(Path(d)); (Path(args["project_root"])/"outside").write_text("x")
            with self.assertRaisesRegex(ProductionDecisionError,"owned scope"): build_production_decision(**args)
        with tempfile.TemporaryDirectory() as d:
            args,_=self.fixture(Path(d),attempt=0)
            with self.assertRaisesRegex(ProductionDecisionError,"attempt"): build_production_decision(**args)

    def test_zero_write_and_no_bound_identifiers_in_source(self):
        with tempfile.TemporaryDirectory() as d:
            args,_=self.fixture(Path(d)); root=Path(d)
            before={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            first=build_production_decision(**args); second=build_production_decision(**args)
            after={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before,after); self.assertEqual(first,second)
        source=Path("runtime/orchestrator/production_decision.py").read_text()
        self.assertNotIn("wallet-gate1",source); self.assertNotIn("deduplicator.py",source)

    def test_clean_restart_replays_bound_worker_result(self):
        with tempfile.TemporaryDirectory() as d:
            args,art=self.fixture(Path(d)); project=Path(args["project_root"])
            subprocess.run(["git","-C",str(project),"add","app/a.py","tests/test_a.py"],check=True)
            subprocess.run(["git","-C",str(project),"commit","-qm","checkpoint"],check=True)
            write(art/"worker.result.json",{"project_id":"fixture","gate_id":"G1","lv_id":"L1","run_id":"fixture-run"})
            out=build_production_decision(**args)
            self.assertEqual(out["selected_action"],"REPLAY_SEALED_WORKER_RESULT")
            self.assertEqual(out["recovery_state"],"ADOPTION_CHECKPOINTED")

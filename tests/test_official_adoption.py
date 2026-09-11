import tempfile,unittest
from pathlib import Path
from tests.test_production_lifecycle import binding
from runtime.orchestrator.persisted_artifact import publish
from runtime.orchestrator.official_adoption import OfficialAdoptionError,official_adopt,reconcile_and_resume
from runtime.orchestrator.cli import official_partial_adoption_entry
from runtime.orchestrator.cli import main as cli_main
from runtime.orchestrator.gate_supervisor import PersistentGateSupervisor

SRC="a"*64;PRE="b"*64
class OfficialAdoptionTests(unittest.TestCase):
 def setup(self,d):
  control=Path(d)/"control";art=Path(d)/"artifacts"
  for name,kind in (("package.json","package"),("preflight.json","preflight"),("worker.request.json","worker_request")):publish(art,name,kind=kind,payload={"status":"READY"},binding=binding(),source_artifact_sha256=SRC,predecessor_digest=PRE)
  return dict(control_root=control,artifact_root=art,binding=binding(),run_id="run",recorded_pid=7,recorded_start="old",process_probe=lambda p:None,diff={"app/a.py":"x"},owned_scope=["app/a.py"],source_sha256=SRC,predecessor=PRE,result_payload={"status":"completed"})
 def test_cli_to_controller_official_path_and_duplicate_idempotency(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);self.assertEqual(official_partial_adoption_entry(**kw)["status"],"REVIEW_PENDING");self.assertTrue(official_partial_adoption_entry(**kw)["idempotent"])
 def test_actual_argparse_cli_command_reaches_adoption(self):
  import json
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);kw.pop("process_probe");kw["process_status"]="terminated";kw["control_root"]=str(kw["control_root"]);kw["artifact_root"]=str(kw["artifact_root"]);p=Path(d)/"request.json";p.write_text(json.dumps(kw))
   self.assertEqual(cli_main(["production-adopt-partial","--request",str(p)]),0)
 def test_supervisor_reaches_same_official_path(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);s=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="GATE_BY_GATE",lv_order=["l"]);self.assertEqual(s.adopt_terminated_partial(**kw)["status"],"REVIEW_PENDING")
 def test_canonical_then_alias_failure_is_invisible_and_restart_reconciles(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d)
   with self.assertRaises(OfficialAdoptionError):official_adopt(**kw,failpoint="after_canonical")
   self.assertFalse((Path(d)/"control/review.queue.json").exists());self.assertEqual(reconcile_and_resume(**kw)["status"],"REVIEW_PENDING")
 def test_reconciliation_revalidates_canonical_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d)
   with self.assertRaises(OfficialAdoptionError):official_adopt(**kw,failpoint="after_canonical")
   (Path(d)/"control/publication-01/worker.result.json").write_text("{}")
   with self.assertRaises(Exception):reconcile_and_resume(**kw)
 def test_alias_without_canonical_and_conflicting_alias_fail(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);root=Path(d)/"control";root.mkdir();(root/"worker.result.current.json").write_text('{}')
   with self.assertRaises(OfficialAdoptionError):official_adopt(**kw)
 def test_live_stale_pid_scope_and_review_ordering(self):
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);kw["process_probe"]=lambda p:"old"
   with self.assertRaisesRegex(OfficialAdoptionError,"live"):official_adopt(**kw)
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);kw["diff"]={"bad":"x"}
   with self.assertRaisesRegex(OfficialAdoptionError,"scope"):official_adopt(**kw)
  with tempfile.TemporaryDirectory() as d:
   kw=self.setup(d);official_adopt(**kw);self.assertTrue((Path(d)/"control/publication-01/COMMITTED").is_file());self.assertTrue((Path(d)/"control/review.queue.json").is_file())

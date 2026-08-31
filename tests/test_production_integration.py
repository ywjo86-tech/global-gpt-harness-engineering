import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_production_lifecycle import binding
from runtime.orchestrator.persisted_artifact import publish
from runtime.orchestrator.production_context import ProductionContextBuilder,build_production_context
from runtime.orchestrator.production_worker_executor import _prompt
from runtime.orchestrator.schemas import TaskSlice,WorkerRequest
from runtime.orchestrator.lv_review import build_bounded_review_context
from runtime.orchestrator.contract_loader import load_contract

SRC="a"*64;PRE="b"*64
class ProductionIntegrationTests(unittest.TestCase):
 def artifacts(self,d):
  root=Path(d)/"art";publish(root,"a.json",kind="package",payload={"summary":"full immutable body"*50},binding=binding(),source_artifact_sha256=SRC,predecessor_digest=PRE);publish(root,"b.json",kind="review",payload={"summary":"checkpoint","review_evidence":["PASS"]},binding=binding(),source_artifact_sha256=SRC,predecessor_digest=PRE)
  return root,[{"path":"a.json","kind":"package","lv_id":"done"},{"path":"b.json","kind":"review","lv_id":"next","checkpoint_summary":"cp"}]
 def test_actual_format_project_fixtures_are_temporary_and_sources_unchanged(self):
  harness=Path(__file__).resolve().parents[1];mapping=next((harness/"runtime/orchestrator/contract_mappings").glob("*.json"));spec=json.loads(mapping.read_text());source=harness.parent/spec["project_id"]
  second=next(p for p in harness.parent.iterdir() if p!=source and (p/"AGENTS.md").is_file() and (p/"docs/DEVELOPMENT_PLAN.txt").is_file())
  candidates=[(source,Path(spec["canonical_implementation_source"]["path"])),(second,Path("docs/DEVELOPMENT_PLAN.txt"))]
  before=[]
  with tempfile.TemporaryDirectory() as d:
   for index,(root,relative) in enumerate(candidates):
    raw=(root/relative).read_bytes();before.append((root/relative,hashlib.sha256(raw).hexdigest()));target=Path(d)/f"fixture-{index}";(target/"docs/harness").mkdir(parents=True);(target/"logs").mkdir();(target/"AGENTS.md").write_bytes((root/"AGENTS.md").read_bytes());(target/"docs/DEVELOPMENT_PLAN.txt").write_bytes(raw);(target/"CHANGELOG.txt").write_text("fixture\n");(target/"logs/app.log").write_text("");(target/"docs/harness/orchestration-state.md").write_text("Current phase: Gate 1\n");self.assertTrue(load_contract(target,strict=True).development_plan_text)
   new=Path(d)/"new";(new/"docs/harness").mkdir(parents=True);(new/"logs").mkdir();(new/"AGENTS.md").write_text("fixture\n");(new/"docs/DEVELOPMENT_PLAN.txt").write_text("Current phase: Gate 1\n");(new/"CHANGELOG.txt").write_text("fixture\n");(new/"logs/app.log").write_text("");(new/"docs/harness/orchestration-state.md").write_text("Current phase: Gate 1\n");self.assertEqual(load_contract(new,strict=True).current_phase,"Gate 1")
  for path,digest in before:self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
 def test_production_builder_dedup_completed_cache_and_invalidation(self):
  with tempfile.TemporaryDirectory() as d:
   root,index=self.artifacts(d);builder=ProductionContextBuilder();args=dict(artifact_root=root,index=index,binding=binding(),source_sha256=SRC,predecessor=PRE,completed_lvs=["done"],audience="worker")
   first=builder.build(**args);second=builder.build(**args)
   self.assertEqual(len(first["artifacts"]),1);self.assertGreater(second["metrics"]["cache_hits"],0);self.assertNotIn("full immutable body",json.dumps(first));self.assertLess(first["metrics"]["bytes"],1000)
   with self.assertRaises(Exception):builder.build(**{**args,"binding":binding(current_head="c"*40)})
 def test_validation_failure_bypasses_cache_and_rechecks_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   root,index=self.artifacts(d);b=ProductionContextBuilder();args=dict(artifact_root=root,index=index,binding=binding(),source_sha256=SRC,predecessor=PRE,completed_lvs=["done"],audience="reviewer");b.build(**args);(root/"b.json").write_text("{}")
   with self.assertRaises(Exception):b.build(**args)
 def test_worker_production_prompt_invokes_same_builder(self):
  with tempfile.TemporaryDirectory() as d:
   root,index=self.artifacts(d);builder=ProductionContextBuilder();task=TaskSlice("L","a","do","out",[],["x"],[],"m",str(Path(d)/"out"));request=WorkerRequest(d,task,{"project_id":"p","gate_id":"g","lv_id":"L","canonical_plan_sha256":"a"*64},{"head":"b"*40},{"run_id":"r","attempt":1,"production_context_request":{"builder":builder,"artifact_root":root,"index":index,"binding":binding(),"source_sha256":SRC,"predecessor":PRE,"completed_lvs":["done"],"audience":"worker"}})
   text=_prompt(request,"b"*40,["x"]);self.assertIn("PERSISTED_BYTES_VALIDATED",text);self.assertEqual(builder.calls,1)
 def test_reviewer_production_path_invokes_same_builder(self):
  with tempfile.TemporaryDirectory() as d:
   root,index=self.artifacts(d);builder=ProductionContextBuilder();out=build_bounded_review_context({"builder":builder,"artifact_root":root,"index":index,"binding":binding(),"source_sha256":SRC,"predecessor":PRE,"completed_lvs":["done"],"audience":"reviewer"});self.assertEqual(out["audience"],"reviewer");self.assertEqual(builder.calls,1)
 def test_gate_by_gate_and_full_plan_context_metrics(self):
  with tempfile.TemporaryDirectory() as d:
   root,index=self.artifacts(d)
   for mode,iterations in (("GATE_BY_GATE",1),("FULL_PLAN",4)):
    b=ProductionContextBuilder()
    for _ in range(iterations):b.build(artifact_root=root,index=index,binding=binding(),source_sha256=SRC,predecessor=PRE,completed_lvs=["done"],audience="worker")
    self.assertEqual(b.calls,1);self.assertEqual(b.hits,iterations-1)

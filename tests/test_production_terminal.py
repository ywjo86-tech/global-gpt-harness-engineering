import tempfile,unittest
from pathlib import Path
from tests.test_production_lifecycle import binding
from runtime.orchestrator.cli import production_terminal_entry
from runtime.orchestrator.cli import main as cli_main
from runtime.orchestrator.gate_supervisor import PersistentGateSupervisor
from runtime.orchestrator.production_terminal import ProductionTerminalLifecycle,run_plan_fixture
SRC="a"*64;PRE="b"*64
class ProductionTerminalTests(unittest.TestCase):
 def test_cli_invocation_graph_reaches_handoff_and_approval_boundary(self):
  with tempfile.TemporaryDirectory() as d:
   s=production_terminal_entry(root=d,binding=binding(),lvs=["a","b","c"],reviewed_lvs=["a","b","c"],source_sha256=SRC,predecessor=PRE);self.assertEqual(s["stage"],"HANDOFF_SEALED");self.assertEqual(s["next_gate_status"],"USER_APPROVAL_REQUIRED")
 def test_actual_argparse_terminal_command(self):
  import json
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"request.json";p.write_text(json.dumps({"root":str(Path(d)/"terminal"),"binding":binding(),"lvs":["a"],"reviewed_lvs":["a"],"source_sha256":SRC,"predecessor":PRE,"mode":"GATE_BY_GATE"}));self.assertEqual(cli_main(["production-terminal","--request",str(p)]),0)
 def test_supervisor_graph_and_persisted_artifacts(self):
  with tempfile.TemporaryDirectory() as d:
   s=PersistentGateSupervisor(d,project_id="p",run_id="r",gate_id="g",mode="GATE_BY_GATE",lv_order=["a"]);out=s.run_production_terminal(root=Path(d)/"terminal",binding=binding(),lvs=["a"],reviewed_lvs=["a"],source_sha256=SRC,predecessor=PRE);self.assertEqual(out["gate_status"],"EXITED");self.assertTrue((Path(d)/"terminal/artifacts/gate.handoff.json").is_file())
 def test_checkpoint_lv_gate_handoff_restart_and_replay(self):
  with tempfile.TemporaryDirectory() as d:
   x=ProductionTerminalLifecycle(d,binding(),["a","b"],source_sha256=SRC,predecessor=PRE);self.assertEqual(x.review_pass("a")["next_lv"],"b");y=ProductionTerminalLifecycle(d,binding(),["a","b"],source_sha256=SRC,predecessor=PRE);y.review_pass("b");self.assertEqual(y.replay()["stage"],"HANDOFF_SEALED")
 def test_duplicate_is_idempotent_and_out_of_order_fails(self):
  with tempfile.TemporaryDirectory() as d:
   x=ProductionTerminalLifecycle(d,binding(),["a","b"],source_sha256=SRC,predecessor=PRE)
   with self.assertRaises(Exception):x.review_pass("b")
   first=x.review_pass("a");self.assertEqual(first,x.review_pass("a"))
 def test_tampered_persisted_handoff_is_rejected_on_terminal_replay(self):
  with tempfile.TemporaryDirectory() as d:
   x=ProductionTerminalLifecycle(d,binding(),["a"],source_sha256=SRC,predecessor=PRE);x.review_pass("a");p=Path(d)/"artifacts/gate.handoff.json";p.write_text("{}")
   with self.assertRaises(Exception):ProductionTerminalLifecycle(d,binding(),["a"],source_sha256=SRC,predecessor=PRE).replay()
 def test_multi_gate_gate_by_gate_and_full_plan_f1_f4(self):
  gates=[{"gate_id":f"F{i}","binding":binding(gate_id=f"F{i}"),"lvs":["a","b","c"],"source_sha256":SRC,"predecessor":PRE} for i in range(1,5)]
  with tempfile.TemporaryDirectory() as d:self.assertEqual(run_plan_fixture(d,gates,mode="GATE_BY_GATE")["completed_gates"],1)
  with tempfile.TemporaryDirectory() as d:self.assertEqual(run_plan_fixture(d,gates,mode="FULL_PLAN")["completed_gates"],4)

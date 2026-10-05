from __future__ import annotations
import json,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase
from runtime.orchestrator.production_attention import AttentionOutbox
from runtime.orchestrator.attention_delivery_runner import run_once,partition_current_attention
from runtime.orchestrator.attention_delivery import ATTENTION_DELIVERY_UNCONFIGURED

class AttentionDeliveryRunnerTests(TestCase):
    def fixture(self,root:Path,project:str,run:str,state:str,reason:str):
        harness=root/"executor"; harness.mkdir(exist_ok=True)
        reg=harness/"_workspace/production-full-plan-jobs"/project; reg.mkdir(parents=True,exist_ok=True)
        jp=reg/f"{run}.job.json"; jp.write_text(json.dumps({"project_id":project,"run_id":run,"harness_root":str(harness)}))
        base=harness/"_workspace/production-full-plan"/project/run; base.mkdir(parents=True,exist_ok=True)
        ev=AttentionOutbox(base,project_id=project,run_id=run).publish(kind=state,state=state,reason=reason,gate_id="G1")
        (base/"state.json").write_text(json.dumps({"state":state,"current_gate":"G1","last_error":reason,"last_semantic_progress_at":ev["created_at"]}))
        return jp,ev

    def test_unconfigured_transport_fails_closed_without_marking_delivered(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); _,ev=self.fixture(root,"P","R","BLOCKED","broken")
            out=root/"health.json"; result=run_once(search_root=root,runtime_source_identity="runtime:test",output_path=out)
            self.assertEqual(result["status"],ATTENTION_DELIVERY_UNCONFIGURED)
            self.assertEqual(result["delivered_count"],0)
            self.assertEqual(result["control_authority"],"NONE")
            self.assertEqual(result["runtime_source_identity"],"runtime:test")
            self.assertEqual(len(result["health_sha256"]),64)
            self.assertTrue(out.is_file())

    def test_older_terminal_run_is_historical_but_latest_blocked_is_current(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); old,ev1=self.fixture(root,"P","R1","BLOCKED","old")
            old.touch()
            import time; time.sleep(.01)
            new,ev2=self.fixture(root,"P","R2","BLOCKED","new")
            rows=[
                {"project_id":"P","run_id":"R1","state":"BLOCKED","event_id":ev1["event_id"]},
                {"project_id":"P","run_id":"R2","state":"BLOCKED","event_id":ev2["event_id"]},
            ]
            current,historical=partition_current_attention(root,rows)
            self.assertEqual([x["run_id"] for x in current],["R2"])
            self.assertEqual([x["run_id"] for x in historical],["R1"])

    def test_completed_latest_pending_is_historical(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); _,ev=self.fixture(root,"P","R","COMPLETED","done")
            current,historical=partition_current_attention(root,[{"project_id":"P","run_id":"R","state":"COMPLETED","event_id":ev["event_id"]}])
            self.assertEqual(current,[]); self.assertEqual(len(historical),1)

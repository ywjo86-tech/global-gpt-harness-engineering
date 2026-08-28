from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.completeness import (
    REQUIREMENT_IDS, CompletenessError, build_ledger, load_ledger, save_ledger,
    seal_handoff, validate_handoff, validate_ledger,
)

R = "a"*64; P = "b"*64; ART = "c"*64; HEAD = "d"*40
PLAN = [{"item_id":"G1-LV3-1","gate_id":"GATE-1","lv_id":"G1-LV3-1","owned_files":["app/a.py"],
         "selected_assets":["worker"],"excluded_assets":["other"],"selection_rationale":"manifest capability match",
         "tests":["tests/test_a.py"]}]
REQS = {key:{"gate_id":"GATE-1","lv_id":"G1-LV3-1","owned_files":[],"selected_assets":["worker"],
             "excluded_assets":["other"],"selection_rationale":"registry permission match","tests":["tests/test_req.py"]}
        for key in REQUIREMENT_IDS}


class CompletenessTests(unittest.TestCase):
    def envelope(self): return build_ledger(project_id="project", requirements_sha256=R, plan_sha256=P, plan_items=PLAN, requirements=REQS)

    def exited(self):
        env=self.envelope()
        for row in env["payload"]["items"]:
            row.update(status="EXITED",evidence_sha256="e"*64,checkpoint_ref="cp",exit_ref="exit",handoff_ref="handoff")
        import hashlib
        from runtime.orchestrator.lv_execution_package import canonical_json_bytes
        env["ledger_sha256"]=hashlib.sha256(canonical_json_bytes(env["payload"])).hexdigest()
        return env

    def test_all_plan_items_and_r01_r25_are_ordered(self):
        env=self.envelope(); ids=[x["item_id"] for x in env["payload"]["items"]]
        self.assertEqual(ids, ["G1-LV3-1"]+list(REQUIREMENT_IDS))

    def test_missing_duplicate_reordered_and_sha_drift_block(self):
        for mutate in (lambda x:x.pop(), lambda x:x.append(dict(x[0])), lambda x:x.reverse()):
            env=self.envelope(); mutate(env["payload"]["items"])
            with self.assertRaises(CompletenessError): validate_ledger(env["payload"],plan_items=PLAN)
        with self.assertRaisesRegex(CompletenessError,"requirements SHA drift"):
            validate_ledger(self.envelope()["payload"],plan_items=PLAN,requirements_sha256="f"*64)

    def test_unlinked_and_missing_evidence_refs_block_exit(self):
        env=self.envelope(); env["payload"]["items"][0]["lv_id"]=""
        with self.assertRaises(CompletenessError): validate_ledger(env["payload"],plan_items=PLAN)
        with self.assertRaises(CompletenessError): validate_ledger(self.envelope()["payload"],plan_items=PLAN,require_exit=True)
        validate_ledger(self.exited()["payload"],plan_items=PLAN,require_exit=True)

    def test_canonical_owned_file_and_requirement_linkage_drift_blocks(self):
        env=self.envelope(); env["payload"]["items"][0]["owned_files"]=["other.py"]
        with self.assertRaisesRegex(CompletenessError,"canonical owned_files"):
            validate_ledger(env["payload"],plan_items=PLAN,requirements=REQS)
        env=self.envelope(); env["payload"]["items"][1]["tests"]=["wrong.py"]
        with self.assertRaisesRegex(CompletenessError,"canonical tests"):
            validate_ledger(env["payload"],plan_items=PLAN,requirements=REQS)

    def test_persistence_is_immutable_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"ledger.json"; save_ledger(path,self.envelope()); self.assertEqual(load_ledger(path)["payload"]["project_id"],"project")
            with self.assertRaisesRegex(CompletenessError,"already exists"): save_ledger(path,self.envelope())
            path.write_text("{}")
            with self.assertRaises(CompletenessError): load_ledger(path)

    def handoff(self, ledger):
        ids=[x["item_id"] for x in ledger["payload"]["items"]]
        return seal_handoff({"schema_version":"orchestration.structured-handoff.v1","project_id":"project","gate_id":"GATE-1",
            "lv_id":"G1-LV3-1","run_id":"run-1","requirements_sha256":R,"plan_sha256":P,"branch":"main","head":HEAD,
            "completed_items":ids,"remaining_items":[],"owned_files":["app/a.py"],"changed_files":["app/a.py"],
            "tests":[{"status":"PASS","evidence_sha256":"f"*64}],"review":{"verdict":"PASS","evidence_sha256":"f"*64},
            "artifact_sha256":ART,"checkpoint_ref":"cp","exit_ref":"exit","ledger_sha256":ledger["ledger_sha256"],
            "known_issues":[],"deferred_items":[],"next_condition":"next Gate approval","permissions":["same Gate"],
            "forbidden_actions":["next Gate"],"selected_assets":["worker"],"excluded_assets":["other"],
            "selection_rationale":"manifest capability match"})

    def test_strong_handoff_consistency(self):
        ledger=self.exited(); handoff=self.handoff(ledger)
        args=dict(ledger_envelope=ledger,project_id="project",gate_id="GATE-1",lv_id="G1-LV3-1",run_id="run-1",
                  requirements_sha256=R,plan_sha256=P,branch="main",head=HEAD,artifact_sha256=ART,checkpoint_ref="cp",exit_ref="exit")
        validate_handoff(handoff,**args)
        for key,value in (("run_id","other"),("head","e"*40),("artifact_sha256","f"*64),("checkpoint_ref","other")):
            bad=dict(args); bad[key]=value
            with self.subTest(key=key), self.assertRaises(CompletenessError): validate_handoff(handoff,**bad)

    def test_handoff_changed_file_and_review_mismatch_block(self):
        ledger=self.exited(); base=self.handoff(ledger)["payload"]
        for key,value in (("changed_files",["other.py"]),("review",{"verdict":"FAIL"}),("remaining_items",["R25"])):
            changed=dict(base); changed[key]=value; handoff=seal_handoff(changed)
            with self.subTest(key=key), self.assertRaises(CompletenessError):
                validate_handoff(handoff,ledger_envelope=ledger,project_id="project",gate_id="GATE-1",lv_id="G1-LV3-1",run_id="run-1",
                    requirements_sha256=R,plan_sha256=P,branch="main",head=HEAD,artifact_sha256=ART,checkpoint_ref="cp",exit_ref="exit")


if __name__ == "__main__": unittest.main()

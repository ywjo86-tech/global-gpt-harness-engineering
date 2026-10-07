import hashlib, json, subprocess, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.gate_orchestrator import (
    GateLV, GatePlan, _publish_recovery_canonical_completion,
    _sealed_completed_lv_lineage, create_gate_authorization,
)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes

def seal(obj, field):
    obj[field] = hashlib.sha256(canonical_json_bytes(obj)).hexdigest()
    return obj

class RecoveryCanonicalBridgeTests(unittest.TestCase):
    def test_completed_recovery_projects_canonical_lineage(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); project=base/"project"; project.mkdir(); harness=base/"harness"
            subprocess.run(["git","-C",str(project),"init","-b","main"],check=True,capture_output=True)
            subprocess.run(["git","-C",str(project),"config","user.name","Test"],check=True)
            subprocess.run(["git","-C",str(project),"config","user.email","test@example.com"],check=True)
            (project/"app").mkdir(); owned=project/"app/model.py"; owned.write_text("a\n")
            (project/"PLAN.md").write_text("plan\n")
            subprocess.run(["git","-C",str(project),"add","."],check=True)
            subprocess.run(["git","-C",str(project),"commit","-m","base"],check=True,capture_output=True)
            baseline=subprocess.run(["git","-C",str(project),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
            before=hashlib.sha256(owned.read_bytes()).hexdigest()
            owned.write_text("b\n"); subprocess.run(["git","-C",str(project),"add","app/model.py"],check=True)
            subprocess.run(["git","-C",str(project),"commit","-m","checkpoint"],check=True,capture_output=True)
            current=subprocess.run(["git","-C",str(project),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
            lv=GateLV("GATE-1","TASK-006",1,"runner",[],["app/model.py"],["pass"],"STATE_CHANGING",["pass"],required_capabilities=["implementation"])
            plan=GatePlan("project",str(project),"GATE-1",str(project/"PLAN.md"),"a"*64,[lv])
            auth=create_gate_authorization(plan,"AUTH-1")
            run="run-1"; source={"schema_version":"orchestration.pre-result-partial-source.v1","project_id":"project","gate_id":"GATE-1","lv_id":"TASK-006","run_id":run,"canonical_plan_sha256":"a"*64,"branch":"main","source_head":baseline,"current_head":baseline,"owned_files":["app/model.py"],"owned_diff":{"app/model.py":before}}
            source["source_payload_sha256"]=hashlib.sha256(canonical_json_bytes(source)).hexdigest()
            sp=harness/"_workspace/orchestration-runs"/run/"pre-result-partial-source.json"; sp.parent.mkdir(parents=True); sp.write_bytes(canonical_json_bytes(source))
            ssha=hashlib.sha256(sp.read_bytes()).hexdigest(); rel=sp.relative_to(harness).as_posix()
            rec={"project_id":"project","gate_id":"GATE-1","lv_id":"TASK-006","run_id":run,"recovery_id":"recovery-02","recovery_attempt":2,"approval_event_id":"APR-1","active_transition_sha256":ssha,"branch":"main","current_head":baseline,"source_binding_kind":"PRE_RESULT_PARTIAL_SOURCE","source_shas":{rel:ssha},"hard_stop":True}; seal(rec,"record_hash")
            ctl={"recovery_id":"recovery-02","recovery_record_hash":rec["record_hash"],"next_attempt":2,"source_binding_kind":"PRE_RESULT_PARTIAL_SOURCE","hard_stop":True}; seal(ctl,"checkpoint_sha256")
            bind={"project_id":"project","gate_id":"GATE-1","lv_id":"TASK-006","run_id":run,"recovery_id":"recovery-02","attempt":2,"canonical_plan_sha256":"a"*64,"approval_event_id":"APR-1","active_transition_sha256":ssha,"recovery_record_hash":rec["record_hash"],"recovery_checkpoint_sha256":ctl["checkpoint_sha256"],"hard_stop":True}
            package={"schema_version":"orchestration.recovery-package.v1",**bind}; seal(package,"package_sha256")
            preflight={"schema_version":"orchestration.recovery-preflight.v1",**bind,"package_sha256":package["package_sha256"],"status":"READY"}; seal(preflight,"preflight_sha256")
            worker={"schema_version":"orchestration.recovery-worker-result.v1",**bind,"package_sha256":package["package_sha256"],"preflight_sha256":preflight["preflight_sha256"],"preflight_evidence_sha256":preflight["preflight_sha256"],"status":"completed","baseline_head":baseline,"current_head":current,"checkpoint_commit":current,"changed_files":["app/model.py"],"tests":[{"status":"PASS"}]}; seal(worker,"worker_result_sha256")
            review={"verdict":"PASS","worker_result_sha256":worker["worker_result_sha256"]}; seal(review,"review_sha256")
            checkpoint={"status":"CHECKPOINTED"}; seal(checkpoint,"lifecycle_checkpoint_sha256")
            lv_exit={"status":"EXITED"}; seal(lv_exit,"lv_exit_sha256")
            rh={"status":"SEALED","remaining_lvs":["NEXT"],"gate_complete":False,"lv_exit_sha256":lv_exit["lv_exit_sha256"],"lifecycle_checkpoint_sha256":checkpoint["lifecycle_checkpoint_sha256"]}; seal(rh,"handoff_sha256")
            handoff=_publish_recovery_canonical_completion(project,harness,plan,auth,lv_id="TASK-006",run_id=run,context={"requirements_sha256":"b"*64,"completed_plan_items":[],"remaining_plan_items":["NEXT"]},recovery={"recovery":rec,"checkpoint":ctl},outcome={"package":package,"preflight":preflight,"worker_result":worker},review=review,final={"checkpoint":checkpoint,"lv_exit":lv_exit,"handoff":rh})
            lineage=_sealed_completed_lv_lineage(project,harness,plan,auth,lv_id="TASK-006",run_id=run,current_head=current)
            self.assertEqual(lineage["current_head"],current)
            self.assertEqual(lineage["handoff_sha256"],handoff["handoff_sha256"])
            again=_publish_recovery_canonical_completion(project,harness,plan,auth,lv_id="TASK-006",run_id=run,context={"requirements_sha256":"b"*64,"completed_plan_items":[],"remaining_plan_items":["NEXT"]},recovery={"recovery":rec,"checkpoint":ctl},outcome={"package":package,"preflight":preflight,"worker_result":worker},review=review,final={"checkpoint":checkpoint,"lv_exit":lv_exit,"handoff":rh})
            self.assertEqual(again["handoff_sha256"],handoff["handoff_sha256"])

if __name__ == "__main__":
    unittest.main()

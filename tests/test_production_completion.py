import subprocess, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.production_completion import verify_product_completion

class ProductCompletionTests(unittest.TestCase):
    def test_unproven_lifecycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); subprocess.run(["git","init","-q",root],check=True)
            result=verify_product_completion(root,{"project_id":"p","gate_id":"g","lv_id":"l","run_id":"r","approval_event_id":"a","plan_sha256":"b"*64,"attempt":2,"hard_stop":True,"changed_files":[],"commands":{},"review_verdict":"PASS","staged_changes":False,"unstaged_changes":False},{"project_id":"p","gate_id":"g","lv_id":"l","run_id":"r","approval_event_id":"a","plan_sha256":"b"*64,"owned_files":["x.py"]})
            self.assertEqual(result["status"],"REJECTED_COMPLETION_UNPROVEN")
            self.assertIn("CHANGED_FILES_EMPTY",result["reasons"])

    def test_committed_product_evidence_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); subprocess.run(["git","init","-q",root],check=True)
            subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","--allow-empty","-qm","base"],check=True)
            base=subprocess.check_output(["git","-C",root,"rev-parse","HEAD"],text=True).strip(); base_tree=subprocess.check_output(["git","-C",root,"rev-parse","HEAD^{tree}"],text=True).strip()
            (root/"x.py").write_text("x=1\n"); subprocess.run(["git","-C",root,"add","x.py"],check=True); subprocess.run(["git","-C",root,"-c","user.name=T","-c","user.email=t@x","commit","-qm","x"],check=True)
            head=subprocess.check_output(["git","-C",root,"rev-parse","HEAD"],text=True).strip(); tree=subprocess.check_output(["git","-C",root,"rev-parse","HEAD^{tree}"],text=True).strip()
            ids={"project_id":"p","gate_id":"g","lv_id":"l","run_id":"r","approval_event_id":"a","plan_sha256":"b"*64}
            commands={k:{"command":[k],"exit_code":0} for k in ("worker","focused_test","full_regression","compile_import","git_diff_check")}
            evidence={**ids,"attempt":3,"hard_stop":True,"changed_files":["x.py"],"commands":commands,"review_verdict":"PASS","staged_changes":False,"unstaged_changes":False,"checkpoint_commit":head,"current_head":head,"current_tree":tree,"baseline_head":base,"baseline_tree":base_tree,"artifact_sha_chain":{"a":"c"*64}}
            result=verify_product_completion(root,evidence,{**ids,"owned_files":["x.py"]})
            self.assertEqual(result["status"],"PASS")

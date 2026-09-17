import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operator_control import MANUAL_ACTION_AUTH_SCHEMA, OPERATOR_DIRECTIVE_SCHEMA, ManualActionAuthorizationV1, OperatorDirectiveV1
from runtime.orchestrator.provider_router import ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2, ProviderEligibilitySnapshotV1, RouterRequestV2, route_request
from runtime.orchestrator.production_manual_action import ACTION_SCHEMA, ProductionManualActionError, command_plan_digest, editable_scope_digest, execute_gpt_operator_manual_action
from runtime.orchestrator.lv_review import LVReviewError, _validate_production_provenance


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class ProductionManualActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "t@example.com"], check=True)
        (self.root / "pkg").mkdir()
        (self.root / "a.py").write_text("VALUE = 1\n")
        (self.root / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        subprocess.run(["git", "-C", str(self.root), "add", "a.py", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "base"], check=True)
        self.head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.branch = subprocess.check_output(["git", "-C", str(self.root), "branch", "--show-current"], text=True).strip()
        self.manifest = {"project_id":"P","gate_id":"G","lv_id":"T12","run_id":"R","canonical_plan_sha256":"c"*64,"source_head":self.head,"branch":self.branch,"owned_files":["a.py"],"manifest_sha256":"d"*64,"approval_id":"APR"}

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, codex_eligible=False):
        prepared = "e"*64
        directive = OperatorDirectiveV1(OPERATOR_DIRECTIVE_SCHEMA,"P","R","T12","E12","PREPARE","ACTION",("filesystem_write","test_execution"),True,(prepared,),"G","DIR12")
        snap = ProviderEligibilitySnapshotV1(ELIGIBILITY_SCHEMA_V1,"snap",{"nvidia":True,"codex":codex_eligible},{"nvidia":"n/model", **({"codex":"c/model"} if codex_eligible else {})},("quota-evidence",),{})
        req = RouterRequestV2(ROUTER_REQUEST_SCHEMA_V2,"REQ12","P","R","T12","E12",directive.directive_digest,"ACTION",("filesystem_write","test_execution"),True,GOVERNED_POLICY_V1,snap)
        decision = route_request(req)
        patch = '''diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
'''
        commands = {"focused_test":["python3","-m","compileall","-q","a.py"],"full_regression":["python3","-m","compileall","-q","a.py"],"compile_import":["python3","-m","compileall","-q","a.py"],"git_diff_check":["git","diff","--check"]}
        action = {"schema_version":ACTION_SCHEMA,"project_id":"P","run_id":"R","gate_id":"G","lv_id":"T12","task_execution_id":"E12","plan_sha256":"c"*64,"source_head":self.head,"owned_files":["a.py"],"expected_changed_files":["a.py"],"prepared_artifact_digest":prepared,"patch":patch,"patch_sha256":hashlib.sha256(patch.encode()).hexdigest(),"validation_ids":["TEST-X"],"validation_commands":commands,"commit_subject":"feat(T12): manual checkpoint","operator_directive":directive.to_dict(),"router_request":req.to_dict(),"router_decision":decision.to_dict()}
        action["action_package_digest"] = digest(action)
        auth = ManualActionAuthorizationV1(MANUAL_ACTION_AUTH_SCHEMA,"P","R","T12","E12","G","GPT_OPERATOR",action["action_package_digest"],editable_scope_digest(["a.py"]),command_plan_digest(commands),"AUTH12")
        return action, auth.to_dict()

    def test_executes_only_after_router_action_block_and_seals_checkpoint(self):
        action, auth = self.make()
        result = execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth)
        self.assertEqual(result["completion_mode"], "GPT_OPERATOR_MANUAL_ACTION")
        self.assertEqual(result["executor"]["identity"], "gpt-operator-manual-action")
        self.assertEqual(result["changed_files"], ["a.py"])
        self.assertNotEqual(result["checkpoint_commit"], self.head)
        _validate_production_provenance(result)
        bad = dict(result); bad["executor"] = {"identity":"codex-cli-production","version":"1"}
        with self.assertRaisesRegex(LVReviewError, "manual production worker provenance"):
            _validate_production_provenance(bad)

    def test_router_eligible_action_cannot_use_manual_bridge(self):
        action, auth = self.make(True)
        with self.assertRaisesRegex(ProductionManualActionError, "ACTION_PROVIDER_BLOCKED"):
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth)

    def test_authorization_scope_tamper_fails_closed(self):
        action, auth = self.make(); auth["editable_scope_digest"] = "0"*64
        with self.assertRaisesRegex(ProductionManualActionError, "scope mismatch"):
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth)

    def test_patch_tamper_fails_closed(self):
        action, auth = self.make(); action["patch"] += "\\n"
        with self.assertRaisesRegex(ProductionManualActionError, "package digest"):
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth)


if __name__ == "__main__":
    unittest.main()

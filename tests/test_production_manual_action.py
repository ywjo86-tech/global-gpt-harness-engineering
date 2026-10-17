import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operator_control import MANUAL_ACTION_AUTH_SCHEMA, OPERATOR_DIRECTIVE_SCHEMA, ManualActionAuthorizationV1, OperatorDirectiveV1
from runtime.orchestrator.provider_router import ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2, ProviderEligibilitySnapshotV1, RouterRequestV2, route_request
from runtime.orchestrator.production_manual_action import ACTION_SCHEMA, ProductionManualActionError, _command, build_manual_worker_request, command_plan_digest, editable_scope_digest, execute_gpt_operator_manual_action
from runtime.orchestrator.lv_review import LVReviewError, _validate_production_baseline, _validate_production_provenance
from runtime.orchestrator.schemas import TaskSlice


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

    def test_g1_blocked_manual_action_routes_without_provider_registry(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, authorization = self.make()
        envelope = {"request": action["router_request"], "decision": action["router_decision"]}
        self.assertFalse(action["router_decision"]["eligible"])
        self.assertEqual(action["router_decision"]["action_state"], "ACTION_PROVIDER_BLOCKED")
        # Manual executor remains responsible for checking the actual authorization.
        self.assertEqual(_resolve_adapter_provider_route(
            envelope, manual_action_package=action, manual_action_authorization=authorization,
        ), (None, False))

    def test_g1_blocked_normal_provider_remains_denied(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, _ = self.make()
        envelope = {"request": action["router_request"], "decision": action["router_decision"]}
        with self.assertRaisesRegex(Exception, "eligible bound Router decision is required"):
            _resolve_adapter_provider_route(envelope)

    def test_g1_incomplete_manual_pair_fails_closed(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, _ = self.make()
        envelope = {"request": action["router_request"], "decision": action["router_decision"]}
        with self.assertRaisesRegex(Exception, "must be supplied together"):
            _resolve_adapter_provider_route(envelope, manual_action_package=action)

    def test_g1_manual_without_router_evidence_fails_closed(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, authorization = self.make()
        with self.assertRaisesRegex(Exception, "canonical blocked Router envelope"):
            _resolve_adapter_provider_route(
                None, manual_action_package=action, manual_action_authorization=authorization)

    def test_g1_different_provider_request_id_preserves_manual_route_identity(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        from runtime.orchestrator.provider_router import router_request_from_mapping, route_request
        action, authorization = self.make()
        import copy
        wrong_request = copy.deepcopy(action["router_request"])
        wrong_request["request_id"] = "DIFFERENT-CANONICAL-REQUEST"
        request = router_request_from_mapping(wrong_request)
        envelope = {"request": request.to_dict(), "decision": route_request(request).to_dict()}
        self.assertEqual(_resolve_adapter_provider_route(
            envelope, manual_action_package=action,
            manual_action_authorization=authorization), (None, False))

    def test_g1_wrong_execution_identity_denied(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        from runtime.orchestrator.provider_router import router_request_from_mapping, route_request
        action, authorization = self.make()
        import copy
        wrong_request = copy.deepcopy(action["router_request"])
        wrong_request["task_execution_id"] = "OTHER-EXECUTION"
        request = router_request_from_mapping(wrong_request)
        envelope = {"request": request.to_dict(), "decision": route_request(request).to_dict()}
        with self.assertRaisesRegex(Exception, "execution identity mismatch"):
            _resolve_adapter_provider_route(
                envelope, manual_action_package=action,
                manual_action_authorization=authorization)

    def test_g1_complete_router_capability_snapshot_is_authoritative(self):
        from runtime.orchestrator.provider_router import router_request_from_mapping, route_request
        from runtime.orchestrator.production_manual_action import _validate_router
        import copy
        action, _ = self.make()
        action = copy.deepcopy(action)
        snap = action["router_request"]["eligibility_snapshot"]
        snap["provider_capabilities"] = {"nvidia": ["filesystem_write", "patch_generation"]}
        # Rebind snapshot and decision using exactly the published parser.
        from runtime.orchestrator.provider_router import eligibility_snapshot_from_mapping
        raw_snap = eligibility_snapshot_from_mapping(snap)
        action["router_request"]["eligibility_snapshot_digest"] = raw_snap.snapshot_digest
        req = router_request_from_mapping(action["router_request"])
        action["router_decision"] = route_request(req).to_dict()
        _, parsed_req, parsed_decision = _validate_router(action)
        self.assertTrue(parsed_req.eligibility_binding_valid)
        self.assertEqual(parsed_decision.reason_code, "provider_capability_mismatch")

    def test_g1_mismatch_in_released_manual_route_rejected(self):
        from runtime.orchestrator.production_manual_action import _validate_router
        import copy
        action, _ = self.make()
        action = copy.deepcopy(action)
        # A signed-looking stale reason cannot override the canonical Router.
        action["router_decision"]["reason_code"] = "eligibility_snapshot_binding_mismatch"
        with self.assertRaisesRegex(Exception, "not canonical"):
            _validate_router(action)

    def test_g1_eligible_provider_cannot_enter_manual_bridge(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, authorization = self.make(True)
        envelope = {"request": action["router_request"], "decision": action["router_decision"]}
        self.assertTrue(action["router_decision"]["eligible"])
        with self.assertRaisesRegex(Exception, "ACTION_PROVIDER_BLOCKED"):
            _resolve_adapter_provider_route(
                envelope, manual_action_package=action, manual_action_authorization=authorization)

    def test_g1_tampered_router_envelope_fails_closed(self):
        from runtime.orchestrator.gate_orchestrator import _resolve_adapter_provider_route
        action, authorization = self.make()
        envelope = {"request": dict(action["router_request"]), "decision": action["router_decision"]}
        envelope["request"]["request_id"] = "TAMPERED"
        with self.assertRaises(Exception):
            _resolve_adapter_provider_route(
                envelope, manual_action_package=action, manual_action_authorization=authorization)

    def test_validation_command_does_not_inherit_active_contract_mapping_root(self):
        probe = self.root / "test_env_probe.py"
        probe.write_text(
            "import os, unittest\n"
            "class EnvProbe(unittest.TestCase):\n"
            "    def test_mapping_root_is_not_inherited(self):\n"
            "        self.assertNotIn('HARNESS_CONTRACT_MAPPING_ROOT', os.environ)\n",
            encoding="utf-8",
        )
        from unittest.mock import patch
        with patch.dict(os.environ, {"HARNESS_CONTRACT_MAPPING_ROOT": "/tmp/live-mapping"}):
            result = _command(self.root, ["python3", "-m", "unittest", "-q", "test_env_probe"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timeout"])

    def test_manual_worker_request_binds_review_identity(self):
        action, _ = self.make()
        task = TaskSlice(
            thread_id="T12", assigned_agent="implementation_agent", input="manual",
            expected_output="truthful worker result", validation_criteria=["TEST-X"],
            editable_scope=["a.py"], forbidden_scope=[], merge_point="GATE_EXIT",
            required_capabilities=["filesystem_write", "test_execution"],
            run_id="R", run_root=str(self.root / "pkg"), output_dir=str(self.root / "pkg"),
            result_path=str(self.root / "pkg" / "worker.result.json"),
            worker_request_path=str(self.root / "pkg" / "worker.request.json"),
        )
        request = build_manual_worker_request(
            project_root=self.root, package_root=self.root / "pkg", task=task, manifest=self.manifest,
            preflight_evidence_sha256="f" * 64, package_manifest_sha256="d" * 64,
            approval_event_id="APR", action_package=action,
        ).to_dict()
        self.assertEqual(request["contract_summary"]["project_id"], "P")
        self.assertEqual(request["contract_summary"]["gate_id"], "G")
        self.assertEqual(request["contract_summary"]["lv_id"], "T12")
        self.assertEqual(request["extra_context"]["run_id"], "R")
        self.assertEqual(request["extra_context"]["package_manifest_sha256"], "d" * 64)
        self.assertEqual(request["extra_context"]["execution_backend"], "GPT_OPERATOR_MANUAL_ACTION")
        bad_manifest = dict(self.manifest); bad_manifest["run_id"] = "OTHER"
        with self.assertRaisesRegex(ProductionManualActionError, "run binding mismatch"):
            build_manual_worker_request(
                project_root=self.root, package_root=self.root / "pkg", task=task, manifest=bad_manifest,
                preflight_evidence_sha256="f" * 64, package_manifest_sha256="d" * 64,
                approval_event_id="APR", action_package=action,
            )

    def test_executes_only_after_router_action_block_and_seals_checkpoint(self):
        action, auth = self.make()
        result = execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth, expected_branch=self.branch, package_manifest_sha256="d"*64)
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
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth, expected_branch=self.branch, package_manifest_sha256="d"*64)

    def test_authorization_scope_tamper_fails_closed(self):
        action, auth = self.make(); auth["editable_scope_digest"] = "0"*64
        with self.assertRaisesRegex(ProductionManualActionError, "scope mismatch"):
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth, expected_branch=self.branch, package_manifest_sha256="d"*64)

    def test_patch_tamper_fails_closed(self):
        action, auth = self.make(); action["patch"] += "\\n"
        with self.assertRaisesRegex(ProductionManualActionError, "package digest"):
            execute_gpt_operator_manual_action(project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest, preflight_evidence_sha256="f"*64, action_package=action, authorization=auth, expected_branch=self.branch, package_manifest_sha256="d"*64)

    def test_clean_safe_descendant_outside_owned_scope_is_allowed(self):
        action, auth = self.make()
        (self.root / "notes.txt").write_text("infra-only\n")
        subprocess.run(["git", "-C", str(self.root), "add", "notes.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "infra descendant"], check=True)
        descendant = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        result = execute_gpt_operator_manual_action(
            project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest,
            preflight_evidence_sha256="f"*64, action_package=action, authorization=auth,
            expected_branch=self.branch, package_manifest_sha256="d"*64)
        self.assertEqual(result["baseline_head"], descendant)
        self.assertEqual(result["sealed_source_head"], self.head)
        self.assertTrue(result["safe_descendant_source"])
        _validate_production_baseline(result, self.manifest, self.root)

    def test_safe_descendant_rejects_owned_scope_drift(self):
        action, auth = self.make()
        (self.root / "a.py").write_text("VALUE = 9\n")
        subprocess.run(["git", "-C", str(self.root), "add", "a.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "owned drift"], check=True)
        with self.assertRaisesRegex(ProductionManualActionError, "changed owned scope"):
            execute_gpt_operator_manual_action(
                project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest,
                preflight_evidence_sha256="f"*64, action_package=action, authorization=auth,
                expected_branch=self.branch, package_manifest_sha256="d"*64)

    def test_non_descendant_source_is_rejected(self):
        action, auth = self.make()
        subprocess.run(["git", "-C", str(self.root), "checkout", "--orphan", "other"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.root), "rm", "-rf", "."], check=True, stdout=subprocess.DEVNULL)
        (self.root / "a.py").write_text("VALUE = 1\n")
        (self.root / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        subprocess.run(["git", "-C", str(self.root), "add", "a.py", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "other root"], check=True)
        action = dict(action)
        # Branch binding must match so ancestry, not branch identity, is the rejecting control.
        with self.assertRaisesRegex(ProductionManualActionError, "not a safe descendant"):
            execute_gpt_operator_manual_action(
                project_root=self.root, package_root=self.root/"pkg", manifest=self.manifest,
                preflight_evidence_sha256="f"*64, action_package=action, authorization=auth,
                expected_branch="other", package_manifest_sha256="d"*64)


if __name__ == "__main__":
    unittest.main()

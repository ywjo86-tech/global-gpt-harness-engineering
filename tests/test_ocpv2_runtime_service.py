from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from runtime.orchestrator.ocpv2_runtime_service import (
    RuntimeConfig,
    RuntimeServiceError,
    _compose_service,
    canary_scope_from_environment,
    execute_authorized_canonical,
    finalize_remote_control_projection,
    full_plan_activation_enabled_from_environment,
    host_inspection_enabled_from_environment,
    load_runtime_config,
    work_activation_enabled_from_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def mutation_envelope(**changes):
    expected = SimpleNamespace(
        canonical_run_state_sha256="a" * 64,
        continuation_owner_epoch=7,
        source_head="b" * 40,
        runtime_release_digest="c" * 64,
    )
    for key, value in changes.items():
        setattr(expected, key, value)
    return SimpleNamespace(
        message_id="MSG-1",
        directive_digest="d" * 64,
        project_id="P1",
        run_id="R1",
        gate_id="G1",
        task_id="G1",
        task_execution_id="R1--g1",
        expected=expected,
    )


def mutation_directive():
    return SimpleNamespace(
        project_id="P1",
        run_id="R1",
        gate_id="G1",
        task_id="G1",
        task_execution_id="R1--g1",
        current_stage="PREPARE",
        requested_next_stage="ACTION",
        state_change_required=True,
    )


class OCPv2RuntimeServiceTests(unittest.TestCase):
    def test_mutation_delegates_only_to_registered_full_plan_resume(self):
        executor = Mock(return_value={"status": "WAITING_APPROVAL", "result_class": "CANONICAL_FULL_PLAN_RESULT"})
        result = execute_authorized_canonical(
            mutation_envelope(),
            mutation_directive(),
            harness_state_root=Path("/safe/state"),
            executor=executor,
        )
        self.assertEqual(result["result_class"], "CANONICAL_FULL_PLAN_RESULT")
        executor.assert_called_once_with(
            harness_state_root=Path("/safe/state"),
            project_id="P1",
            run_id="R1",
            gate_id="G1",
            task_id="G1",
            task_execution_id="R1--g1",
            expected_state_sha256="a" * 64,
            expected_owner_epoch=7,
            expected_source_head="b" * 40,
            expected_runtime_release_digest="c" * 64,
            remote_message_id="MSG-1",
            remote_directive_digest="d" * 64,
        )

    def test_missing_canonical_mutation_binding_fails_before_executor(self):
        for field, value in (
            ("canonical_run_state_sha256", ""),
            ("continuation_owner_epoch", 0),
            ("source_head", ""),
            ("runtime_release_digest", ""),
        ):
            with self.subTest(field=field):
                executor = Mock()
                with self.assertRaisesRegex(RuntimeServiceError, "MUTATION_BINDING_REQUIRED"):
                    execute_authorized_canonical(
                        mutation_envelope(**{field: value}),
                        mutation_directive(),
                        harness_state_root=Path("/safe/state"),
                        executor=executor,
                    )
                executor.assert_not_called()

    def test_canary_mode_requires_all_exact_scope_fields(self):
        complete = {
            "OCP_CANARY_PROJECT_ID": "P1",
            "OCP_CANARY_RUN_ID": "R1",
            "OCP_CANARY_TASK_ID": "G1",
            "OCP_CANARY_GATE_ID": "G1",
            "OCP_CANARY_DIRECTIVE_ID": "D1",
        }
        scope = canary_scope_from_environment("CONTROL_MUTATION_CANARY", complete)
        self.assertEqual((scope.project_id, scope.run_id, scope.task_id, scope.gate_id, scope.directive_id),
                         ("P1", "R1", "G1", "G1", "D1"))
        broken = dict(complete)
        broken.pop("OCP_CANARY_DIRECTIVE_ID")
        with self.assertRaisesRegex(RuntimeServiceError, "CANARY_SCOPE_REQUIRED"):
            canary_scope_from_environment("CONTROL_MUTATION_CANARY", broken)
        self.assertIsNone(canary_scope_from_environment("OBSERVE_ONLY", {}))

    def test_runtime_service_has_no_job_registration_or_direct_shell_authority(self):
        import runtime.orchestrator.ocpv2_runtime_service as module
        source = inspect.getsource(module)
        self.assertNotIn("register_job(", source)
        self.assertNotIn("subprocess.Popen", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("provider_router", source)

    def test_runtime_decode_uses_additive_remote_control_dispatch(self):
        import runtime.orchestrator.ocpv2_runtime_service as module
        source = inspect.getsource(module)
        self.assertIn("decode_remote_control_payload(value)", source)
        self.assertNotIn("envelope = validate_remote_envelope(value)", source)


    def test_remote_control_status_projection_does_not_touch_durable_outbox(self):
        outbox = Mock()
        finalize_remote_control_projection(
            outbox,
            {
                "schema_version": "orchestration.remote-activation-status-projection.v1",
                "message_id": "MSG-A1", "activation_request_id": "ACT-1",
                "project_alias": "demo", "request_digest": "a" * 64,
                "result_class": "WORK_ACTIVATION_ERROR",
            },
        )
        outbox.mark_published.assert_not_called()

    def test_user_service_invokes_runtime_module_not_bootstrap_poll_loop(self):
        text = (REPO_ROOT / "deploy" / "operator-control-plane-v2" / "ocpv2.user.service.in").read_text(encoding="utf-8")
        self.assertIn("-m runtime.orchestrator.ocpv2_runtime_service", text)
        self.assertNotIn("bootstrap.py run-once", text)


    def test_host_inspection_feature_flag_is_explicit_and_fail_closed(self):
        self.assertFalse(host_inspection_enabled_from_environment({}))
        self.assertFalse(host_inspection_enabled_from_environment({"OCP_HOST_INSPECTION_ENABLED": "0"}))
        self.assertTrue(host_inspection_enabled_from_environment({"OCP_HOST_INSPECTION_ENABLED": "1"}))
        self.assertFalse(host_inspection_enabled_from_environment({"OCP_HOST_INSPECTION_ENABLED": "true"}))
        self.assertFalse(host_inspection_enabled_from_environment({"OCP_HOST_INSPECTION_ENABLED": "bogus"}))

    def test_runtime_composes_host_inspection_without_direct_effect_authority(self):
        import runtime.orchestrator.ocpv2_runtime_service as module
        source = inspect.getsource(module)
        self.assertIn("HostInspectionPort", source)
        self.assertIn("RemoteInspectionProjectionV1", source)
        self.assertIn("OCP_HOST_INSPECTION_ENABLED", source)
        for forbidden in ("FullMCPRuntime", "ProcessService", "shell_execute", "register_job(", "provider_router"):
            with self.subTest(forbidden=forbidden): self.assertNotIn(forbidden, source)

    def test_user_service_defaults_host_inspection_off(self):
        text = (REPO_ROOT / "deploy" / "operator-control-plane-v2" / "ocpv2.user.service.in").read_text(encoding="utf-8")
        self.assertIn("Environment=OCP_HOST_INSPECTION_ENABLED=0", text)


    def test_work_activation_feature_flag_is_explicit_and_fail_closed(self):
        self.assertFalse(work_activation_enabled_from_environment({}))
        self.assertFalse(work_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "0"}))
        self.assertTrue(work_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "1"}))
        self.assertFalse(work_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "true"}))
        self.assertFalse(work_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "bogus"}))

    def test_user_service_defaults_work_activation_off(self):
        text = (REPO_ROOT / "deploy" / "operator-control-plane-v2" / "ocpv2.user.service.in").read_text(encoding="utf-8")
        self.assertIn("Environment=OCP_WORK_ACTIVATION_ENABLED=0", text)


    def test_full_plan_activation_flag_is_exact_one_and_independent(self):
        self.assertFalse(full_plan_activation_enabled_from_environment({}))
        self.assertFalse(full_plan_activation_enabled_from_environment({"OCP_FULL_PLAN_ACTIVATION_ENABLED": "0"}))
        self.assertFalse(full_plan_activation_enabled_from_environment({"OCP_FULL_PLAN_ACTIVATION_ENABLED": "true"}))
        self.assertTrue(full_plan_activation_enabled_from_environment({"OCP_FULL_PLAN_ACTIVATION_ENABLED": "1"}))
        self.assertTrue(work_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "1"}))
        self.assertFalse(full_plan_activation_enabled_from_environment({"OCP_WORK_ACTIVATION_ENABLED": "1"}))

    def test_v1_activation_flag_does_not_enable_full_plan_activation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); repo=root/"repo"; repo.mkdir(); token=root/"token"; token.write_text("x"); token.chmod(0o600)
            env=root/"ocp.env"; env.write_text("\n".join([
                "OCP_MODE=ACTIVE", "OCP_GITHUB_CONTROL_REPOSITORY_ID=222", "OCP_GITHUB_CONTROL_PR_NUMBER=7",
                "OCP_GITHUB_ALLOWED_ACTOR_IDS=235775273", f"OCP_GITHUB_TOKEN_FILE={token}", f"OCP_STATE_ROOT={root/'state'}",
                f"OCP_REPO_ROOT={repo}", "OCP_WORK_ACTIVATION_ENABLED=1", "OCP_WORK_ACTIVATION_POLICY_REF=ACT-POLICY-1",
                "OCP_FULL_PLAN_ACTIVATION_ENABLED=0",
            ])+"\n")
            cfg=load_runtime_config(env, process_environment={})
            self.assertTrue(cfg.work_activation_enabled); self.assertFalse(cfg.full_plan_activation_enabled)
            self.assertEqual(cfg.full_plan_activation_policy_ref, "")

    def test_full_plan_activation_enabled_requires_dedicated_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); repo=root/"repo"; repo.mkdir(); token=root/"token"; token.write_text("x"); token.chmod(0o600)
            env=root/"ocp.env"; env.write_text("\n".join([
                "OCP_MODE=ACTIVE", "OCP_GITHUB_CONTROL_REPOSITORY_ID=222", "OCP_GITHUB_CONTROL_PR_NUMBER=7",
                "OCP_GITHUB_ALLOWED_ACTOR_IDS=235775273", f"OCP_GITHUB_TOKEN_FILE={token}", f"OCP_STATE_ROOT={root/'state'}",
                f"OCP_REPO_ROOT={repo}", "OCP_FULL_PLAN_ACTIVATION_ENABLED=1",
            ])+"\n")
            with self.assertRaisesRegex(RuntimeServiceError, "Full Plan activation policy"):
                load_runtime_config(env, process_environment={})

    def test_executable_activation_uses_system_authority_root_and_never_request_mapping_root(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); repo=root/"runtime"; repo.mkdir(); token=root/"token"; token.write_text("x"); token.chmod(0o600)
            ocp_state=root/"ocp-state"; ocp_state.mkdir(); harness_state=root/"harness-state"; harness_state.mkdir()
            authority=root/"authority"; authority.mkdir()
            cfg=RuntimeConfig(
                mode=__import__("runtime.orchestrator.remote_operator_service",fromlist=["ControlMode"]).ControlMode.ACTIVE,
                repo_root=repo, control_repository_id=222, control_pr_number=7,
                allowed_actor_ids=("235775273",), token_file=token, state_root=ocp_state,
                environment={"GCH_STATE_ROOT":str(harness_state),"HARNESS_CONTRACT_MAPPING_ROOT":str(authority)},
                host_inspection_enabled=False, work_activation_enabled=False, activation_policy_ref="",
                full_plan_activation_enabled=True, full_plan_activation_policy_ref="FP-POLICY-1",
            )
            with patch("runtime.orchestrator.ocpv2_runtime_service.GitHubRESTClient",return_value=Mock()), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.GitHubControlAdapter",return_value=Mock()), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.recover_pending_canonical_results"), \
                 patch("runtime.orchestrator.ocpv2_runtime_service._runtime_release_for_root",return_value=Mock()) as release, \
                 patch("runtime.orchestrator.ocpv2_runtime_service.validate_approved_full_plan_binding",side_effect=RuntimeError("stop")) as validate:
                service=_compose_service(cfg)
                envelope=SimpleNamespace(payload=SimpleNamespace(mapping_root="caller-forbidden"),message_id="MSG-FP")
                with self.assertRaisesRegex(RuntimeError,"stop"):
                    service.activate_full_plan_authorized(envelope)
            self.assertEqual(validate.call_args.kwargs["authority_root"],authority)
            self.assertEqual(validate.call_args.kwargs["harness_state_root"],harness_state)
            release.assert_called_once_with(repo)

    def test_user_service_defaults_full_plan_activation_off(self):
        text=(REPO_ROOT/"deploy/operator-control-plane-v2/ocpv2.user.service.in").read_text(encoding="utf-8")
        self.assertIn("Environment=OCP_FULL_PLAN_ACTIVATION_ENABLED=0", text)
        self.assertNotIn("OCP_FULL_PLAN_ACTIVATION_POLICY_REF=", text)


if __name__ == "__main__":
    unittest.main()

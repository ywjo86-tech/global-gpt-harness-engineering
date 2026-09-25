from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import runtime.orchestrator.ocpv2_runtime_service as runtime_service
from runtime.orchestrator.remote_operator_service import ControlMode


REPO_ROOT = Path(__file__).resolve().parents[1]


class HarnessLifecycleV2Gate15DefaultDisableTests(unittest.TestCase):
    def test_new_activation_lifecycle_default_is_v2_and_legacy_is_explicit(self) -> None:
        resolver = runtime_service.new_activation_lifecycle_mode_from_environment
        self.assertEqual(resolver({}), "V2")
        self.assertEqual(resolver({"GCH_NEW_ACTIVATION_LIFECYCLE_MODE": "V2"}), "V2")
        self.assertEqual(resolver({"GCH_NEW_ACTIVATION_LIFECYCLE_MODE": "LEGACY"}), "LEGACY")
        with self.assertRaisesRegex(runtime_service.RuntimeServiceError, "NEW_ACTIVATION_LIFECYCLE_MODE_INVALID"):
            resolver({"GCH_NEW_ACTIVATION_LIFECYCLE_MODE": "BOGUS"})

    def test_ocp_full_plan_activation_passes_legacy_default_only_to_new_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "runtime"
            repo.mkdir()
            token = root / "token"
            token.write_text("x", encoding="utf-8")
            token.chmod(0o600)
            ocp_state = root / "ocp-state"
            ocp_state.mkdir()
            harness_state = root / "harness-state"
            harness_state.mkdir()
            authority = root / "authority"
            authority.mkdir()

            config = runtime_service.RuntimeConfig(
                mode=ControlMode.ACTIVE,
                repo_root=repo,
                control_repository_id=222,
                control_pr_number=7,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=ocp_state,
                environment={
                    "GCH_STATE_ROOT": str(harness_state),
                    "HARNESS_CONTRACT_MAPPING_ROOT": str(authority),
                    "GCH_NEW_ACTIVATION_LIFECYCLE_MODE": "LEGACY",
                },
                host_inspection_enabled=False,
                work_activation_enabled=False,
                activation_policy_ref="",
                full_plan_activation_enabled=True,
                full_plan_activation_policy_ref="FP-POLICY-1",
            )
            bundle = SimpleNamespace(project_id="P1", activation_request_id="ACT-1")
            activation = Mock(side_effect=RuntimeError("STOP_AFTER_ACTIVATION_CALL"))

            with patch.object(runtime_service, "GitHubRESTClient", return_value=Mock()), \
                 patch.object(runtime_service, "GitHubControlAdapter", return_value=Mock()), \
                 patch.object(runtime_service, "recover_pending_canonical_results", return_value=None), \
                 patch.object(runtime_service, "resolve_harness_state_root", return_value=harness_state), \
                 patch.object(runtime_service, "_runtime_release_for_root", return_value=Mock()), \
                 patch.object(runtime_service, "validate_approved_full_plan_binding", return_value=bundle), \
                 patch.object(runtime_service, "AIOfficeStateStore", return_value=Mock()), \
                 patch.object(runtime_service, "coordinate_approved_full_plan_activation", return_value=Mock()), \
                 patch.object(runtime_service, "activate_approved_full_plan", activation):
                service = runtime_service._compose_service(config)
                envelope = SimpleNamespace(payload=Mock(), message_id="MSG-FP-ROLLBACK")
                with self.assertRaisesRegex(RuntimeError, "STOP_AFTER_ACTIVATION_CALL"):
                    service.activate_full_plan_authorized(envelope)

            self.assertEqual(activation.call_args.kwargs["lifecycle_mode"], "LEGACY")

    def test_deployed_service_defaults_v2_and_env_file_can_override_to_legacy(self) -> None:
        service_template = (
            REPO_ROOT / "deploy" / "operator-control-plane-v2" / "ocpv2.user.service.in"
        ).read_text(encoding="utf-8")
        self.assertIn("Environment=GCH_NEW_ACTIVATION_LIFECYCLE_MODE=V2", service_template)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            token = root / "token"
            token.write_text("x", encoding="utf-8")
            token.chmod(0o600)
            env_path = root / "ocp.env"
            env_path.write_text(
                "\n".join(
                    [
                        "OCP_MODE=OBSERVE_ONLY",
                        "OCP_GITHUB_CONTROL_REPOSITORY_ID=987654",
                        "OCP_GITHUB_CONTROL_PR_NUMBER=7",
                        "OCP_GITHUB_ALLOWED_ACTOR_IDS=123",
                        f"OCP_GITHUB_TOKEN_FILE={token}",
                        f"OCP_STATE_ROOT={root / 'state'}",
                        f"OCP_REPO_ROOT={repo}",
                        "GCH_NEW_ACTIVATION_LIFECYCLE_MODE=LEGACY",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config = runtime_service.load_runtime_config(
                env_path,
                process_environment={"GCH_NEW_ACTIVATION_LIFECYCLE_MODE": "V2"},
            )
            self.assertEqual(
                runtime_service.new_activation_lifecycle_mode_from_environment(config.environment),
                "LEGACY",
            )


if __name__ == "__main__":
    unittest.main()

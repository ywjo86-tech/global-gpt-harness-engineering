from __future__ import annotations

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
    host_inspection_enabled_from_environment,
    load_runtime_config,
    work_activation_enabled_from_environment,
)
from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.read_only_host_diagnostic_contract import (
    DiagnosticPolicy,
    ReadOnlyDiagnosticResultV1,
)
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA,
    seal_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


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


def _write_runtime_env(root: Path, *, extra: dict[str, str] | None = None):
    repo = root / "repo"
    repo.mkdir(exist_ok=True)
    token = root / "token"
    token.write_text("x\n", encoding="utf-8")
    token.chmod(0o600)
    state = root / "state"
    values = {
        "OCP_MODE": "CONTROL_READ_ONLY",
        "OCP_GITHUB_CONTROL_REPOSITORY_ID": "987654",
        "OCP_GITHUB_CONTROL_PR_NUMBER": "7",
        "OCP_GITHUB_ALLOWED_ACTOR_IDS": "123",
        "OCP_GITHUB_TOKEN_FILE": str(token),
        "OCP_STATE_ROOT": str(state),
        "OCP_REPO_ROOT": str(repo),
    }
    values.update(extra or {})
    path = root / "ocp.env"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    return path, repo, state


def _write_policy(path: Path, repo: Path):
    path.write_text(json.dumps({
        "schema_version": "orchestration.read-only-host-diagnostic-config.v1",
        "roots": {"project": str(repo)},
        "user_services": ["ocpv2.service"],
        "limits": {"max_bytes": 32768, "max_lines": 400, "timeout_seconds": 5},
    }), encoding="utf-8")
    path.chmod(0o600)
    return path


def _diagnostic_raw():
    payload = {
        "schema_version": REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA,
        "message_id": "MSG-DIAG-1", "sequence": 1,
        "issued_at": "2026-09-23T00:00:00+00:00", "expires_at": "2026-09-24T00:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {"adapter_id": "GITHUB_CONTROL_V1", "channel_id": "PR:7", "source_actor_id": "123", "source_message_id": "9"},
        "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1", "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA, "project_id": "P1", "run_id": "R1", "task_id": "T1",
            "task_execution_id": "E1", "current_stage": "PREPARE", "requested_next_stage": "VERIFY",
            "required_capabilities": ["read_only_host_diagnostic"], "state_change_required": False,
            "input_artifact_digests": [], "gate_id": "G1", "directive_id": "D1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "", "continuation_owner_epoch": 0, "canonical_run_state_sha256": "",
            "migration_id": "", "migration_transaction_sha256": "", "migration_phase": "",
            "qualification_evidence_sha256": "", "source_head": "a" * 40, "runtime_release_digest": "b" * 64,
        },
        "authorization": {"risk_envelope_ref": "", "risk_envelope_digest": "", "manual_action_authorization_digest": ""},
        "read_only_request": {
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1", "request_id": "REQ-1",
            "operation": "repo.snapshot", "root_id": "project", "relative_path": "", "start_line": 0,
            "line_count": 0, "service_id": "",
        },
        "read_only_request_digest": "", "envelope_sha256": "",
    }
    sealed = seal_remote_control_envelope(payload)
    return RawControlEnvelope(
        source_repository_id=987654, source_channel_id="PR:7", source_actor_id="123", source_message_id="9",
        content=json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        received_at="2026-09-23T00:01:00+00:00",
    )


class _FakeAdapter:
    def __init__(self, items=(), *, fail_publish=False):
        self.items = tuple(items)
        self.fail_publish = fail_publish
        self.projections = []
        self.acks = []
    def receive(self, *, limit=16):
        return self.items[:limit]
    def publish_projection(self, projection):
        if self.fail_publish:
            raise RuntimeError("offline")
        self.projections.append(dict(projection))
    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)
    def has_durable_ack(self, *args, **kwargs):
        return False
    def prepare_recovery_delivery(self, **kwargs):
        return None


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

    def test_diagnostic_feature_defaults_off_and_old_env_still_loads(self):
        with tempfile.TemporaryDirectory() as td:
            env_path, _, _ = _write_runtime_env(Path(td))
            config = load_runtime_config(env_path, process_environment={})
            self.assertFalse(config.diagnostic_enabled)
            self.assertIsNone(config.diagnostic_policy)

    def test_old_env_cannot_be_implicitly_enabled_by_process_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env_path, repo, _ = _write_runtime_env(root)
            policy = _write_policy(root / "policy.json", repo)
            config = load_runtime_config(env_path, process_environment={
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true",
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG": str(policy),
            })
            self.assertFalse(config.diagnostic_enabled)
            self.assertIsNone(config.diagnostic_policy)

    def test_diagnostic_feature_true_requires_secure_absolute_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env_path, repo, _ = _write_runtime_env(root, extra={"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true"})
            with self.assertRaisesRegex(RuntimeServiceError, "diagnostic config"):
                load_runtime_config(env_path, process_environment={})

            env_path, repo, _ = _write_runtime_env(root, extra={
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true",
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG": "relative.json",
            })
            with self.assertRaisesRegex(RuntimeServiceError, "diagnostic config"):
                load_runtime_config(env_path, process_environment={})

            policy = _write_policy(root / "policy.json", repo)
            link = root / "policy-link.json"
            link.symlink_to(policy)
            env_path, _, _ = _write_runtime_env(root, extra={
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true",
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG": str(link),
            })
            with self.assertRaisesRegex(RuntimeServiceError, "diagnostic config"):
                load_runtime_config(env_path, process_environment={})

            policy.chmod(0o620)
            env_path, _, _ = _write_runtime_env(root, extra={
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true",
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG": str(policy),
            })
            with self.assertRaisesRegex(RuntimeServiceError, "diagnostic config"):
                load_runtime_config(env_path, process_environment={})

    def test_feature_off_does_not_instantiate_diagnostic_outbox(self):
        import runtime.orchestrator.ocpv2_runtime_service as module
        with tempfile.TemporaryDirectory() as td:
            env_path, _, _ = _write_runtime_env(Path(td))
            config = load_runtime_config(env_path, process_environment={})
            with patch.object(module, "RemoteDiagnosticOutbox", side_effect=AssertionError("must stay off"), create=True), \
                 patch.object(module, "GitHubRESTClient", return_value=Mock()), \
                 patch.object(module, "GitHubControlAdapter", return_value=Mock()), \
                 patch.object(module, "recover_pending_canonical_results", return_value=None), \
                 patch.object(module, "resolve_harness_state_root", return_value=Path(td)):
                _compose_service(config)

    def test_diagnostic_outbox_recovers_after_publish_crash_without_reexecution(self):
        import runtime.orchestrator.ocpv2_runtime_service as module
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            policy_path = _write_policy(root / "policy.json", repo)
            env_path, _, state = _write_runtime_env(root, extra={
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true",
                "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG": str(policy_path),
            })
            config = load_runtime_config(env_path, process_environment={})
            first_adapter = _FakeAdapter((_diagnostic_raw(),), fail_publish=True)
            second_adapter = _FakeAdapter(())
            adapters = iter((first_adapter, second_adapter))
            executions = []

            def fake_execute(request, policy, **kwargs):
                executions.append((request.request_id, kwargs["source_sha"], kwargs["runtime_sha"]))
                return ReadOnlyDiagnosticResultV1.build(
                    request_id=request.request_id, correlation_id=kwargs["correlation_id"], project_id=kwargs["project_id"],
                    root_id=request.root_id, operation_id=request.operation, authorization_decision="ALLOW",
                    captured_at="2026-09-23T00:02:00+00:00", freshness="CURRENT",
                    source_sha=kwargs["source_sha"], runtime_sha=kwargs["runtime_sha"], data_class="DIAG_SUMMARY",
                    redaction_applied=False, truncated=False, status="OK", error_class="", payload={"head": "a" * 40},
                )

            with patch.object(module, "GitHubRESTClient", return_value=Mock()), \
                 patch.object(module, "GitHubControlAdapter", side_effect=lambda **kwargs: next(adapters)), \
                 patch.object(module, "recover_pending_canonical_results", return_value=None), \
                 patch.object(module, "resolve_harness_state_root", return_value=repo), \
                 patch.object(module, "_diagnostic_provenance", return_value=("1" * 40, "2" * 64)), \
                 patch.object(module, "execute_read_only_host_diagnostic", side_effect=fake_execute, create=True):
                first = _compose_service(config)
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    first.poll_once(mode=config.mode)
                self.assertEqual(executions, [("REQ-1", "1" * 40, "2" * 64)])

                _compose_service(config)
                self.assertEqual(executions, [("REQ-1", "1" * 40, "2" * 64)])
                self.assertEqual(len(second_adapter.projections), 1)
                recovered = second_adapter.projections[0]
                self.assertEqual(recovered["schema_version"], "orchestration.remote-diagnostic-projection.v1")
                self.assertEqual(recovered["diagnostic_result"]["status"], "OK")

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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from runtime.orchestrator.ocpv2_runtime_service import (
    RuntimeServiceError,
    canary_scope_from_environment,
    execute_authorized_canonical,
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

    def test_user_service_invokes_runtime_module_not_bootstrap_poll_loop(self):
        text = (REPO_ROOT / "deploy" / "operator-control-plane-v2" / "ocpv2.user.service.in").read_text(encoding="utf-8")
        self.assertIn("-m runtime.orchestrator.ocpv2_runtime_service", text)
        self.assertNotIn("bootstrap.py run-once", text)


if __name__ == "__main__":
    unittest.main()

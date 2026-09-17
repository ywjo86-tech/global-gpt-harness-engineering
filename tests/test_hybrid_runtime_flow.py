from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.engine import OrchestrationEngine
from runtime.orchestrator.nvidia_adapter import run_nvidia_reasoning_task
from runtime.orchestrator.provider_executor import execute_provider_task
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1, RouterRequestV2, route_request,
)
from runtime.orchestrator.schemas import TaskSlice
from tests.helpers import cloned_sample_project


def _write_model_pool(project: Path, model: str = "nvidia/router-model", fallback_models: tuple[str, ...] = ()) -> Path:
    path = project / "runtime" / "test-nvidia-model-pool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "gch.nvidia.model-pool.v1",
        "default_role": "primary_heavy",
        "models": {"primary_heavy": {
            "model": model, "status": "ACTIVE", "fallback_models": list(fallback_models),
        }},
        "policy": {
            "automatic_provider_fallback": False,
            "automatic_model_failover": bool(fallback_models),
            "state_changing_execution": False,
        },
    }), encoding="utf-8")
    return path


def _write_codex_policy(project: Path, model: str = "codex/router-model") -> Path:
    path = project / "runtime" / "test-pre-mprf-provider-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "gch.pre-mprf.provider-policy.v1",
        "policy_profile": GOVERNED_POLICY_V1,
        "providers": {
            "codex": {"model": model, "status": "ACTIVE", "approval_ref": "TEST-APPROVAL"}
        },
    }), encoding="utf-8")
    return path


def _task(capabilities: list[str]) -> TaskSlice:
    return TaskSlice(
        thread_id="T1",
        assigned_agent="qa_reviewer_agent",
        input="Review docs",
        expected_output="handoff",
        validation_criteria=[],
        editable_scope=[],
        forbidden_scope=[],
        merge_point="fanin",
        output_dir="/tmp/hybrid-test",
        required_capabilities=capabilities,
    )


class HybridRuntimeFlowTest(unittest.TestCase):
    def test_hybrid_routes_read_only_to_nvidia_and_write_to_codex(self) -> None:
        with patch("runtime.orchestrator.provider_executor.run_nvidia_reasoning_task", return_value={"status": "completed", "summary": "ok"}) as nvidia, patch(
            "runtime.orchestrator.provider_executor.run_task_prompt",
            return_value={"status": "manual_fallback", "mode": "manual"},
        ) as codex:
            read_result = execute_provider_task(_task(["reasoning", "read_only"]), mode="hybrid", project_root=".", local_worker=lambda task: {})
            write_result = execute_provider_task(_task(["reasoning", "filesystem_write"]), mode="hybrid", project_root=".", local_worker=lambda task: {})
            self.assertEqual(read_result["provider_trace"]["provider"], "nvidia")
            self.assertEqual(write_result["provider"], "codex")
            nvidia.assert_called_once()
            codex.assert_called_once()
            codex.assert_called_with(
                _task(["reasoning", "filesystem_write"]).task_prompt_path,
                _task(["reasoning", "filesystem_write"]).output_dir,
                "codex-cli",
                project_root=".",
                required_capabilities=["reasoning", "filesystem_write"],
            )

    def test_hybrid_routes_read_only_plus_integration_to_codex(self) -> None:
        with patch("runtime.orchestrator.provider_executor.run_nvidia_reasoning_task") as nvidia, patch(
            "runtime.orchestrator.provider_executor.run_task_prompt",
            return_value={"status": "manual_fallback", "mode": "manual"},
        ) as codex:
            result = execute_provider_task(_task(["reasoning", "read_only", "integration"]), mode="hybrid", project_root=".", local_worker=lambda task: {})

            self.assertEqual(result["provider"], "codex")
            self.assertEqual(result["route_reason"], "hybrid_state_changing_to_codex")
            nvidia.assert_not_called()
            codex.assert_called_once()

    def test_governed_hybrid_persists_prepare_checkpoint_and_resumes_without_repeating_provider(self) -> None:
        with cloned_sample_project() as project:
            pool = _write_model_pool(project)
            with patch.dict(
                os.environ, {
                    "NVIDIA_API_KEY": "test-key",
                    "NVIDIA_MODEL": "nvidia/environment-must-not-control-router",
                    "GCH_NVIDIA_MODEL_POOL": str(pool),
                }, clear=False
            ), patch(
                "runtime.orchestrator.provider_executor.run_nvidia_reasoning_task",
                return_value={"status": "completed", "summary": "prepared", "findings": [], "warnings": [], "errors": []},
            ) as nvidia, patch("runtime.orchestrator.provider_executor.run_task_prompt") as codex:
                engine = OrchestrationEngine(project)
                first = engine.run(mode="hybrid", run_id="governed-hybrid")
                prepared = [item for item in first["completed_workers"] if item.get("status") == "prepared"]
                self.assertTrue(prepared)
                codex.assert_not_called()
                self.assertGreater(nvidia.call_count, 0)

                checkpoint = Path(prepared[0]["continuation_checkpoint"])
                self.assertTrue(checkpoint.is_file())
                checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                self.assertEqual(checkpoint_payload["execution_state"], "PREPARED")
                self.assertEqual(checkpoint_payload["next_action"], "GPT_OPERATOR_ACTION_AUTHORIZATION_REQUIRED")
                self.assertEqual(len(checkpoint_payload["last_router_decision_digest"]), 64)
                self.assertEqual(len(checkpoint_payload["last_handoff_digest"]), 64)

                nvidia.reset_mock()
                second = engine.run(mode="hybrid", run_id="governed-hybrid")
                self.assertTrue(any(item.get("status") == "prepared" for item in second["completed_workers"]))
                nvidia.assert_not_called()
                codex.assert_not_called()

                state = engine.status(run_id="governed-hybrid")["state"]
                self.assertEqual(state["operator_stage"], "PREPARE")
                self.assertEqual(state["provider_action_state"], "ACTION_PENDING")
                self.assertTrue(state["continuation_checkpoint"])

    def test_gpt_operator_action_resumes_from_handoff_and_queues_when_codex_unavailable(self) -> None:
        with cloned_sample_project() as project:
            pool = _write_model_pool(project)
            with patch.dict(
                os.environ, {
                    "NVIDIA_API_KEY": "test-key",
                    "NVIDIA_MODEL": "nvidia/environment-must-not-control-router",
                    "CODEX_MODEL": "codex/environment-must-not-control-router",
                    "GCH_NVIDIA_MODEL_POOL": str(pool),
                }, clear=False
            ), patch(
                "runtime.orchestrator.provider_executor.run_nvidia_reasoning_task",
                return_value={"status": "completed", "summary": "prepared", "findings": [], "warnings": [], "errors": []},
            ), patch("runtime.orchestrator.provider_executor.run_task_prompt") as codex:
                engine = OrchestrationEngine(project)
                first = engine.run(mode="hybrid", run_id="operator-action")
                prepared = [item for item in first["completed_workers"] if item.get("status") == "prepared"]
                self.assertTrue(prepared)
                thread_id = str(prepared[0]["thread_id"])

                action = engine.operator_action("operator-action", thread_id)
                self.assertEqual(action["status"], "action_provider_blocked")
                self.assertEqual(action["queue_state"], "QUEUED")
                self.assertEqual(action["runtime_stage"], "ACTION")
                self.assertEqual(action["action_state"], "ACTION_PROVIDER_BLOCKED")
                codex.assert_not_called()

                checkpoint = json.loads(Path(action["continuation_checkpoint"]).read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["current_stage"], "ACTION")
                self.assertEqual(checkpoint["execution_state"], "ACTION_PROVIDER_BLOCKED")
                self.assertEqual(checkpoint["next_action"], "GPT_AUTHORIZED_MANUAL_ACTION_OR_QUEUE_BLOCK")

    def test_gpt_operator_action_uses_file_backed_codex_model_when_approved_policy_exists(self) -> None:
        with cloned_sample_project() as project:
            pool = _write_model_pool(project)
            codex_policy = _write_codex_policy(project)
            with patch.dict(
                os.environ, {
                    "NVIDIA_API_KEY": "test-key",
                    "NVIDIA_MODEL": "nvidia/environment-must-not-control-router",
                    "CODEX_MODEL": "codex/environment-must-not-control-router",
                    "GCH_NVIDIA_MODEL_POOL": str(pool),
                    "GCH_PRE_MPRF_PROVIDER_POLICY": str(codex_policy),
                }, clear=False
            ), patch("runtime.orchestrator.engine.detect_codex_cli", return_value=True), patch(
                "runtime.orchestrator.provider_executor.run_nvidia_reasoning_task",
                return_value={"status": "completed", "summary": "prepared", "findings": [], "warnings": [], "errors": []},
            ), patch(
                "runtime.orchestrator.provider_executor.run_task_prompt",
                return_value={"status": "completed", "summary": "applied", "findings": [], "warnings": [], "errors": []},
            ) as codex:
                engine = OrchestrationEngine(project)
                first = engine.run(mode="hybrid", run_id="operator-action-approved-codex")
                prepared = [item for item in first["completed_workers"] if item.get("status") == "prepared"]
                self.assertTrue(prepared)
                thread_id = str(prepared[0]["thread_id"])

                action = engine.operator_action("operator-action-approved-codex", thread_id)
                self.assertEqual(action["status"], "completed")
                self.assertEqual(action["provider"], "codex")
                self.assertEqual(action["model"], "codex/router-model")
                self.assertEqual(codex.call_args.kwargs["model_ref"], "codex/router-model")
                self.assertNotEqual(codex.call_args.kwargs["model_ref"], os.environ["CODEX_MODEL"])

                checkpoint = json.loads(Path(action["continuation_checkpoint"]).read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["execution_state"], "VERIFY_PENDING")
                self.assertEqual(checkpoint["next_action"], "GPT_OPERATOR_VERIFY_REQUIRED")

    def test_governed_adapter_cannot_use_environment_model_as_substitute(self) -> None:
        with patch.dict(
            os.environ, {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "environment-model"}, clear=True
        ):
            result = run_nvidia_reasoning_task(
                prompt="hello", project_root=".", model=None, require_explicit_model=True
            )
        self.assertEqual(result["status"], "provider_failed")
        self.assertEqual(result["provider_error_class"], "nvidia_config_error")
        self.assertNotEqual(result.get("model"), "environment-model")

    def test_governed_executor_uses_router_bound_nvidia_model(self) -> None:
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1, snapshot_id="S1",
            provider_eligible={"nvidia": True, "codex": False},
            model_refs={"nvidia": "nvidia/router-model"}, evidence_refs=("E1",),
        )
        request = RouterRequestV2(
            schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id="R1", project_id="P1", run_id="RUN1",
            task_id="T1", task_execution_id="E1", directive_digest="d" * 64, stage="PREPARE",
            required_capabilities=("read_only", "reasoning"), state_change_required=False,
            policy_profile=GOVERNED_POLICY_V1, eligibility_snapshot=snapshot,
        )
        decision = route_request(request)
        with patch.dict(os.environ, {"NVIDIA_MODEL": "nvidia/environment-model"}, clear=False), patch(
            "runtime.orchestrator.provider_executor.run_nvidia_reasoning_task",
            return_value={"status": "completed", "summary": "ok"},
        ) as nvidia:
            result = execute_provider_task(
                _task(["read_only", "reasoning"]), mode="hybrid", project_root=".",
                local_worker=lambda task: {}, router_decision=decision,
            )
            self.assertEqual(result["provider_trace"]["model"], "nvidia/router-model")
            self.assertEqual(nvidia.call_args.kwargs["model"], "nvidia/router-model")
            self.assertTrue(nvidia.call_args.kwargs["require_explicit_model"])

    def test_governed_action_block_does_not_fallback_to_another_provider(self) -> None:
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1, snapshot_id="S1",
            provider_eligible={"nvidia": True, "codex": False},
            model_refs={"nvidia": "nvidia/router-model"}, evidence_refs=("E1",),
        )
        request = RouterRequestV2(
            schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id="R2", project_id="P1", run_id="RUN1",
            task_id="T1", task_execution_id="E2", directive_digest="e" * 64, stage="ACTION",
            required_capabilities=("filesystem_write",), state_change_required=True,
            policy_profile=GOVERNED_POLICY_V1, eligibility_snapshot=snapshot,
        )
        decision = route_request(request)
        with patch("runtime.orchestrator.provider_executor.run_nvidia_reasoning_task") as nvidia, patch(
            "runtime.orchestrator.provider_executor.run_task_prompt"
        ) as codex:
            result = execute_provider_task(
                _task(["filesystem_write"]), mode="hybrid", project_root=".",
                local_worker=lambda task: {}, router_decision=decision,
            )
            self.assertEqual(result["status"], "action_provider_blocked")
            self.assertEqual(result["next_step"], "GPT_OPERATOR_REVIEW_REQUIRED")
            nvidia.assert_not_called()
            codex.assert_not_called()

    def test_governed_router_binds_nvidia_model_fallbacks(self) -> None:
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1, snapshot_id="S-FALLBACK",
            provider_eligible={"nvidia": True, "codex": False},
            model_refs={"nvidia": "nvidia/primary"}, evidence_refs=("E1",),
            model_fallback_refs={"nvidia": ("nvidia/fallback-a", "nvidia/fallback-b")},
        )
        request = RouterRequestV2(
            schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id="R-FALLBACK", project_id="P1", run_id="RUN1",
            task_id="T1", task_execution_id="E-FALLBACK", directive_digest="f" * 64, stage="PREPARE",
            required_capabilities=("read_only", "reasoning"), state_change_required=False,
            policy_profile=GOVERNED_POLICY_V1, eligibility_snapshot=snapshot,
        )
        decision = route_request(request)
        self.assertEqual(decision.model_ref, "nvidia/primary")
        self.assertEqual(decision.model_fallback_refs, ("nvidia/fallback-a", "nvidia/fallback-b"))

        with patch(
            "runtime.orchestrator.provider_executor.run_nvidia_reasoning_task",
            return_value={
                "status": "completed", "summary": "ok", "model": "nvidia/fallback-a",
                "routed_model": "nvidia/primary", "model_failover_used": True,
            },
        ) as nvidia:
            result = execute_provider_task(
                _task(["read_only", "reasoning"]), mode="hybrid", project_root=".",
                local_worker=lambda task: {}, router_decision=decision,
            )
        self.assertEqual(nvidia.call_args.kwargs["fallback_models"], decision.model_fallback_refs)
        self.assertEqual(result["provider_trace"]["model"], "nvidia/fallback-a")
        self.assertEqual(result["provider_trace"]["routed_model"], "nvidia/primary")
        self.assertTrue(result["provider_trace"]["model_failover_used"])


if __name__ == "__main__":
    unittest.main()

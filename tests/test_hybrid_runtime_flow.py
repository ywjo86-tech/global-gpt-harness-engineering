from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.orchestrator.provider_executor import execute_provider_task
from runtime.orchestrator.schemas import TaskSlice


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import inspect
import unittest
from pathlib import Path

from runtime.orchestrator.provider_adapter_registry import ProviderAdapterRegistry
from runtime.orchestrator.provider_executor import execute_provider_task
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1,
    GOVERNED_POLICY_V1,
    ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1,
    RouterRequestV2,
    route_request,
)
from runtime.orchestrator.schemas import TaskSlice


def task(output_dir: str) -> TaskSlice:
    return TaskSlice(
        thread_id="T1", assigned_agent="qa_reviewer_agent", input="review", expected_output="handoff",
        validation_criteria=[], editable_scope=[], forbidden_scope=[], merge_point="fanin",
        output_dir=output_dir, required_capabilities=["read_only", "reasoning"],
    )


def third_decision():
    snapshot = ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, "S-X", {"provider-x": True}, {"provider-x": "provider-x/model-1"},
        ("provider-x-admitted",), provider_capabilities={"provider-x": ("read_only", "reasoning")},
    )
    request = RouterRequestV2(
        ROUTER_REQUEST_SCHEMA_V2, "REQ-X", "P1", "R1", "T1", "E1", "d" * 64,
        "PREPARE", ("read_only", "reasoning"), False, GOVERNED_POLICY_V1, snapshot,
    )
    return route_request(request)


class ProviderAdapterRegistryTest(unittest.TestCase):
    def test_governed_dispatch_core_has_no_builtin_provider_postselection_branch(self):
        from runtime.orchestrator import provider_executor
        source = inspect.getsource(provider_executor._execute_governed)
        self.assertNotIn("CODEX_PROVIDER", source)
        self.assertNotIn("NVIDIA_PROVIDER", source)

    def test_third_provider_executes_through_injected_adapter_without_core_branch(self) -> None:
        calls = []
        def adapter(task_obj, decision, project_root):
            calls.append((decision.provider_ref, decision.model_ref, project_root))
            return {"status": "completed", "summary": "third provider ok", "model": decision.model_ref}
        registry = ProviderAdapterRegistry({"provider-x": adapter})
        with tempfile.TemporaryDirectory() as td:
            result = execute_provider_task(
                task(td), mode="hybrid", project_root="/project", local_worker=lambda _: {},
                router_decision=third_decision(), adapter_registry=registry,
            )
        self.assertEqual(calls, [("provider-x", "provider-x/model-1", "/project")])
        self.assertEqual(result["provider"], "provider-x")
        self.assertEqual(result["model"], "provider-x/model-1")

    def test_unknown_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = execute_provider_task(
                task(td), mode="hybrid", project_root="/project", local_worker=lambda _: {},
                router_decision=third_decision(), adapter_registry=ProviderAdapterRegistry({}),
            )
        self.assertEqual(result["status"], "route_blocked")
        self.assertEqual(result["errors"], ["provider_adapter_unavailable"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.production_worker_executor import (
    NVIDIA_EXECUTOR_ID,
    NVIDIA_READ_ONLY_BACKEND,
    READ_ONLY_EXECUTION_MODE,
    execute_production_worker,
)
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1,
    ProviderEligibilitySnapshotV1,
    normalize_legacy_hybrid_request,
    route_request,
)
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest


class ProductionProviderRouterIntegrationTests(unittest.TestCase):
    def _request(self, root: Path) -> WorkerRequest:
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Router Fixture"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "router@example.invalid"], check=True)
        (root / "docs").mkdir()
        (root / "docs" / "evidence.md").write_text("baseline\n")
        (root / ".gitignore").write_text("out/\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

        capabilities = ["reasoning", "read_only", "evidence_analysis", "review", "documentation"]
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1,
            snapshot_id="nvidia-only",
            provider_eligible={"nvidia": True, "codex": False},
            model_refs={"nvidia": "nvidia/test-read-model"},
            evidence_refs=("unit-nvidia-ready", "unit-codex-unavailable"),
        )
        route = normalize_legacy_hybrid_request(
            required_capabilities=capabilities,
            eligibility_snapshot=snapshot,
            request_id="route-read-only",
            project_id="fixture-project",
            run_id="run-router",
            task_id="TASK-READ",
            task_execution_id="run-router-TASK-READ-worker",
            directive_digest="d" * 64,
        )
        decision = route_request(route)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.provider_ref, "nvidia")

        binding = {
            "schema_version": "orchestration.canonical-launch-authority.v1",
            "execution_obligation": "READ_ONLY_EXECUTION",
        }
        task = TaskSlice(
            thread_id="TASK-READ",
            assigned_agent="implementation_agent",
            input="Review the existing documentation evidence without changing files.",
            expected_output="read-only review",
            validation_criteria=["documentation evidence remains valid"],
            editable_scope=["docs/"],
            forbidden_scope=[],
            merge_point="GATE_EXIT",
            run_id="run-router",
            run_root=str(root / "out"),
            output_dir=str(root / "out"),
            result_path=str(root / "out" / "worker.result.json"),
            required_capabilities=capabilities,
            task_execution_id="run-router-TASK-READ-worker",
        )
        return WorkerRequest(
            project_root=str(root),
            task=task,
            contract_summary={
                "project_id": "fixture-project",
                "gate_id": "GATE-READ",
                "lv_id": "TASK-READ",
                "canonical_plan_sha256": "a" * 64,
            },
            state_snapshot={"branch": "main", "head": head},
            extra_context={
                "execution_mode": "production",
                "execution_backend": NVIDIA_READ_ONLY_BACKEND,
                "run_id": "run-router",
                "run_root": str(root / "out"),
                "attempt": 1,
                "approval_event_id": "APR-READ",
                "package_manifest_sha256": "b" * 64,
                "preflight_evidence_sha256": "c" * 64,
                "source_snapshot": {"source_head": head},
                "task_effect_requirement": "READ_ONLY_EXECUTION",
                "allow_read_only_execution": True,
                "canonical_authority_binding": binding,
                "canonical_authority_binding_digest": hashlib.sha256(
                    canonical_json_bytes(binding)
                ).hexdigest(),
                "provider_route": {
                    "request": route.to_dict(),
                    "decision": decision.to_dict(),
                },
            },
        )

    def test_router_selected_nvidia_read_only_worker_never_invokes_codex_or_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            baseline = request.state_snapshot["head"]
            provider_result = {
                "status": "completed",
                "provider": "nvidia",
                "model": "nvidia/test-read-model",
                "routed_model": "nvidia/test-read-model",
                "model_failover_used": False,
                "provider_attempts": 1,
                "route_reason": "nvidia_read_only",
                "summary": "READ_ONLY_REVIEW_PASS",
                "warnings": [],
                "errors": [],
            }
            with patch(
                "runtime.orchestrator.production_worker_executor.run_nvidia_reasoning_task",
                return_value=provider_result,
            ) as nvidia, patch(
                "runtime.orchestrator.production_worker_executor.CodexExecutionAdapter.argv",
                side_effect=AssertionError("Codex must not be invoked for NVIDIA read-only work"),
            ):
                result = execute_production_worker(request)

            self.assertEqual(result["completion_mode"], READ_ONLY_EXECUTION_MODE)
            self.assertEqual(result["executor"]["identity"], NVIDIA_EXECUTOR_ID)
            self.assertEqual(result["changed_files"], [])
            self.assertEqual(result["checkpoint_commit"], baseline)
            self.assertEqual(result["verification_authority"]["provider"], "nvidia")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(root), "status", "--porcelain"], text=True
                ),
                "",
            )
            nvidia.assert_called_once()

    def test_nvidia_read_only_backend_rejects_state_changing_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self._request(root)
            request.task.required_capabilities.append("filesystem_write")
            with self.assertRaisesRegex(Exception, "NVIDIA_READ_ONLY_AUTHORITY_REQUIRED"):
                execute_production_worker(request)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import (
    GateLV, GateOrchestrationError, GatePlan, create_gate_authorization, execute_gate,
    load_project_requirement_contract, project_lv_execution_state,
)
from runtime.orchestrator.task_contract_compat import resolve_task_project_requirement_contract


TASK_CONTRACT = '''# Contract

## TASK-001 — bootstrap
Purpose: Bootstrap safely.
Related Requirements: NFR-008
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write, shell, test, git, implementation
Validation: TEST-001
Completion Condition: Both skeletons build.

## GATE-001 — first
Required Tasks: TASK-001

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| NFR-008 | Keep architecture extensible. | No user-specific core logic. | MUST |
'''


class TaskExecutionEntryBridgeTests(unittest.TestCase):
    def _plan(self, root: Path) -> tuple[GatePlan, object, Path, str]:
        path = root / "docs" / "DEVELOPMENT_PLAN.txt"
        path.parent.mkdir(parents=True)
        path.write_text("canonical\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lvs = [
            GateLV("GATE-001", "TASK-001", 1, "bootstrap", [], ["app/"], ["pass"], "SEQUENTIAL", ["TEST-001"]),
            GateLV("GATE-001", "TASK-002", 2, "profile", ["TASK-001"], ["profile/"], ["pass"], "SEQUENTIAL", ["TEST-002"]),
        ]
        plan = GatePlan(root.name, str(root), "GATE-001", "docs/DEVELOPMENT_PLAN.txt", digest, lvs)
        auth = create_gate_authorization(plan, "APR-1")
        return plan, auth, path, digest

    def test_full_gate_active_scope_is_narrowed_without_ledger_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan, auth, path, digest = self._plan(root)
            mapping = SimpleNamespace(canonical_source=path, canonical_sha256=digest)
            state = {
                "state": "GATE1_ACTIVE", "transition_authorized": True, "gate_id": "GATE-001",
                "selected_source": path, "canonical_plan": "docs/DEVELOPMENT_PLAN.txt",
                "plan_sha256": digest, "active_scope": ["TASK-001", "TASK-002"], "owned_files": ["legacy-flat-scope"],
            }
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping), \
                 patch("runtime.orchestrator.gate_orchestrator.evaluate_canonical_state", return_value=state):
                projected = project_lv_execution_state(root, plan, auth, "TASK-001")
            self.assertEqual(projected["active_scope"], ["TASK-001"])
            self.assertEqual(projected["owned_files"], ["app/"])
            self.assertEqual(state["active_scope"], ["TASK-001", "TASK-002"])

    def test_partial_or_unrelated_active_scope_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan, auth, path, digest = self._plan(root)
            mapping = SimpleNamespace(canonical_source=path, canonical_sha256=digest)
            state = {
                "state": "GATE1_ACTIVE", "transition_authorized": True, "gate_id": "GATE-001",
                "selected_source": path, "canonical_plan": "docs/DEVELOPMENT_PLAN.txt",
                "plan_sha256": digest, "active_scope": ["TASK-002"], "owned_files": ["profile/"],
            }
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping), \
                 patch("runtime.orchestrator.gate_orchestrator.evaluate_canonical_state", return_value=state):
                with self.assertRaisesRegex(GateOrchestrationError, "cannot be projected"):
                    project_lv_execution_state(root, plan, auth, "TASK-001")

    def test_execute_gate_injects_task_scoped_state_only_for_task_projection_mapping(self) -> None:
        class StopLifecycle(RuntimeError):
            pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan, auth, path, digest = self._plan(root)
            projected = {
                "state": "GATE1_ACTIVE", "transition_authorized": True, "gate_id": "GATE-001",
                "selected_source": path, "canonical_plan": "docs/DEVELOPMENT_PLAN.txt",
                "plan_sha256": digest, "active_scope": ["TASK-001"], "owned_files": ["app/"],
            }
            task_mapping = SimpleNamespace(task_lv_projection_path=root / "projection.json")
            captured = {}
            def stop(context, adapters):
                captured.update(context)
                raise StopLifecycle("captured")
            with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan", return_value=plan), \
                 patch("runtime.orchestrator.gate_orchestrator.validate_global_gate_bindings", return_value={}), \
                 patch("runtime.orchestrator.gate_orchestrator.load_approved_authorization", return_value=auth), \
                 patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=task_mapping), \
                 patch("runtime.orchestrator.gate_orchestrator.project_lv_execution_state", return_value=projected) as projection_call, \
                 patch("runtime.orchestrator.gate_orchestrator.run_gate_lifecycle", side_effect=stop):
                with self.assertRaisesRegex(StopLifecycle, "captured"):
                    execute_gate(
                        root, "GATE-001", "run-1", harness_root=root.parent, adapters=object(),
                        approval_evidence=root / "approval.json", requirements_sha256="a" * 64,
                        branch="main", head="b" * 40, requirement_evidence={},
                    )
            projection_call.assert_called_once_with(root, plan, auth, "TASK-001")
            self.assertEqual(captured["canonical_state_override"]["active_scope"], ["TASK-001"])

    def test_requirement_contract_is_deterministic_and_semantically_bound(self) -> None:
        digest = hashlib.sha256(TASK_CONTRACT.encode()).hexdigest()
        first = resolve_task_project_requirement_contract(
            TASK_CONTRACT, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-001", task_id="TASK-001", owned_files=["app/", "backend/"],
        )
        second = resolve_task_project_requirement_contract(
            TASK_CONTRACT, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-001", task_id="TASK-001", owned_files=["app/", "backend/"],
        )
        self.assertEqual(first, second)
        self.assertEqual(list(first["requirements"]), ["NFR-008"])
        item = first["requirements"]["NFR-008"]
        self.assertEqual(item["validation_ids"], ["TEST-001"])
        self.assertEqual(item["semantic_metadata"]["priority"], "MUST")

    def test_requirement_loader_rejects_semantic_tamper(self) -> None:
        digest = hashlib.sha256(TASK_CONTRACT.encode()).hexdigest()
        payload = resolve_task_project_requirement_contract(
            TASK_CONTRACT, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-001", task_id="TASK-001", owned_files=["app/"],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_project_requirement_contract(
                path, project_id="task-project", gate_id="GATE-001", lv_id="TASK-001",
                plan_sha256=digest, expected_requirement_ids=("NFR-008",),
            )
            self.assertEqual(tuple(loaded), ("NFR-008",))
            payload["requirements"]["NFR-008"]["semantic_metadata"]["priority"] = "SHOULD"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GateOrchestrationError, "semantic metadata SHA drift"):
                load_project_requirement_contract(
                    path, project_id="task-project", gate_id="GATE-001", lv_id="TASK-001",
                    plan_sha256=digest, expected_requirement_ids=("NFR-008",),
                )


if __name__ == "__main__":
    unittest.main()

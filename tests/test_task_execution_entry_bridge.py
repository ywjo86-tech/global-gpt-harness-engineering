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
from runtime.orchestrator.lv_review import LVReviewError, _project_task_execution_binding


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

TASK_REVIEW_CONTRACT = r'''# Contract

## TASK-001 — bootstrap
Purpose: Bootstrap safely.
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write, shell, test, git, implementation
Validation: TEST-001
Completion Condition: Bootstrap passes.

## TASK-002 — profile
Purpose: Build profile.
Dependencies: TASK-001
Change Targets: CT-002
Required Capabilities: reasoning, filesystem_write, shell, test, git, implementation
Validation: TEST-002
Completion Condition: Profile passes.

| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | `app/` | CREATE | TASK-001 | PLANNED_NEW |
| CT-002 | `profile/` | CREATE | TASK-002 | PLANNED_NEW |

| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |
| TASK-002 | SEQUENTIAL | TASK-001 | Upstream |

## GATE-001 — first
Required Tasks: TASK-001, TASK-002
'''


def review_projection(plan_sha: str) -> dict:
    return {
        "schema_version": "orchestration.task-lv-authority-projection.v1",
        "project_id": "task-project",
        "canonical_plan_sha256": plan_sha,
        "contract_shape": "TASK_STAGE_GATE",
        "projection_policy": {
            "lv_identity": "TASK_ID",
            "gate_membership": "CANONICAL_GATE_REQUIRED_TASKS",
            "dependencies": "CANONICAL_TASK_DEPENDENCIES",
            "execution": "CANONICAL_TASK_DEPENDENCY_TYPE",
            "completion_criteria": "CANONICAL_TASK_COMPLETION_CONDITION_PLUS_VALIDATION",
            "provider_capabilities": "CANONICAL_TASK_REQUIRED_CAPABILITIES",
            "operational_capability": "DECLARED_NONE",
        },
        "change_targets": {
            "CT-001": {"source_expression": "app/", "owned_files": ["app/"]},
            "CT-002": {"source_expression": "profile/", "owned_files": ["profile/"]},
        },
    }


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

    def test_review_binding_projects_gate_scope_through_sha_bound_task_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"; plan.parent.mkdir(parents=True)
            plan.write_text(TASK_REVIEW_CONTRACT, encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            projection_path = root / "docs" / "projection.json"
            projection_path.write_text(json.dumps(review_projection(plan_sha), sort_keys=True), encoding="utf-8")
            mapping = SimpleNamespace(
                project_id="task-project", canonical_source=plan, canonical_sha256=plan_sha,
                task_lv_projection_path=projection_path,
                task_lv_projection_sha256=hashlib.sha256(projection_path.read_bytes()).hexdigest(),
            )
            state = {"state":"GATE1_ACTIVE", "gate_id":"GATE-001",
                     "active_scope":["TASK-001","TASK-002"], "owned_files":["app/"]}
            manifest = {"gate_id":"GATE-001", "lv_id":"TASK-001",
                        "active_scope":["TASK-001"], "owned_files":["app/"]}
            projected = _project_task_execution_binding(root, mapping, state, manifest)
            self.assertEqual(projected["active_scope"], ["TASK-001"])
            self.assertEqual(projected["owned_files"], ["app/"])
            self.assertEqual(state["active_scope"], ["TASK-001", "TASK-002"])

    def test_review_binding_rejects_projection_or_gate_scope_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"; plan.parent.mkdir(parents=True)
            plan.write_text(TASK_REVIEW_CONTRACT, encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            projection_path = root / "docs" / "projection.json"
            projection_path.write_text(json.dumps(review_projection(plan_sha), sort_keys=True), encoding="utf-8")
            mapping = SimpleNamespace(
                project_id="task-project", canonical_source=plan, canonical_sha256=plan_sha,
                task_lv_projection_path=projection_path, task_lv_projection_sha256="0" * 64,
            )
            state = {"state":"GATE1_ACTIVE", "gate_id":"GATE-001",
                     "active_scope":["TASK-001","TASK-002"], "owned_files":["app/"]}
            manifest = {"gate_id":"GATE-001", "lv_id":"TASK-001",
                        "active_scope":["TASK-001"], "owned_files":["app/"]}
            with self.assertRaisesRegex(LVReviewError, "task_projection"):
                _project_task_execution_binding(root, mapping, state, manifest)
            mapping.task_lv_projection_sha256 = hashlib.sha256(projection_path.read_bytes()).hexdigest()
            state["active_scope"] = ["TASK-002", "TASK-001"]
            with self.assertRaisesRegex(LVReviewError, "active_scope"):
                _project_task_execution_binding(root, mapping, state, manifest)

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

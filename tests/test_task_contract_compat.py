import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import compatibility_dry_run, load_gate_plan
from runtime.orchestrator.lv_preview import preview_lv_read_only
from runtime.orchestrator.task_contract_compat import (
    TaskContractProjectionError,
    analyze_task_stage_gate_contract,
    compatibility_block_reason,
    resolve_task_lv_projection,
    validate_task_lv_authority_projection,
)


FORWARD_CONTRACT = '''# Contract

## TASK-001 — bootstrap
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write

## TASK-002 — safety
Dependencies: TASK-003
Change Targets: CT-002
Required Capabilities: reasoning, filesystem_write

## TASK-003 — curriculum
Dependencies: TASK-001
Change Targets: CT-003
Required Capabilities: reasoning, filesystem_write

## GATE-001 — first
Required Tasks: TASK-001, TASK-002

## GATE-002 — second
Required Tasks: TASK-003
'''

DUPLICATE_CONTRACT = '''# Contract

## TASK-001 — shared safety
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write

## GATE-001 — first
Required Tasks: TASK-001

## GATE-002 — second
Required Tasks: TASK-001
'''

CONSISTENT_CONTRACT = '''# Contract

## TASK-001 — bootstrap
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write

## GATE-001 — first
Required Tasks: TASK-001
'''

PROJECTABLE_CONTRACT = '''# Contract

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
Validation: TEST-002, TEST-003
Completion Condition: Profile passes.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | `app/ + backend/` | CREATE | TASK-001 | PLANNED_NEW |
| CT-002 | `app/profile/` | CREATE | TASK-002 | PLANNED_NEW |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |
| TASK-002 | SEQUENTIAL | TASK-001 | Upstream |

## GATE-001 — first
Required Tasks: TASK-001, TASK-002
'''


def projection(plan_sha: str) -> dict:
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
            "CT-001": {"source_expression": "app/ + backend/", "owned_files": ["app/", "backend/"]},
            "CT-002": {"source_expression": "app/profile/", "owned_files": ["app/profile/"]},
        },
    }


class TaskContractCompatibilityTests(unittest.TestCase):
    def test_forward_stage_dependency_is_reported(self) -> None:
        analysis = analyze_task_stage_gate_contract(FORWARD_CONTRACT, "GATE-001")
        self.assertIsNotNone(analysis)
        self.assertEqual(len(analysis["forward_dependency_violations"]), 1)
        self.assertIn("not executable without contract revision", compatibility_block_reason(analysis))

    def test_duplicate_stage_binding_requires_explicit_projection(self) -> None:
        analysis = analyze_task_stage_gate_contract(DUPLICATE_CONTRACT, "GATE-001")
        self.assertEqual(analysis["duplicate_task_bindings"], {"TASK-001": ["GATE-001", "GATE-002"]})
        self.assertIn("execute-vs-evidence", compatibility_block_reason(analysis))

    def test_consistent_task_contract_remains_fail_closed_without_projection(self) -> None:
        analysis = analyze_task_stage_gate_contract(CONSISTENT_CONTRACT, "GATE-001")
        self.assertEqual(analysis["blockers"], [])
        self.assertTrue(analysis["runtime_projection_ready"])
        self.assertIn("no approved TASK-to-LV authority projection", compatibility_block_reason(analysis))

    def test_non_task_contract_is_not_claimed(self) -> None:
        self.assertIsNone(analyze_task_stage_gate_contract("# legacy\n\n### Gate 1\n", "GATE-1"))

    def test_gate_dry_run_reports_task_contract_diagnostics_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"
            root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"
            plan.parent.mkdir(parents=True)
            plan.write_text(FORWARD_CONTRACT, encoding="utf-8")
            mapping = SimpleNamespace(
                canonical_source=plan,
                canonical_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            )
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping):
                result = compatibility_dry_run(root, "GATE-001")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["contract_shape"], "TASK_STAGE_GATE")
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(len(result["task_contract_analysis"]["forward_dependency_violations"]), 1)
        self.assertIn("canonical plan must contain exactly one section", result["legacy_gate_parser_reason"])

    def test_valid_projection_resolves_task_authority_without_provider_hardcoding(self) -> None:
        plan_sha = hashlib.sha256(PROJECTABLE_CONTRACT.encode()).hexdigest()
        value = projection(plan_sha)
        validated = validate_task_lv_authority_projection(
            PROJECTABLE_CONTRACT, value, project_id="task-project", canonical_plan_sha256=plan_sha
        )
        self.assertEqual(set(validated["change_targets"]), {"CT-001", "CT-002"})
        resolved = resolve_task_lv_projection(
            PROJECTABLE_CONTRACT, value, project_id="task-project", canonical_plan_sha256=plan_sha, gate_id="GATE-001"
        )
        self.assertEqual([item["lv_id"] for item in resolved], ["TASK-001", "TASK-002"])
        self.assertEqual(resolved[0]["owned_files"], ["app/", "backend/"])
        self.assertEqual(resolved[1]["dependencies"], ["TASK-001"])
        self.assertIn("filesystem_write", resolved[0]["required_capabilities"])
        self.assertEqual(resolved[0]["capability_contract"]["mode"], "DECLARED_NONE")

    def test_projection_rejects_plan_sha_source_drift_and_unsafe_scope(self) -> None:
        plan_sha = hashlib.sha256(PROJECTABLE_CONTRACT.encode()).hexdigest()
        value = projection(plan_sha)
        with self.assertRaisesRegex(TaskContractProjectionError, "canonical plan SHA mismatch"):
            validate_task_lv_authority_projection(
                PROJECTABLE_CONTRACT, value, project_id="task-project", canonical_plan_sha256="0" * 64
            )
        drift = projection(plan_sha); drift["change_targets"]["CT-001"]["source_expression"] = "other/"
        with self.assertRaisesRegex(TaskContractProjectionError, "source drift"):
            validate_task_lv_authority_projection(
                PROJECTABLE_CONTRACT, drift, project_id="task-project", canonical_plan_sha256=plan_sha
            )
        unsafe = projection(plan_sha); unsafe["change_targets"]["CT-001"]["owned_files"] = ["../escape"]
        with self.assertRaisesRegex(TaskContractProjectionError, "unsafe projection owned path"):
            validate_task_lv_authority_projection(
                PROJECTABLE_CONTRACT, unsafe, project_id="task-project", canonical_plan_sha256=plan_sha
            )

    def test_gate_loader_and_dry_run_use_explicit_task_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"; plan.parent.mkdir(parents=True)
            plan.write_text(PROJECTABLE_CONTRACT, encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            projection_path = root / "docs" / "projection.json"
            projection_path.write_text(json.dumps(projection(plan_sha)), encoding="utf-8")
            mapping = SimpleNamespace(
                project_id="task-project",
                canonical_source=plan, canonical_sha256=plan_sha,
                task_lv_projection_path=projection_path,
                task_lv_projection_sha256=hashlib.sha256(projection_path.read_bytes()).hexdigest(),
            )
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping):
                plan_value = load_gate_plan(root, "GATE-001")
                result = compatibility_dry_run(root, "GATE-001")
        self.assertEqual([item.lv_id for item in plan_value.lvs], ["TASK-001", "TASK-002"])
        self.assertEqual(plan_value.lvs[0].required_capabilities[0], "reasoning")
        self.assertEqual(result["status"], "COMPATIBLE")
        self.assertEqual(result["lv_order"], ["TASK-001", "TASK-002"])
        self.assertFalse(result["mutation_performed"])

    def test_projected_lv_preview_uses_sha_bound_owned_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"; plan.parent.mkdir(parents=True)
            plan.write_text(PROJECTABLE_CONTRACT, encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            projection_path = root / "docs" / "projection.json"
            projection_path.write_text(json.dumps(projection(plan_sha)), encoding="utf-8")
            mapping = SimpleNamespace(
                project_id="task-project",
                canonical_source=plan, canonical_sha256=plan_sha,
                task_lv_projection_path=projection_path,
                task_lv_projection_sha256=hashlib.sha256(projection_path.read_bytes()).hexdigest(),
            )
            state = {
                "state": "GATE1_ACTIVE", "gate_id": "GATE-001",
                "selected_source": plan, "canonical_plan": "docs/DEVELOPMENT_PLAN.txt",
                "plan_sha256": plan_sha, "active_scope": ["TASK-001"],
                "owned_files": ["app/", "backend/"],
            }
            inspection = {
                "business_gate_state": {}, "business_lv_approval_state": {},
                "codex_runtime_sandbox_approval_state": {},
            }
            with patch("runtime.orchestrator.lv_preview.load_project_mapping", return_value=mapping), \
                 patch("runtime.orchestrator.lv_preview.inspect_read_only", return_value=inspection):
                result = preview_lv_read_only(root, "GATE-001", "TASK-001", canonical_state_override=state)
        self.assertEqual(result["selected_lv"]["lv_id"], "TASK-001")
        self.assertEqual(result["selected_lv"]["owned_files"], ["app/", "backend/"])
        self.assertFalse(result["mutation_permitted"])


if __name__ == "__main__":
    unittest.main()

class TaskDependencyDeadlockTests(unittest.TestCase):
    def test_dependency_cycle_is_runtime_blocker(self) -> None:
        text = '''
## TASK-001 — one
Dependencies: TASK-002
Required Capabilities: reasoning
Change Targets: CT-001
## TASK-002 — two
Dependencies: TASK-001
Required Capabilities: reasoning
Change Targets: CT-002
## GATE-001 — gate
Required Tasks: TASK-001, TASK-002
'''
        analysis = analyze_task_stage_gate_contract(text, "GATE-001")
        self.assertIsNotNone(analysis)
        self.assertIn("TASK dependency graph contains a cycle", analysis["blockers"])
        self.assertTrue(analysis["dependency_cycles"])
        self.assertFalse(analysis["runtime_projection_ready"])

    def test_dependency_on_unstaged_task_is_runtime_blocker(self) -> None:
        text = '''
## TASK-001 — one
Dependencies: TASK-002
Required Capabilities: reasoning
Change Targets: CT-001
## TASK-002 — two
Dependencies: NONE
Required Capabilities: reasoning
Change Targets: CT-002
## GATE-001 — gate
Required Tasks: TASK-001
'''
        analysis = analyze_task_stage_gate_contract(text, "GATE-001")
        self.assertIsNotNone(analysis)
        self.assertIn("TASK dependency exists but is not staged by any Gate", analysis["blockers"])
        self.assertEqual(analysis["unstaged_dependencies"], [{"task_id": "TASK-001", "dependency": "TASK-002"}])


class TaskContractBulletAndRangeCompatibilityTests(unittest.TestCase):
    BULLET_RANGE_CONTRACT = """# Contract

## TASK-001 — entry
Purpose: Verify entry.
Dependencies: NONE
Change Targets:
- CT-001
Required Capabilities:
- reasoning
- read_only
Validation:
- TEST-001
Completion Condition: Entry passes.

## TASK-002 — implement
Purpose: Implement boundary.
Dependencies:
- TASK-001
Change Targets:
- CT-002
Required Capabilities:
- reasoning
- implementation
- filesystem_write
Validation:
- TEST-002
- TEST-003
Completion Condition: Boundary passes.

## TASK-003 — integrate
Purpose: Integrate boundary.
Dependencies:
- TASK-002
Change Targets:
- CT-003
Required Capabilities:
- reasoning
- implementation
Validation:
- TEST-004
Completion Condition: Integration passes.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | docs/DEVELOPMENT_PLAN.txt | VERIFY | TASK-001 | VERIFIED |
| CT-002 | runtime/example.py | CREATE | TASK-002 | PLANNED_CREATE |
| CT-003 | tests/test_example.py | CREATE | TASK-003 | PLANNED_CREATE |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | EXTERNAL | NONE | Entry |
| TASK-002 | SEQUENTIAL | TASK-001 | Boundary |
| TASK-003 | SEQUENTIAL | TASK-002 | Integration |

## GATE-001 — entry
Required Tasks: TASK-001

## GATE-002 — implementation
Required Tasks: TASK-002~003
"""

    def test_multiline_bullets_and_compact_task_ranges_are_projection_ready(self) -> None:
        analysis = analyze_task_stage_gate_contract(self.BULLET_RANGE_CONTRACT, "GATE-002")
        self.assertEqual(analysis["blockers"], [])
        self.assertEqual(analysis["requested_gate_tasks"], ["TASK-002", "TASK-003"])
        self.assertTrue(analysis["runtime_projection_ready"])

    def test_unquoted_change_target_paths_and_multiline_fields_resolve(self) -> None:
        plan_sha = hashlib.sha256(self.BULLET_RANGE_CONTRACT.encode()).hexdigest()
        value = {
            "schema_version": "orchestration.task-lv-authority-projection.v1",
            "project_id": "task-project",
            "canonical_plan_sha256": plan_sha,
            "contract_shape": "TASK_STAGE_GATE",
            "projection_policy": projection(plan_sha)["projection_policy"],
            "change_targets": {
                "CT-001": {"source_expression": "docs/DEVELOPMENT_PLAN.txt", "owned_files": ["docs/DEVELOPMENT_PLAN.txt"]},
                "CT-002": {"source_expression": "runtime/example.py", "owned_files": ["runtime/example.py"]},
                "CT-003": {"source_expression": "tests/test_example.py", "owned_files": ["tests/test_example.py"]},
            },
        }
        resolved = resolve_task_lv_projection(
            self.BULLET_RANGE_CONTRACT, value,
            project_id="task-project", canonical_plan_sha256=plan_sha, gate_id="GATE-002",
        )
        self.assertEqual([item["lv_id"] for item in resolved], ["TASK-002", "TASK-003"])
        self.assertEqual(resolved[0]["dependencies"], ["TASK-001"])
        self.assertEqual(resolved[0]["tests"], ["TEST-002", "TEST-003"])
        self.assertEqual(resolved[0]["required_capabilities"], ["reasoning", "implementation", "filesystem_write"])

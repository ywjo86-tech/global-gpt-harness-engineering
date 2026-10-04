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
    resolve_task_project_requirement_contract,
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

    def test_legacy_projection_does_not_infer_dependency_type_from_prose(self) -> None:
        contract = """# Contract

## TASK-001 — bootstrap
Purpose: Bootstrap safely.
Dependencies: NONE, SEQUENTIAL
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write
Validation: TEST-001
Completion Condition: Bootstrap passes.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | app/ | CREATE | TASK-001 | PLANNED_NEW |

## GATE-001 — first
Required Tasks: TASK-001
"""
        plan_sha = hashlib.sha256(contract.encode()).hexdigest()
        value = projection(plan_sha)
        value["change_targets"] = {
            "CT-001": {"source_expression": "app/", "owned_files": ["app/"]},
        }
        with self.assertRaisesRegex(TaskContractProjectionError, "dependency type is missing"):
            resolve_task_lv_projection(
                contract, value, project_id="task-project",
                canonical_plan_sha256=plan_sha, gate_id="GATE-001",
            )

    def test_legacy_projection_does_not_use_evidence_as_validation(self) -> None:
        contract = """# Contract

## TASK-001 — bootstrap
Purpose: Bootstrap safely.
Dependencies: NONE
Change Targets: CT-001
Required Capabilities: reasoning, filesystem_write
Evidence: EV-R01
Completion Condition: Bootstrap passes.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | app/ | CREATE | TASK-001 | PLANNED_NEW |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |

## GATE-001 — first
Required Tasks: TASK-001
"""
        plan_sha = hashlib.sha256(contract.encode()).hexdigest()
        value = projection(plan_sha)
        value["change_targets"] = {
            "CT-001": {"source_expression": "app/", "owned_files": ["app/"]},
        }
        with self.assertRaisesRegex(TaskContractProjectionError, "runtime authority fields are incomplete"):
            resolve_task_lv_projection(
                contract, value, project_id="task-project",
                canonical_plan_sha256=plan_sha, gate_id="GATE-001",
            )

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
            mapping_root = Path(directory) / "mappings"
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping) as loader:
                plan_value = load_gate_plan(root, "GATE-001", mapping_root=mapping_root)
                loader.assert_called_once_with(root.resolve(), mapping_root=mapping_root)
                loader.reset_mock()
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


    def test_recovery_requirement_contract_expands_compact_related_requirement_ids(self) -> None:
        contract = """# Contract

### TASK-R05 — Guard
- 목적: Verify compact requirement projection.
- 관련: REQ-010/015/017~018, NFR-001~003/006, SEC-003/005, OPS-004/008/009.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: CMP-R03 명시 파일.
- Required Capabilities: implementation, test.
- Execution Authority: STATE_CHANGING.
- Evidence: EV-R12, EV-R13, EV-R14.
- 완료 조건: guard PASS.

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| REQ-010 | r10 | a | MUST |
| REQ-015 | r15 | a | MUST |
| REQ-017 | r17 | a | MUST |
| REQ-018 | r18 | a | MUST |
| NFR-001 | n1 | a | MUST |
| NFR-002 | n2 | a | MUST |
| NFR-003 | n3 | a | MUST |
| NFR-006 | n6 | a | MUST |
| SEC-003 | s3 | a | MUST |
| SEC-005 | s5 | a | MUST |
| OPS-004 | o4 | a | MUST |
| OPS-008 | o8 | a | MUST |
| OPS-009 | o9 | a | MUST |

### GATE-R04 — Guard
Required Tasks: TASK-R05
"""
        digest = hashlib.sha256(contract.encode()).hexdigest()
        projected = resolve_task_project_requirement_contract(
            contract, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-R04", task_id="TASK-R05", owned_files=["runtime/guard.py"],
        )
        self.assertEqual(list(projected["requirements"]), [
            "REQ-010", "REQ-015", "REQ-017", "REQ-018",
            "NFR-001", "NFR-002", "NFR-003", "NFR-006",
            "SEC-003", "SEC-005", "OPS-004", "OPS-008", "OPS-009",
        ])

    def test_recovery_requirement_contract_rejects_descending_compact_range(self) -> None:
        contract = """# Contract

### TASK-R05 — Guard
- 목적: Verify fail closed.
- 관련: REQ-010~008.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: CMP-R03 명시 파일.
- Required Capabilities: implementation.
- Execution Authority: STATE_CHANGING.
- Evidence: EV-R12.
- 완료 조건: blocked.

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| REQ-010 | r10 | a | MUST |

### GATE-R04 — Guard
Required Tasks: TASK-R05
"""
        digest = hashlib.sha256(contract.encode()).hexdigest()
        with self.assertRaises(TaskContractProjectionError):
            resolve_task_project_requirement_contract(
                contract, project_id="task-project", canonical_plan_sha256=digest,
                gate_id="GATE-R04", task_id="TASK-R05", owned_files=["runtime/guard.py"],
            )

    def test_recovery_read_only_requirement_contract_uses_ev_evidence_and_empty_owned_scope(self) -> None:
        contract = """# Contract

### TASK-R01 — Entry/Drift revalidation
- 목적: Verify exact entry binding.
- 관련: REQ-001, OPS-003.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: 없음(읽기 전용).
- Required Capabilities: reasoning, read_only, evidence_analysis.
- Execution Authority: READ_ONLY.
- Evidence: EV-R01, EV-R02, EV-R03.
- 완료 조건: unresolved drift 0.

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| REQ-001 | Bind approved identity. | exact identity | MUST |
| OPS-003 | Preserve source binding. | source exact | MUST |

### GATE-R01 — Entry
Required Tasks: TASK-R01
"""
        digest = hashlib.sha256(contract.encode()).hexdigest()
        projected = resolve_task_project_requirement_contract(
            contract, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-R01", task_id="TASK-R01", owned_files=[],
        )
        self.assertEqual(list(projected["requirements"]), ["REQ-001", "OPS-003"])
        for item in projected["requirements"].values():
            self.assertEqual(item["validation_ids"], ["EV-R01", "EV-R02", "EV-R03"])
            self.assertEqual(item["owned_files"], [])

    def test_recovery_read_only_requirement_contract_rejects_read_only_prefixed_mutation_authority(self) -> None:
        contract = """# Contract

### TASK-R01 — Entry/Drift revalidation
- 목적: Verify exact entry binding.
- 관련: REQ-001.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: 없음(읽기 전용).
- Required Capabilities: reasoning, read_only.
- Execution Authority: READ_ONLY_MUTATION.
- Evidence: EV-R01.
- 완료 조건: unresolved drift 0.

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| REQ-001 | Bind approved identity. | exact identity | MUST |

### GATE-R01 — Entry
Required Tasks: TASK-R01
"""
        digest = hashlib.sha256(contract.encode()).hexdigest()
        with self.assertRaises(TaskContractProjectionError):
            resolve_task_project_requirement_contract(
                contract, project_id="task-project", canonical_plan_sha256=digest,
                gate_id="GATE-R01", task_id="TASK-R01", owned_files=[],
            )

    def test_recovery_mutation_requirement_contract_uses_ev_evidence_fallback(self) -> None:
        contract = """# Contract

### TASK-R02 — Deterministic validation profile
- 목적: Separate validation intent from environment accident.
- 관련: NFR-004, OPS-005.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: CMP-R01 명시 파일.
- Required Capabilities: implementation, filesystem_write, shell, test.
- Execution Authority: STATE_CHANGING.
- Evidence: EV-R04, EV-R05, EV-R06.
- 완료 조건: deterministic validation PASS.

### 4.1 CMP-R01 — Validation Profile Fixture

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| NFR-004 | Validation is deterministic. | same profile gives same result | MUST |
| OPS-005 | Validation evidence is durable. | evidence recorded | MUST |

### GATE-R02 — Foundation
Required Tasks: TASK-R02
"""
        digest = hashlib.sha256(contract.encode()).hexdigest()
        projected = resolve_task_project_requirement_contract(
            contract, project_id="task-project", canonical_plan_sha256=digest,
            gate_id="GATE-R02", task_id="TASK-R02",
            owned_files=["runtime/orchestrator/validation_toolchain.py"],
        )
        for item in projected["requirements"].values():
            self.assertEqual(item["validation_ids"], ["EV-R04", "EV-R05", "EV-R06"])
            self.assertEqual(item["owned_files"], ["runtime/orchestrator/validation_toolchain.py"])


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


class TaskContractRecoveryAmendmentCompatibilityTests(unittest.TestCase):
    RECOVERY_AMENDMENT_CONTRACT = """# Contract

### TASK-R01 — Entry/Drift 재검증

- 목적: 승인 계획과 worktree 적용 대상을 고정한다.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: 없음(읽기 전용).
- Required Capabilities: reasoning, read_only, evidence_analysis, version_control.
- Execution Authority: READ_ONLY.
- 완료 조건: 승인 의미에 영향을 주는 미해결 drift 0; 아니면 NO_GO.

### TASK-R02 — D1 결정적 검증 프로필

- 목적: 환경 우연과 검증 의도를 분리한다.
- 의존성: TASK-R01, SEQUENTIAL.
- 변경 대상: CMP-R01 명시 파일.
- Required Capabilities: implementation, filesystem_write, shell, test.
- Execution Authority: STATE_CHANGING(개발 worktree 내부만).
- 완료 조건: resolver 분기 테스트 각각 PASS.

| Evidence | 생성자 | 검증자 | 주요 binding | Acceptance / Gate |
|---|---|---|---|---|
| EV-R01~03 | TASK-R01 owner | Design/Entry reviewer | plan/design/root/HEAD/runtime/run digest | drift 0 / R01 |
| EV-R04~06 | TASK-R02 owner | Validation reviewer | candidate HEAD, env manifest, profile, collection | deterministic profile / R02 |

### GATE-R01 — 설계/소스 진입

- GO: 승인 identity 일치, drift 해결, worktree 변경 소유권 명확.
- NO_GO: 승인 문서·root·branch/HEAD 적용 대상 불명확.

### GATE-R02 — D1/D2 기반 복구

- GO: RT-01~05 PASS.
- NO_GO: invalid 대상 실행 가능.
"""

    def test_r_prefixed_recovery_tasks_and_gates_are_contract_shape(self) -> None:
        analysis = analyze_task_stage_gate_contract(self.RECOVERY_AMENDMENT_CONTRACT, "GATE-R01")
        self.assertIsNotNone(analysis)
        self.assertNotIn("requested Stage Gate is absent: GATE-R01", analysis["blockers"])
        self.assertEqual(analysis["requested_gate_tasks"], ["TASK-R01"])

    def test_read_only_recovery_entry_gate_dry_run_does_not_need_mutation_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task-project"; root.mkdir()
            plan = root / "docs" / "DEVELOPMENT_PLAN.txt"; plan.parent.mkdir(parents=True)
            plan.write_text(self.RECOVERY_AMENDMENT_CONTRACT, encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            mapping = SimpleNamespace(
                project_id="task-project",
                canonical_source=plan,
                canonical_sha256=plan_sha,
                task_lv_projection_path=None,
            )
            with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping", return_value=mapping):
                entry = compatibility_dry_run(root, "GATE-R01")
                mutation_gate = compatibility_dry_run(root, "GATE-R02")
        self.assertEqual(entry["status"], "COMPATIBLE")
        self.assertEqual(entry["lv_order"], ["TASK-R01"])
        self.assertEqual(mutation_gate["status"], "BLOCKED")
        self.assertIn("no approved TASK-to-LV authority projection", mutation_gate["reason"])

    def test_recovery_mutation_gate_resolves_cmp_authority_projection(self) -> None:
        contract = self.RECOVERY_AMENDMENT_CONTRACT.replace(
            "### GATE-R01 — 설계/소스 진입",
            """### TASK-R03 — D2 Canonical Registry 복구

- 목적: 기존 binding을 결정적으로 검증한다.
- 의존성: TASK-R01. TASK-R02와 파일 비중복 확인 시 PARALLEL_SAFE.
- 변경 대상: CMP-R02 명시 파일.
- Required Capabilities: implementation, filesystem_write, shell, test, evidence_analysis.
- Execution Authority: STATE_CHANGING(개발 worktree 내부만).
- Evidence: EV-R07, EV-R08.
- 완료 조건: 대상 검증과 전체 감사가 분리되어 PASS.

### 4.1 CMP-R01 — Validation Profile Fixture (D1)

### 4.2 CMP-R02 — Canonical Plan Binding & Registry Isolation (D2)

### GATE-R01 — 설계/소스 진입""",
        ).replace(
            "- 완료 조건: resolver 분기 테스트 각각 PASS.",
            "- Evidence: EV-R04, EV-R05, EV-R06.\n- 완료 조건: resolver 분기 테스트 각각 PASS.",
        ).replace(
            "### GATE-R02 — D1/D2 기반 복구\n\n- GO:",
            "### GATE-R02 — D1/D2 기반 복구\n\nRequired Tasks: TASK-R02, TASK-R03\n\n- GO:",
        )
        plan_sha = hashlib.sha256(contract.encode()).hexdigest()
        value = {
            "schema_version": "orchestration.task-lv-authority-projection.v1",
            "project_id": "task-project",
            "canonical_plan_sha256": plan_sha,
            "contract_shape": "TASK_STAGE_GATE",
            "projection_policy": projection(plan_sha)["projection_policy"],
            "change_targets": {
                "CMP-R01": {
                    "source_expression": "CMP-R01",
                    "owned_files": [
                        "runtime/orchestrator/validation_toolchain.py",
                        "tests/test_validation_toolchain.py",
                    ],
                },
                "CMP-R02": {
                    "source_expression": "CMP-R02",
                    "owned_files": [
                        "runtime/orchestrator/project_onboarding.py",
                        "runtime/orchestrator/read_only_inspector.py",
                        "tests/test_project_onboarding_remote.py",
                    ],
                },
            },
        }
        resolved = resolve_task_lv_projection(
            contract, value, project_id="task-project",
            canonical_plan_sha256=plan_sha, gate_id="GATE-R02",
        )
        self.assertEqual([item["lv_id"] for item in resolved], ["TASK-R02", "TASK-R03"])
        self.assertEqual(resolved[0]["execution"], "SEQUENTIAL")
        self.assertEqual(resolved[1]["execution"], "PARALLEL_SAFE")
        self.assertEqual(resolved[0]["tests"], ["EV-R04", "EV-R05", "EV-R06"])
        self.assertEqual(resolved[1]["tests"], ["EV-R07", "EV-R08"])
        self.assertIn("runtime/orchestrator/validation_toolchain.py", resolved[0]["owned_files"])
        self.assertIn("runtime/orchestrator/project_onboarding.py", resolved[1]["owned_files"])

    def test_bound_projection_preserves_read_only_recovery_entry_gate(self) -> None:
        contract = """# Contract

### TASK-R01 — Entry
- 목적: Verify entry.
- 의존성: 없음, SEQUENTIAL.
- 변경 대상: 없음(읽기 전용).
- Required Capabilities: reasoning, read_only, evidence_analysis, version_control.
- Execution Authority: READ_ONLY 검증(격리 환경); 실제 운영 effect 금지.
- 완료 조건: drift 0.

### TASK-R02 — Mutate
- 목적: Change safely.
- 의존성: TASK-R01, SEQUENTIAL.
- 변경 대상: CMP-R01 명시 파일.
- Required Capabilities: implementation, filesystem_write, test.
- Execution Authority: STATE_CHANGING.
- Evidence: EV-R04.
- 완료 조건: focused PASS.

### 4.1 CMP-R01 — Scope

### GATE-R01 — entry
Required Tasks: TASK-R01

### GATE-R02 — mutate
Required Tasks: TASK-R02
"""
        plan_sha = hashlib.sha256(contract.encode()).hexdigest()
        value = {
            "schema_version": "orchestration.task-lv-authority-projection.v1",
            "project_id": "task-project",
            "canonical_plan_sha256": plan_sha,
            "contract_shape": "TASK_STAGE_GATE",
            "projection_policy": projection(plan_sha)["projection_policy"],
            "change_targets": {
                "CMP-R01": {"source_expression": "CMP-R01", "owned_files": ["runtime/example.py"]},
            },
        }
        resolved = resolve_task_lv_projection(
            contract, value, project_id="task-project",
            canonical_plan_sha256=plan_sha, gate_id="GATE-R01",
        )
        self.assertEqual([item["lv_id"] for item in resolved], ["TASK-R01"])
        self.assertEqual(resolved[0]["execution"], "READ_ONLY")
        self.assertEqual(resolved[0]["owned_files"], [])
        self.assertEqual(
            resolved[0]["required_capabilities"],
            ["reasoning", "read_only", "evidence_analysis", "version_control"],
        )

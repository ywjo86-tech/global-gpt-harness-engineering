import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.execution_lifecycle_v2 import (
    ExecutionLifecycleV2Error,
    adapt_legacy_task_lv_authority,
    build_v2_operator_plan_job,
    resolve_lifecycle_binding,
    validate_execution_authority_bundle,
)
from runtime.orchestrator.operator_plan_execution import build_operator_plan_job


RUNTIME_RELEASE_DIGEST = "a" * 64
LEGACY_TASK_CONTRACT = '''# Contract

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

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | `app/` | CREATE | TASK-001 | PLANNED_NEW |
| CT-002 | `app/profile/` | CREATE | TASK-002 | PLANNED_NEW |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |
| TASK-002 | SEQUENTIAL | TASK-001 | Upstream |

## GATE-001 — first
Required Tasks: TASK-001, TASK-002
'''


def legacy_projection(plan_sha: str) -> dict:
    return {
        "schema_version": "orchestration.task-lv-authority-projection.v1",
        "project_id": "FAMILY_AI_ENGLISH_COACH",
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
            "CT-002": {"source_expression": "app/profile/", "owned_files": ["app/profile/"]},
        },
    }


class HarnessLifecycleV2CompatTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[Path, Path]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        spec = root / "spec.md"
        plan = root / "plan.md"
        spec.write_text("# Approved spec\n", encoding="utf-8")
        plan.write_text("# Approved plan\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "spec.md", "plan.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
        return spec, plan

    def build_legacy_job(self, root: Path) -> dict:
        spec, plan = self.make_repo(root)
        return build_operator_plan_job(
            project_root=root,
            harness_root=root,
            runtime_code_root=root,
            project_id="compat-proj",
            run_id="compat-run",
            task_ids=("TASK-001", "TASK-002"),
            approved_plan_path=plan,
            approved_spec_path=spec,
            approval_ref="USER-APPROVED-COMPAT",
        )

    def test_missing_lifecycle_binding_resolves_to_legacy_without_rewriting_job(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            job = self.build_legacy_job(Path(d))
            self.assertNotIn("lifecycle_binding", job)
            self.assertNotIn("execution_authority_bundle", job)
            resolved = resolve_lifecycle_binding(job)
            self.assertEqual(resolved["schema_version"], "orchestration.lifecycle-binding.v1")
            self.assertEqual(resolved["lifecycle_mode"], "LEGACY")
            self.assertFalse(resolved["bound_at_activation"])
            self.assertFalse(resolved["migration_allowed"])

    def test_v2_job_materializes_one_immutable_authority_bundle_from_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            spec, plan = self.make_repo(root)
            job = build_v2_operator_plan_job(
                project_root=root,
                harness_root=root,
                runtime_code_root=root,
                project_id="compat-proj",
                run_id="compat-v2-run",
                task_ids=("TASK-001", "TASK-002"),
                approved_plan_path=plan,
                approved_spec_path=spec,
                approval_ref="USER-APPROVED-COMPAT",
                runtime_release_digest=RUNTIME_RELEASE_DIGEST,
            )

            binding = job["lifecycle_binding"]
            self.assertEqual(binding, {
                "schema_version": "orchestration.lifecycle-binding.v1",
                "lifecycle_mode": "V2",
                "bound_at_activation": True,
                "migration_allowed": False,
                "runtime_release_digest": RUNTIME_RELEASE_DIGEST,
            })

            bundle = job["execution_authority_bundle"]
            self.assertEqual(bundle["schema_version"], "orchestration.execution-authority-bundle.v1")
            self.assertEqual(bundle["project_id"], job["project_id"])
            self.assertEqual(bundle["run_id"], job["run_id"])
            self.assertEqual(bundle["approved_plan_sha256"], job["approved_plan_sha256"])
            self.assertEqual(bundle["approved_spec_sha256"], job["approved_spec_sha256"])
            self.assertEqual(bundle["approval_ref"], job["approval_ref"])
            self.assertEqual(bundle["expected_branch"], job["expected_branch"])
            self.assertEqual(bundle["activation_source_head"], job["gates"][0]["head"])
            self.assertEqual(bundle["runtime_release_digest"], RUNTIME_RELEASE_DIGEST)
            self.assertEqual(bundle["lifecycle_mode"], "V2")
            self.assertEqual([item["gate_id"] for item in bundle["gate_authorities"]], ["TASK-001", "TASK-002"])
            self.assertTrue(all(item["authority_kind"] == "FULL_PLAN_GATE" for item in bundle["gate_authorities"]))
            self.assertRegex(bundle["bundle_sha256"], r"^[0-9a-f]{64}$")
            validate_execution_authority_bundle(job)

            forbidden = {"final_assignee", "provider_ref", "model_ref", "completion_authority", "effect_authority"}
            self.assertTrue(forbidden.isdisjoint(bundle))
            for authority in bundle["gate_authorities"]:
                self.assertTrue(forbidden.isdisjoint(authority))

    def test_family_style_task_lv_projection_is_adapted_read_only(self) -> None:
        plan_sha = hashlib.sha256(LEGACY_TASK_CONTRACT.encode("utf-8")).hexdigest()
        projection = legacy_projection(plan_sha)
        projection_text = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        projection_sha = hashlib.sha256(projection_text.encode("utf-8")).hexdigest()
        before = projection_text

        authority = adapt_legacy_task_lv_authority(
            canonical_plan_text=LEGACY_TASK_CONTRACT,
            canonical_plan_sha256=plan_sha,
            projection_text=projection_text,
            projection_sha256=projection_sha,
            project_id="FAMILY_AI_ENGLISH_COACH",
            gate_id="GATE-001",
            authority_ref="docs/harness/task-lv-authority-projection.json",
        )

        self.assertEqual(projection_text, before)
        self.assertEqual(authority, {
            "gate_id": "GATE-001",
            "authority_kind": "TASK_LV_PROJECTION",
            "authority_ref": "docs/harness/task-lv-authority-projection.json",
            "authority_sha256": projection_sha,
        })
        forbidden = {"final_assignee", "provider_ref", "model_ref", "completion_authority", "effect_authority"}
        self.assertTrue(forbidden.isdisjoint(authority))

    def test_legacy_adapter_fails_closed_on_projection_digest_or_gate_mismatch(self) -> None:
        plan_sha = hashlib.sha256(LEGACY_TASK_CONTRACT.encode("utf-8")).hexdigest()
        projection_text = json.dumps(legacy_projection(plan_sha), sort_keys=True, separators=(",", ":"))
        projection_sha = hashlib.sha256(projection_text.encode("utf-8")).hexdigest()

        with self.assertRaisesRegex(ExecutionLifecycleV2Error, "projection digest mismatch"):
            adapt_legacy_task_lv_authority(
                canonical_plan_text=LEGACY_TASK_CONTRACT,
                canonical_plan_sha256=plan_sha,
                projection_text=projection_text,
                projection_sha256="0" * 64,
                project_id="FAMILY_AI_ENGLISH_COACH",
                gate_id="GATE-001",
                authority_ref="docs/harness/task-lv-authority-projection.json",
            )

        with self.assertRaises(ExecutionLifecycleV2Error):
            adapt_legacy_task_lv_authority(
                canonical_plan_text=LEGACY_TASK_CONTRACT,
                canonical_plan_sha256=plan_sha,
                projection_text=projection_text,
                projection_sha256=projection_sha,
                project_id="FAMILY_AI_ENGLISH_COACH",
                gate_id="GATE-999",
                authority_ref="docs/harness/task-lv-authority-projection.json",
            )


if __name__ == "__main__":
    unittest.main()

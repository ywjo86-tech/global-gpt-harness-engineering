from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    CanonicalContractBridgeError,
    build_active_contract_and_run_binding,
)
from runtime.orchestrator.completion_authority import (
    materialize_task_4a_08_completion_authority,
)
from runtime.orchestrator.completion_contract import TaskEffectPolicy
from runtime.orchestrator.execution_contract import ContractStatus
from runtime.orchestrator.migration_authority import (
    R4_SEMANTIC_SHA256,
    load_migration_authority,
)


ROOT = Path(__file__).resolve().parents[1]

SOURCE = """\
def test_product_id_key_is_stable_and_does_not_include_price():
    assert True

def test_fallback_key_canonicalizes_merchant_title_and_url():
    assert True

def test_deduplication_is_order_independent_and_preserves_query_lineage():
    assert True
"""


class CanonicalContractBridgeTests(unittest.TestCase):
    def _completion_authority(self):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        package = base / "package"
        (project / "tests").mkdir(parents=True)
        package.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        authority = materialize_task_4a_08_completion_authority(project, package)
        self.addCleanup(temp.cleanup)
        return authority

    def _task(self):
        return ApprovedTaskContractInputs(
            requirement_refs=("REQ-TASK-4A-08",),
            plan_task_ref="TASK-4A-08",
            purpose="deduplicator",
            task_effect_policy=TaskEffectPolicy.MUTATING,
            validation_criteria=(
                "키 안정성·중복 제거 테스트 통과",
                "중복키 규칙 → 키·중복 제거 / 안정성 테스트",
            ),
            quality_criteria_contract_ref="quality://migration/TASK-4A-08",
            change_targets=(
                "app/services/deduplicator.py",
                "tests/test_deduplicator.py",
            ),
            owned_scope=(
                "app/services/deduplicator.py",
                "tests/test_deduplicator.py",
            ),
            allowed_worker_terminal_states=("BLOCKED", "CHANGED", "SKIPPED_SATISFIED"),
            allowed_capabilities=(
                "PROJECT_OWNED_FILE_LIST",
                "PROJECT_OWNED_FILE_READ",
                "PROJECT_OWNED_FILE_WRITE",
            ),
            permission_requirements=("DEC-007",),
            security_requirements=("BROKER_ONLY_EFFECT_PATH",),
            evidence_requirements=(
                "FROZEN_COMPLETION_AUTHORITY",
                "BROKER_EFFECT_RECEIPT",
            ),
            remediation_policy_ref="DEC-008:HOLD",
        )

    def test_builds_active_contract_with_run_specific_plan_and_requirement_digests(self):
        authority = load_migration_authority(ROOT)
        completion = self._completion_authority()
        plan = "1" * 64
        requirement = "2" * 64

        result = build_active_contract_and_run_binding(
            authority=authority,
            completion_authority=completion,
            task=self._task(),
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-proof",
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            canonical_plan_sha256=plan,
            requirement_version="RUN-REQUIREMENTS",
            requirements_sha256=requirement,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            contract_id="CEC-TASK-4A-08",
            contract_version="1",
        )

        self.assertIs(result.active_contract.status, ContractStatus.ACTIVE)
        self.assertEqual(result.active_contract.source_digests["plan"], plan)
        self.assertEqual(result.active_contract.source_digests["requirement"], requirement)
        self.assertEqual(result.active_contract.source_digests["semantic"], R4_SEMANTIC_SHA256)
        self.assertEqual(result.run_binding.plan_digest, plan)
        self.assertEqual(result.run_binding.requirement_digest, requirement)
        self.assertEqual(result.run_binding.semantic_digest, R4_SEMANTIC_SHA256)
        self.assertEqual(
            result.active_contract.completion_criteria_ids,
            ("CC-TASK-4A-08-001", "CC-TASK-4A-08-002"),
        )

    def test_architecture_plan_digest_is_not_used_as_run_plan_digest(self):
        authority = load_migration_authority(ROOT)
        completion = self._completion_authority()
        plan = "3" * 64
        requirement = "4" * 64
        result = build_active_contract_and_run_binding(
            authority=authority,
            completion_authority=completion,
            task=self._task(),
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-proof",
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            canonical_plan_sha256=plan,
            requirement_version="RUN-REQUIREMENTS",
            requirements_sha256=requirement,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            contract_id="CEC-TASK-4A-08",
            contract_version="1",
        )
        self.assertNotEqual(result.active_contract.source_digests["plan"], authority.plan_digest)
        self.assertNotEqual(result.active_contract.source_digests["requirement"], authority.requirement_digest)

    def test_missing_run_requirement_digest_fails_closed(self):
        authority = load_migration_authority(ROOT)
        completion = self._completion_authority()
        with self.assertRaises(CanonicalContractBridgeError) as caught:
            build_active_contract_and_run_binding(
                authority=authority,
                completion_authority=completion,
                task=self._task(),
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-proof",
                worker_task_id="TASK-4A-08",
                plan_version="DP-5.0-CANDIDATE",
                canonical_plan_sha256="1" * 64,
                requirement_version="RUN-REQUIREMENTS",
                requirements_sha256="",
                semantic_version="SC-1.0-FROZEN-LINEAGE",
                contract_id="CEC-TASK-4A-08",
                contract_version="1",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "RUN_SOURCE_BINDING_INVALID")

    def test_worker_task_mismatch_fails_closed(self):
        authority = load_migration_authority(ROOT)
        completion = self._completion_authority()
        with self.assertRaises(CanonicalContractBridgeError) as caught:
            build_active_contract_and_run_binding(
                authority=authority,
                completion_authority=completion,
                task=self._task(),
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-proof",
                worker_task_id="TASK-OTHER",
                plan_version="DP-5.0-CANDIDATE",
                canonical_plan_sha256="1" * 64,
                requirement_version="RUN-REQUIREMENTS",
                requirements_sha256="2" * 64,
                semantic_version="SC-1.0-FROZEN-LINEAGE",
                contract_id="CEC-TASK-4A-08",
                contract_version="1",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CANONICAL_BRIDGE_WORKER_TASK_DRIFT")


if __name__ == "__main__":
    unittest.main()

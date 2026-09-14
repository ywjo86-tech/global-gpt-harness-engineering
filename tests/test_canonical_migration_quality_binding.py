from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    CanonicalContractBridgeError,
    build_migration_quality_bound_active_contract_and_run_binding,
)
from runtime.orchestrator.canonical_launch_bridge import (
    CanonicalLaunchBridgeError,
    build_canonical_launch,
)
from runtime.orchestrator.codex_readiness import ReadinessProbeSet, collect_codex_auth_readiness
from runtime.orchestrator.completion_authority import materialize_task_4a_08_completion_authority
from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionCriterion,
    CompletionState,
    CriterionResult,
    TaskEffectPolicy,
    criterion_set_digest,
)
from runtime.orchestrator.execution_contract import ActivationProfile
from runtime.orchestrator.migration_authority import load_migration_authority
from runtime.orchestrator.migration_quality_authority import (
    MIGRATION_APPROVED_PLAN,
    MigrationQualityAuthorityError,
    build_approved_migration_quality_contract,
    load_approved_migration_quality_authority,
    validate_approved_migration_quality_contract,
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


def probes():
    return ReadinessProbeSet(
        version_probe=lambda: "0.150.1",
        schema_probe=lambda: (
            {
                "experimental_api": True,
                "dynamic_tool_request": True,
                "dynamic_tool_response": True,
                "empty_environment_supported": True,
                "schema_verified": True,
            },
            "a" * 64,
        ),
        environment_probe=lambda: "b" * 64,
        auth_probe=lambda: "READY",
    )


class CanonicalMigrationQualityBindingTests(unittest.TestCase):
    def _fixture(self):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        package_root = base / "completion-package"
        (project / "tests").mkdir(parents=True)
        package_root.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        completion = materialize_task_4a_08_completion_authority(project, package_root)

        quality_authority = load_approved_migration_quality_authority(ROOT)
        quality_contract = build_approved_migration_quality_contract(
            authority=quality_authority,
            activation_profile=MIGRATION_APPROVED_PLAN,
            contract_id="MQC-TASK-4A-08",
            contract_version="1",
            created_at_utc="2026-09-10T02:00:00Z",
        )
        task = ApprovedTaskContractInputs(
            requirement_refs=("REQ-TASK-4A-08",),
            plan_task_ref="TASK-4A-08",
            purpose="deduplicator",
            task_effect_policy=TaskEffectPolicy.MUTATING,
            validation_criteria=(
                "키 안정성·중복 제거 테스트 통과",
                "중복키 규칙 → 키·중복 제거 / 안정성 테스트",
            ),
            quality_criteria_contract_ref=quality_contract.contract_ref,
            change_targets=("app/services/deduplicator.py", "tests/test_deduplicator.py"),
            owned_scope=("app/services/deduplicator.py", "tests/test_deduplicator.py"),
            allowed_worker_terminal_states=("BLOCKED", "CHANGED", "SKIPPED_SATISFIED"),
            allowed_capabilities=(
                "PROJECT_OWNED_FILE_LIST",
                "PROJECT_OWNED_FILE_READ",
                "PROJECT_OWNED_FILE_WRITE",
            ),
            permission_requirements=("DEC-007",),
            security_requirements=("BROKER_ONLY_EFFECT_PATH",),
            evidence_requirements=("FROZEN_COMPLETION_AUTHORITY", "BROKER_EFFECT_RECEIPT"),
            remediation_policy_ref="DEC-008:HOLD",
        )
        authority = load_migration_authority(ROOT)
        bridge = build_migration_quality_bound_active_contract_and_run_binding(
            migration_quality_contract=quality_contract,
            authority=authority,
            completion_authority=completion,
            task=task,
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-quality-bound",
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            canonical_plan_sha256="1" * 64,
            requirement_version="RUN-REQUIREMENTS",
            requirements_sha256="2" * 64,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            contract_id="CEC-TASK-4A-08",
            contract_version="1",
        )
        criteria = tuple(
            CompletionCriterion(
                criterion_id=item.criterion_id,
                verifier_type=item.verifier_type,
                authoritative_source_ref=item.authoritative_source_ref,
                verifier_config={},
                mandatory=True,
            )
            for item in completion.criteria
        )
        results = tuple(
            CriterionResult(
                criterion_id=item.criterion_id,
                verifier_type=item.verifier_type,
                authoritative_source_ref=item.authoritative_source_ref,
                state=CompletionState.UNSATISFIED,
                evidence_refs=(f"{item.authoritative_source_ref}#fixture",),
                reason_taxonomy="FIXTURE",
                mandatory=True,
            )
            for item in completion.criteria
        )
        assessment = CompletionAssessment(
            criterion_results=results,
            overall_state=CompletionState.UNSATISFIED,
            criterion_set_digest=criterion_set_digest(criteria),
            evidence_refs=tuple(
                ref
                for item in results
                for ref in item.evidence_refs
            ),
        )
        readiness = collect_codex_auth_readiness(
            run_id="run-quality-bound",
            worker_task_id="TASK-4A-08",
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            probes=probes(),
            verified_at_utc="2026-09-10T02:05:00Z",
        )
        self.addCleanup(temp.cleanup)
        return authority, completion, quality_contract, task, bridge, assessment, readiness

    def test_quality_contract_self_validation_binds_policy_criteria_and_lineage(self):
        _, _, quality_contract, _, _, _, _ = self._fixture()
        validate_approved_migration_quality_contract(quality_contract)
        self.assertIn(quality_contract.contract_digest, quality_contract.contract_ref)
        self.assertEqual(len(quality_contract.policy_digest), 64)
        self.assertEqual(len(quality_contract.criterion_set_digest), 64)
        self.assertEqual(len(quality_contract.pre_post_lineage_digest), 64)

    def test_active_contract_exactly_binds_approved_migration_quality_contract_ref(self):
        _, _, quality_contract, _, bridge, _, _ = self._fixture()
        self.assertEqual(bridge.active_contract.quality_criteria_contract_ref, quality_contract.contract_ref)

    def test_task_quality_ref_drift_fails_before_canonical_contract_build(self):
        authority, completion, quality_contract, task, _, _, _ = self._fixture()
        bad_task = replace(task, quality_criteria_contract_ref="quality://migration/TASK-4A-08")
        with self.assertRaises(CanonicalContractBridgeError) as caught:
            build_migration_quality_bound_active_contract_and_run_binding(
                migration_quality_contract=quality_contract,
                authority=authority,
                completion_authority=completion,
                task=bad_task,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-quality-drift",
                worker_task_id="TASK-4A-08",
                plan_version="DP-5.0-CANDIDATE",
                canonical_plan_sha256="1" * 64,
                requirement_version="RUN-REQUIREMENTS",
                requirements_sha256="2" * 64,
                semantic_version="SC-1.0-FROZEN-LINEAGE",
                contract_id="CEC-TASK-4A-08",
                contract_version="1",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CANONICAL_BRIDGE_MIGRATION_QUALITY_REF_DRIFT")

    def test_forged_quality_contract_digest_fails_closed(self):
        _, _, quality_contract, _, _, _, _ = self._fixture()
        forged = replace(quality_contract, contract_digest="0" * 64)
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            validate_approved_migration_quality_contract(forged)
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_CONTRACT_DIGEST_DRIFT")

    def test_execution_package_seals_exact_migration_quality_ref(self):
        authority, _, quality_contract, _, bridge, assessment, readiness = self._fixture()
        result = build_canonical_launch(
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            previous_package_digest="",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=bridge.run_binding,
            active_contract=bridge.active_contract,
            pre_execution_assessment_ref="completion://TASK-4A-08/pre#fixture",
            pre_execution_assessment=assessment,
            runtime_selection={"backend": "HOST_GATEWAY"},
            exact_tool_authorization_projection=(
                "PROJECT_OWNED_FILE_LIST",
                "PROJECT_OWNED_FILE_READ",
                "PROJECT_OWNED_FILE_WRITE",
            ),
            security_policy_refs=("security://broker-only",),
            quality_policy_refs=(quality_contract.contract_ref,),
            codex_auth_readiness=readiness,
            approval_context=authority.approval_context(),
            migration_authority_ref="migration-authority://R4.1/manifest",
            migration_quality_contract=quality_contract,
            readiness_recheck_probes=probes(),
            readiness_recheck_verified_at_utc="2026-09-10T02:05:05Z",
        )
        self.assertEqual(result.package.quality_criteria_contract_ref, quality_contract.contract_ref)
        self.assertIn(quality_contract.contract_ref, result.package.quality_policy_refs)
        self.assertEqual(result.package.contract_digest, bridge.active_contract.contract_digest)

    def test_migration_quality_active_contract_cannot_launch_without_contract_object(self):
        authority, _, quality_contract, _, bridge, assessment, readiness = self._fixture()
        with self.assertRaises(CanonicalLaunchBridgeError) as caught:
            build_canonical_launch(
                package_id="PKG-TASK-4A-08",
                package_revision=1,
                previous_package_digest="",
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                run_binding=bridge.run_binding,
                active_contract=bridge.active_contract,
                pre_execution_assessment_ref="completion://TASK-4A-08/pre#fixture",
                pre_execution_assessment=assessment,
                runtime_selection={"backend": "HOST_GATEWAY"},
                exact_tool_authorization_projection=(
                    "PROJECT_OWNED_FILE_LIST",
                    "PROJECT_OWNED_FILE_READ",
                    "PROJECT_OWNED_FILE_WRITE",
                ),
                security_policy_refs=("security://broker-only",),
                quality_policy_refs=(quality_contract.contract_ref,),
                codex_auth_readiness=readiness,
                approval_context=authority.approval_context(),
                migration_authority_ref="migration-authority://R4.1/manifest",
                readiness_recheck_probes=probes(),
                readiness_recheck_verified_at_utc="2026-09-10T02:05:05Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CANONICAL_LAUNCH_MIGRATION_QUALITY_MISSING")


if __name__ == "__main__":
    unittest.main()

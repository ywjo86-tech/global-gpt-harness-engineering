from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.canonical_contract_bridge import ApprovedTaskContractInputs
from runtime.orchestrator.codex_readiness import ReadinessProbeSet, collect_codex_auth_readiness
from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionState,
    CriterionResult,
    TaskEffectPolicy,
    criterion_set_digest,
)
from runtime.orchestrator.completion_contract_bridge import build_completion_criteria
from runtime.orchestrator.production_canonical_authority import (
    ProductionCanonicalAuthorityError,
    build_production_canonical_launch_authority,
    materialize_production_canonical_contract_authority,
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


class ProductionCanonicalAuthorityTests(unittest.TestCase):
    def _task(self, quality_ref: str = "") -> ApprovedTaskContractInputs:
        return ApprovedTaskContractInputs(
            requirement_refs=("REQ-TASK-4A-08",),
            plan_task_ref="TASK-4A-08",
            purpose="deduplicator",
            task_effect_policy=TaskEffectPolicy.MUTATING,
            validation_criteria=(
                "키 안정성·중복 제거 테스트 통과",
                "중복키 규칙 → 키·중복 제거 / 안정성 테스트",
            ),
            quality_criteria_contract_ref=quality_ref,
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

    def _authority(self, quality_ref: str = ""):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        completion_root = base / "canonical-authority"
        (project / "tests").mkdir(parents=True)
        completion_root.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        result = materialize_production_canonical_contract_authority(
            project_root=project,
            harness_root=ROOT,
            completion_authority_root=completion_root,
            task=self._task(quality_ref),
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-production-canonical",
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            canonical_plan_sha256="1" * 64,
            requirement_version="RUN-REQUIREMENTS",
            requirements_sha256="2" * 64,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            canonical_contract_id="CEC-TASK-4A-08",
            canonical_contract_version="1",
            quality_contract_id="MQC-TASK-4A-08",
            quality_contract_version="1",
            quality_contract_created_at_utc="2026-09-10T03:00:00Z",
            verify_git_provenance=False,
        )
        self.addCleanup(temp.cleanup)
        return result

    def test_materializes_exact_quality_bound_active_contract(self):
        result = self._authority()
        quality = result.migration_quality_contract
        active = result.contract_bridge.active_contract
        run = result.contract_bridge.run_binding
        self.assertEqual(result.approved_task.quality_criteria_contract_ref, quality.contract_ref)
        self.assertEqual(active.quality_criteria_contract_ref, quality.contract_ref)
        self.assertEqual(active.source_digests["plan"], run.plan_digest)
        self.assertEqual(active.source_digests["requirement"], run.requirement_digest)
        self.assertEqual(active.source_digests["semantic"], run.semantic_digest)

    def test_conflicting_existing_quality_ref_fails_closed(self):
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            self._authority("quality://legacy-or-forged")
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_TASK_QUALITY_REF_DRIFT",
        )

    def test_builds_package_preflight_launch_and_gateway_binding_with_injected_readiness(self):
        authority = self._authority()
        criteria = build_completion_criteria(authority.completion_authority)
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
            for item in criteria
        )
        assessment = CompletionAssessment(
            criterion_results=results,
            overall_state=CompletionState.UNSATISFIED,
            criterion_set_digest=criterion_set_digest(criteria),
            evidence_refs=tuple(ref for item in results for ref in item.evidence_refs),
        )
        readiness = collect_codex_auth_readiness(
            run_id=authority.contract_bridge.run_binding.run_id,
            worker_task_id="TASK-4A-08",
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            probes=probes(),
            verified_at_utc="2026-09-10T03:05:00Z",
        )
        launch = build_production_canonical_launch_authority(
            authority=authority,
            pre_execution_assessment_ref="completion://TASK-4A-08/pre#fixture",
            pre_execution_assessment=assessment,
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            previous_package_digest="",
            runtime_selection={"backend": "HOST_GATEWAY"},
            exact_tool_authorization_projection=(
                "PROJECT_OWNED_FILE_LIST",
                "PROJECT_OWNED_FILE_READ",
                "PROJECT_OWNED_FILE_WRITE",
            ),
            security_policy_refs=("security://broker-only",),
            codex_auth_readiness=readiness,
            migration_authority_ref="migration-authority://R4.1/manifest",
            readiness_recheck_probes=probes(),
            readiness_recheck_verified_at_utc="2026-09-10T03:05:05Z",
        )
        self.assertEqual(
            launch.gateway_authority_binding["worker_task_id"],
            "TASK-4A-08",
        )
        self.assertEqual(
            launch.gateway_authority_binding["package_digest"],
            launch.package.package_digest,
        )
        self.assertEqual(
            launch.package.quality_criteria_contract_ref,
            authority.migration_quality_contract.contract_ref,
        )
        self.assertTrue(launch.gateway_authority_binding_digest)

    def test_completion_task_mismatch_is_blocked_before_launch(self):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        completion_root = base / "canonical-authority"
        (project / "tests").mkdir(parents=True)
        completion_root.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            materialize_production_canonical_contract_authority(
                project_root=project,
                harness_root=ROOT,
                completion_authority_root=completion_root,
                task=self._task(),
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-wrong-task",
                worker_task_id="TASK-OTHER",
                plan_version="DP-5.0-CANDIDATE",
                canonical_plan_sha256="1" * 64,
                requirement_version="RUN-REQUIREMENTS",
                requirements_sha256="2" * 64,
                semantic_version="SC-1.0-FROZEN-LINEAGE",
                canonical_contract_id="CEC-TASK-4A-08",
                canonical_contract_version="1",
                quality_contract_id="MQC-TASK-4A-08",
                quality_contract_version="1",
                quality_contract_created_at_utc="2026-09-10T03:00:00Z",
                verify_git_provenance=False,
            )
        temp.cleanup()
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_COMPLETION_TASK_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    build_active_contract_and_run_binding,
)
from runtime.orchestrator.canonical_launch_bridge import (
    build_canonical_launch,
)
from runtime.orchestrator.codex_readiness import (
    ReadinessProbeSet,
    collect_codex_auth_readiness,
)
from runtime.orchestrator.completion_authority import (
    materialize_task_4a_08_completion_authority,
)
from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionState,
    CriterionResult,
    TaskEffectPolicy,
)
from runtime.orchestrator.execution_contract import (
    ActivationProfile,
    PreflightBlocked,
)
from runtime.orchestrator.migration_authority import load_migration_authority
from runtime.orchestrator.worker_authority import WorkerAuthorityError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "a" * 64
ENV = "b" * 64

SOURCE = """\
def test_product_id_key_is_stable_and_does_not_include_price():
    assert True

def test_fallback_key_canonicalizes_merchant_title_and_url():
    assert True

def test_deduplication_is_order_independent_and_preserves_query_lineage():
    assert True
"""


def probes(*, schema=SCHEMA, env=ENV, auth="READY"):
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
            schema,
        ),
        environment_probe=lambda: env,
        auth_probe=lambda: auth,
    )


class CanonicalLaunchBridgeTests(unittest.TestCase):
    def _fixture(self, *, completion_state=CompletionState.UNSATISFIED):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        package_root = base / "package"
        (project / "tests").mkdir(parents=True)
        package_root.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        completion = materialize_task_4a_08_completion_authority(project, package_root)

        task = ApprovedTaskContractInputs(
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
            evidence_requirements=("FROZEN_COMPLETION_AUTHORITY", "BROKER_EFFECT_RECEIPT"),
            remediation_policy_ref="DEC-008:HOLD",
        )

        authority = load_migration_authority(ROOT)
        contract_bridge = build_active_contract_and_run_binding(
            authority=authority,
            completion_authority=completion,
            task=task,
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-proof",
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            canonical_plan_sha256="1" * 64,
            requirement_version="RUN-REQUIREMENTS",
            requirements_sha256="2" * 64,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            contract_id="CEC-TASK-4A-08",
            contract_version="1",
        )

        results = tuple(
            CriterionResult(
                criterion_id=item.criterion_id,
                verifier_type=item.verifier_type,
                authoritative_source_ref=item.authoritative_source_ref,
                state=completion_state,
                evidence_refs=(f"{item.authoritative_source_ref}#fixture",),
                reason_taxonomy="FIXTURE",
                mandatory=True,
            )
            for item in completion.criteria
        )
        assessment = CompletionAssessment(
            criterion_results=results,
            overall_state=completion_state,
            criterion_set_digest=__import__(
                "runtime.orchestrator.completion_contract",
                fromlist=["criterion_set_digest"],
            ).criterion_set_digest(
                tuple(
                    __import__(
                        "runtime.orchestrator.completion_contract",
                        fromlist=["CompletionCriterion"],
                    ).CompletionCriterion(
                        criterion_id=item.criterion_id,
                        verifier_type=item.verifier_type,
                        authoritative_source_ref=item.authoritative_source_ref,
                        verifier_config={},
                        mandatory=True,
                    )
                    for item in completion.criteria
                )
            ),
            evidence_refs=tuple(
                ref
                for result in results
                for ref in result.evidence_refs
            ),
        )

        readiness = collect_codex_auth_readiness(
            run_id="run-proof",
            worker_task_id="TASK-4A-08",
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            probes=probes(),
            verified_at_utc="2026-09-09T15:00:00Z",
        )
        self.addCleanup(temp.cleanup)
        return authority, contract_bridge, assessment, readiness

    def _build(self, *, completion_state=CompletionState.UNSATISFIED, recheck=None):
        authority, contract_bridge, assessment, readiness = self._fixture(
            completion_state=completion_state
        )
        return build_canonical_launch(
            package_id="PKG-TASK-4A-08",
            package_revision=1,
            previous_package_digest="",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=contract_bridge.run_binding,
            active_contract=contract_bridge.active_contract,
            pre_execution_assessment_ref="completion://TASK-4A-08/pre#fixture",
            pre_execution_assessment=assessment,
            runtime_selection={"backend": "HOST_GATEWAY"},
            exact_tool_authorization_projection=(
                "PROJECT_OWNED_FILE_LIST",
                "PROJECT_OWNED_FILE_READ",
                "PROJECT_OWNED_FILE_WRITE",
            ),
            security_policy_refs=("security://broker-only",),
            quality_policy_refs=(contract_bridge.active_contract.quality_criteria_contract_ref,),
            codex_auth_readiness=readiness,
            approval_context=authority.approval_context(),
            migration_authority_ref="migration-authority://R4.1/manifest",
            readiness_recheck_probes=recheck or probes(),
            readiness_recheck_verified_at_utc="2026-09-09T15:00:05Z",
        )

    def test_builds_package_preflight_recheck_and_exact_launch_authorization(self):
        result = self._build()
        self.assertTrue(result.preflight.ready)
        self.assertEqual(
            result.launch_authorization.package_digest,
            result.package.package_digest,
        )
        self.assertEqual(
            result.launch_authorization.preflight_evidence_digest,
            result.preflight.evidence_digest,
        )
        self.assertEqual(
            result.gateway_authority_binding["launch_authorization_digest"],
            result.launch_authorization.authorization_digest,
        )
        self.assertEqual(
            result.gateway_authority_binding["codex_auth_readiness_ref"],
            result.package.codex_auth_readiness_ref,
        )
        self.assertNotEqual(
            result.gateway_authority_binding["codex_auth_recheck_evidence_ref"],
            result.gateway_authority_binding["codex_auth_readiness_ref"],
        )
        self.assertEqual(len(result.gateway_authority_binding_digest), 64)

    def test_launch_adjacent_environment_drift_blocks_before_authorization(self):
        with self.assertRaises(Exception) as caught:
            self._build(recheck=probes(env="c" * 64))
        self.assertEqual(
            getattr(caught.exception, "reason_taxonomy", ""),
            "CODEX_READINESS_STALE_OR_DRIFTED",
        )

    def test_blocked_completion_cannot_pass_canonical_preflight(self):
        with self.assertRaises(PreflightBlocked) as caught:
            self._build(completion_state=CompletionState.UNKNOWN)
        self.assertEqual(caught.exception.reason_taxonomy, "BLOCKED_COMPLETION_CONTRACT")

    def test_none_satisfied_produces_launch_authorization_for_skip_path(self):
        result = self._build(completion_state=CompletionState.SATISFIED)
        self.assertEqual(result.package.execution_obligation.value, "NONE_SATISFIED")
        self.assertEqual(
            result.launch_authorization.execution_obligation.value,
            "NONE_SATISFIED",
        )

    def test_gateway_authority_binding_preserves_migration_authority_and_contract_activation(self):
        result = self._build()
        binding = result.gateway_authority_binding
        self.assertEqual(binding["migration_authority_ref"], "migration-authority://R4.1/manifest")
        self.assertEqual(
            binding["contract_activation_digest"],
            result.package.contract_activation_digest,
        )
        self.assertEqual(
            binding["preflight_evidence_digest"],
            result.preflight.evidence_digest,
        )


if __name__ == "__main__":
    unittest.main()

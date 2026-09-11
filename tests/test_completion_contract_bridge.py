from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.orchestrator.canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    build_active_contract_and_run_binding,
)
from runtime.orchestrator.completion_authority import (
    materialize_task_4a_08_completion_authority,
)
from runtime.orchestrator.completion_contract import (
    CompletionState,
    ExecutionObligation,
    TaskEffectPolicy,
)
from runtime.orchestrator.completion_contract_bridge import (
    CompletionContractBridgeError,
    assess_frozen_completion,
    build_completion_criteria,
    evaluate_contract_completion,
)
from runtime.orchestrator.migration_authority import load_migration_authority


ROOT = Path(__file__).resolve().parents[1]

SOURCE = """\
def test_product_id_key_is_stable_and_does_not_include_price():
    assert True

def test_fallback_key_canonicalizes_merchant_title_and_url():
    assert True

def test_deduplication_is_order_independent_and_preserves_query_lineage():
    assert True
"""


class CompletionContractBridgeTests(unittest.TestCase):
    def _fixture(self):
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        project = base / "project"
        package = base / "package"
        (project / "tests").mkdir(parents=True)
        (project / ".venv/bin").mkdir(parents=True)
        (project / ".venv/bin/python").write_text("", encoding="utf-8")
        (project / ".venv/bin/pytest").write_text("", encoding="utf-8")
        package.mkdir()
        (project / "tests/test_deduplicator.py").write_text(SOURCE, encoding="utf-8")
        completion = materialize_task_4a_08_completion_authority(project, package)

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
            evidence_requirements=(
                "FROZEN_COMPLETION_AUTHORITY",
                "BROKER_EFFECT_RECEIPT",
            ),
            remediation_policy_ref="DEC-008:HOLD",
        )
        authority = load_migration_authority(ROOT)
        bridge = build_active_contract_and_run_binding(
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
        self.addCleanup(temp.cleanup)
        return project, completion, bridge.active_contract

    def test_materialized_completion_criteria_are_exactly_the_frozen_authority_set(self):
        _project, completion, _contract = self._fixture()
        criteria = build_completion_criteria(completion)
        self.assertEqual(
            tuple(item.criterion_id for item in criteria),
            ("CC-TASK-4A-08-001", "CC-TASK-4A-08-002"),
        )
        self.assertTrue(all(item.mandatory for item in criteria))

    def test_unsatisfied_pre_completion_derives_mutation_required(self):
        project, completion, contract = self._fixture()
        # Patch only after authority/contract fixture construction so Git
        # provenance verification keeps using the real subprocess.run.
        with mock.patch("runtime.orchestrator.completion_authority.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout=b"failed", stderr=b"")
            result = evaluate_contract_completion(contract, completion, project)
        self.assertIs(result.assessment.overall_state, CompletionState.UNSATISFIED)
        self.assertIs(result.execution_obligation, ExecutionObligation.MUTATION_REQUIRED)
        self.assertEqual(len(result.evidence), 2)

    def test_satisfied_pre_completion_derives_none_satisfied(self):
        project, completion, contract = self._fixture()
        with mock.patch("runtime.orchestrator.completion_authority.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"pass", stderr=b"")
            result = evaluate_contract_completion(contract, completion, project)
        self.assertIs(result.assessment.overall_state, CompletionState.SATISFIED)
        self.assertIs(result.execution_obligation, ExecutionObligation.NONE_SATISFIED)

    def test_verifier_infrastructure_error_derives_blocked(self):
        project, completion, contract = self._fixture()
        with mock.patch("runtime.orchestrator.completion_authority.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=4, stdout=b"", stderr=b"usage")
            result = evaluate_contract_completion(contract, completion, project)
        self.assertIs(result.assessment.overall_state, CompletionState.UNKNOWN)
        self.assertIs(result.execution_obligation, ExecutionObligation.BLOCKED)

    def test_tampered_evidence_digest_becomes_unknown_fail_closed(self):
        _project, completion, _contract = self._fixture()
        from runtime.orchestrator.completion_authority import CriterionVerificationEvidence

        evidence = []
        for item in completion.criteria:
            evidence.append(
                CriterionVerificationEvidence(
                    criterion_id=item.criterion_id,
                    state="SATISFIED",
                    reason_taxonomy="PASS",
                    authoritative_source_ref=item.authoritative_source_ref,
                    snapshot_sha256=completion.snapshot_sha256,
                    node_set_digest=completion.node_set_digest,
                    pytest_exit_code=0,
                    stdout_sha256="1" * 64,
                    stderr_sha256="2" * 64,
                    command_digest="3" * 64,
                    evidence_digest="0" * 64,
                )
            )
        assessment = assess_frozen_completion(completion, evidence=tuple(evidence))
        self.assertIs(assessment.overall_state, CompletionState.UNKNOWN)
        self.assertTrue(
            all(
                item.reason_taxonomy == "AUTHORITATIVE_COMPLETION_EVIDENCE_DIGEST_DRIFT"
                for item in assessment.criterion_results
            )
        )

    def test_contract_criterion_set_drift_fails_closed_before_verifier(self):
        project, completion, contract = self._fixture()
        from dataclasses import replace

        drifted = replace(contract, completion_criteria_ids=("CC-OTHER",))
        with self.assertRaises(CompletionContractBridgeError) as caught:
            evaluate_contract_completion(drifted, completion, project)
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "COMPLETION_BRIDGE_CONTRACT_CRITERIA_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()

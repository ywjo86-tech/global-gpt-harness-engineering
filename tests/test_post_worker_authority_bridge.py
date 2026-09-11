from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from runtime.orchestrator.canonical_contract_bridge import (
    ApprovedTaskContractInputs,
    build_active_contract_and_run_binding,
)
from runtime.orchestrator.canonical_launch_bridge import build_canonical_launch
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
    ExecutionObligation,
    TaskEffectPolicy,
    criterion_set_digest,
)
from runtime.orchestrator.completion_contract_bridge import build_completion_criteria
from runtime.orchestrator.execution_contract import ActivationProfile
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.migration_authority import load_migration_authority
from runtime.orchestrator.post_worker_authority_bridge import (
    PostWorkerAuthorityBridgeError,
    build_mutation_worker_result_envelope,
    evaluate_mutation_post_worker_authority,
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


def seal_payload(value):
    sealed = dict(value)
    sealed["evidence_sha256"] = hashlib.sha256(
        canonical_json_bytes(sealed)
    ).hexdigest()
    return sealed


def effect():
    return {
        "effect_id": "TE-1234",
        "operation": "PROJECT_OWNED_FILE_WRITE",
        "scope_ref": "app/services/deduplicator.py",
        "intent_digest": "1" * 64,
        "receipt_intent_digest": "1" * 64,
        "receipt_digest": "2" * 64,
        "authorized": True,
        "mutation_performed": True,
        "security_passed": True,
        "evidence_refs": (
            "tool-effect://TE-1234/intent#" + "1" * 64,
            "tool-effect://TE-1234/receipt#" + "2" * 64,
        ),
    }


def payload():
    return seal_payload(
        {
            "status": "completed",
            "changed_files": ["app/services/deduplicator.py"],
            "checkpoint_commit": "commit-123",
            "current_tree": "tree-123",
            "review_verdict": "PASS",
            "executor": {"identity": "production-worker-executor"},
            "governed_effect_evidence": [effect()],
            "artifact_sha_chain": {
                "request": "3" * 64,
                "executor_output": "4" * 64,
                "process_evidence": "5" * 64,
            },
        }
    )


def task_inputs():
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
        allowed_worker_terminal_states=(
            "BLOCKED",
            "CHANGED",
            "SKIPPED_SATISFIED",
        ),
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


class PostWorkerAuthorityBridgeTests(unittest.TestCase):
    def test_builds_changed_result_from_durable_production_evidence(self):
        pkg = type(
            "Package",
            (),
            {
                "execution_obligation": ExecutionObligation.MUTATION_REQUIRED,
                "owned_scope_projection": (
                    "app/services/deduplicator.py",
                    "tests/test_deduplicator.py",
                ),
            },
        )()
        launch = type(
            "Launch",
            (),
            {
                "task_ref": "TASK-4A-08",
                "package_ref": "package://PKG-1@1#" + "a" * 64,
                "package_digest": "a" * 64,
                "contract_ref": "contract://CONTRACT-1@1#" + "c" * 64,
                "contract_digest": "c" * 64,
            },
        )()
        result = build_mutation_worker_result_envelope(pkg, launch, payload())
        self.assertEqual(result.task_ref, "TASK-4A-08")
        self.assertEqual(result.terminal_state, "CHANGED")
        self.assertEqual(
            result.output_artifact_refs,
            ("app/services/deduplicator.py",),
        )
        self.assertEqual(len(result.effect_evidence), 1)
        self.assertIn("5" * 64, result.security_evidence_refs)
        self.assertIn("2" * 64, result.security_evidence_refs)

    def test_out_of_scope_changed_file_fails_closed(self):
        pkg = type(
            "Package",
            (),
            {
                "execution_obligation": ExecutionObligation.MUTATION_REQUIRED,
                "owned_scope_projection": (
                    "app/services/deduplicator.py",
                    "tests/test_deduplicator.py",
                ),
            },
        )()
        launch = type(
            "Launch",
            (),
            {
                "task_ref": "TASK-4A-08",
                "package_ref": "package://PKG-1@1#" + "a" * 64,
                "package_digest": "a" * 64,
                "contract_ref": "contract://CONTRACT-1@1#" + "c" * 64,
                "contract_digest": "c" * 64,
            },
        )()
        unsigned = payload()
        unsigned.pop("evidence_sha256")
        unsigned["changed_files"] = ["outside.py"]
        value = seal_payload(unsigned)
        with self.assertRaises(PostWorkerAuthorityBridgeError) as caught:
            build_mutation_worker_result_envelope(pkg, launch, value)
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "POST_WORKER_CHANGED_FILES_OUT_OF_SCOPE",
        )

    def test_malformed_effect_projection_fails_closed(self):
        pkg = type(
            "Package",
            (),
            {
                "execution_obligation": ExecutionObligation.MUTATION_REQUIRED,
                "owned_scope_projection": (
                    "app/services/deduplicator.py",
                    "tests/test_deduplicator.py",
                ),
            },
        )()
        launch = type(
            "Launch",
            (),
            {
                "task_ref": "TASK-4A-08",
                "package_ref": "package://PKG-1@1#" + "a" * 64,
                "package_digest": "a" * 64,
                "contract_ref": "contract://CONTRACT-1@1#" + "c" * 64,
                "contract_digest": "c" * 64,
            },
        )()
        unsigned = payload()
        unsigned.pop("evidence_sha256")
        unsigned["governed_effect_evidence"] = [{"effect_id": "broken"}]
        value = seal_payload(unsigned)
        with self.assertRaises(PostWorkerAuthorityBridgeError) as caught:
            build_mutation_worker_result_envelope(pkg, launch, value)
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "POST_WORKER_EFFECT_EVIDENCE_INVALID",
        )

    def test_worker_payload_digest_tamper_fails_closed(self):
        pkg = type(
            "Package",
            (),
            {
                "execution_obligation": ExecutionObligation.MUTATION_REQUIRED,
                "owned_scope_projection": (
                    "app/services/deduplicator.py",
                    "tests/test_deduplicator.py",
                ),
            },
        )()
        launch = type(
            "Launch",
            (),
            {
                "task_ref": "TASK-4A-08",
                "package_ref": "package://PKG-1@1#" + "a" * 64,
                "package_digest": "a" * 64,
                "contract_ref": "contract://CONTRACT-1@1#" + "c" * 64,
                "contract_digest": "c" * 64,
            },
        )()
        value = payload()
        value["changed_files"] = ["tests/test_deduplicator.py"]
        with self.assertRaises(PostWorkerAuthorityBridgeError) as caught:
            build_mutation_worker_result_envelope(pkg, launch, value)
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "POST_WORKER_EVIDENCE_DIGEST_DRIFT",
        )

    def test_missing_artifact_chain_member_fails_closed(self):
        pkg = type(
            "Package",
            (),
            {
                "execution_obligation": ExecutionObligation.MUTATION_REQUIRED,
                "owned_scope_projection": (
                    "app/services/deduplicator.py",
                    "tests/test_deduplicator.py",
                ),
            },
        )()
        launch = type(
            "Launch",
            (),
            {
                "task_ref": "TASK-4A-08",
                "package_ref": "package://PKG-1@1#" + "a" * 64,
                "package_digest": "a" * 64,
                "contract_ref": "contract://CONTRACT-1@1#" + "c" * 64,
                "contract_digest": "c" * 64,
            },
        )()
        value = payload()
        unsigned = dict(value)
        unsigned.pop("evidence_sha256")
        unsigned["artifact_sha_chain"] = {
            "request": "3" * 64,
            "process_evidence": "5" * 64,
        }
        value = seal_payload(unsigned)
        with self.assertRaises(PostWorkerAuthorityBridgeError) as caught:
            build_mutation_worker_result_envelope(pkg, launch, value)
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "POST_WORKER_PROVENANCE_INVALID",
        )

    def test_canonical_package_launch_with_verifier_success_reaches_post_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            package_root = base / "package"
            (project / "tests").mkdir(parents=True)
            (project / "app/services").mkdir(parents=True)
            (project / ".venv/bin").mkdir(parents=True)
            (project / ".venv/bin/python").write_text("", encoding="utf-8")
            (project / ".venv/bin/pytest").write_text("", encoding="utf-8")
            package_root.mkdir()
            (project / "tests/test_deduplicator.py").write_text(
                SOURCE,
                encoding="utf-8",
            )
            (project / "app/services/deduplicator.py").write_text(
                "VALUE = 1\n",
                encoding="utf-8",
            )

            completion = materialize_task_4a_08_completion_authority(
                project,
                package_root,
            )
            authority = load_migration_authority(ROOT)
            contract_bridge = build_active_contract_and_run_binding(
                authority=authority,
                completion_authority=completion,
                task=task_inputs(),
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-post-worker",
                worker_task_id="TASK-4A-08",
                plan_version="DP-5.0-CANDIDATE",
                canonical_plan_sha256="6" * 64,
                requirement_version="RUN-REQUIREMENTS",
                requirements_sha256="7" * 64,
                semantic_version="SC-1.0-FROZEN-LINEAGE",
                contract_id="CEC-TASK-4A-08",
                contract_version="1",
            )

            criteria = build_completion_criteria(completion)
            results = tuple(
                CriterionResult(
                    criterion_id=item.criterion_id,
                    verifier_type=item.verifier_type,
                    authoritative_source_ref=item.authoritative_source_ref,
                    state=CompletionState.UNSATISFIED,
                    evidence_refs=(f"{item.authoritative_source_ref}#pre-fixture",),
                    reason_taxonomy="PRE_EXECUTION_UNSATISFIED_FIXTURE",
                    mandatory=item.mandatory,
                )
                for item in criteria
            )
            pre = CompletionAssessment(
                criterion_results=results,
                overall_state=CompletionState.UNSATISFIED,
                criterion_set_digest=criterion_set_digest(criteria),
                evidence_refs=tuple(
                    ref for item in results for ref in item.evidence_refs
                ),
            )

            readiness = collect_codex_auth_readiness(
                run_id="run-post-worker",
                worker_task_id="TASK-4A-08",
                package_id="PKG-TASK-4A-08",
                package_revision=1,
                probes=probes(),
                verified_at_utc="2026-09-10T00:00:00Z",
            )
            canonical_launch = build_canonical_launch(
                package_id="PKG-TASK-4A-08",
                package_revision=1,
                previous_package_digest="",
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                run_binding=contract_bridge.run_binding,
                active_contract=contract_bridge.active_contract,
                pre_execution_assessment_ref="completion://TASK-4A-08/pre#fixture",
                pre_execution_assessment=pre,
                runtime_selection={"backend": "HOST_GATEWAY"},
                exact_tool_authorization_projection=(
                    "PROJECT_OWNED_FILE_LIST",
                    "PROJECT_OWNED_FILE_READ",
                    "PROJECT_OWNED_FILE_WRITE",
                ),
                security_policy_refs=("security://broker-only",),
                quality_policy_refs=(
                    contract_bridge.active_contract.quality_criteria_contract_ref,
                ),
                codex_auth_readiness=readiness,
                approval_context=authority.approval_context(),
                migration_authority_ref="migration-authority://R4.1/manifest",
                readiness_recheck_probes=probes(),
                readiness_recheck_verified_at_utc="2026-09-10T00:00:05Z",
            )
            self.assertIs(
                canonical_launch.package.execution_obligation,
                ExecutionObligation.MUTATION_REQUIRED,
            )

            worker_payload = seal_payload(
                {
                    "status": "completed",
                    "changed_files": ["app/services/deduplicator.py"],
                    "checkpoint_commit": "commit-post-worker",
                    "current_tree": "tree-post-worker",
                    "review_verdict": "PASS",
                    "executor": {"identity": "production-worker-executor"},
                    "governed_effect_evidence": [effect()],
                    "artifact_sha_chain": {
                        "request": "8" * 64,
                        "executor_output": "9" * 64,
                        "process_evidence": "a" * 64,
                    },
                }
            )

            with mock.patch(
                "runtime.orchestrator.completion_authority.subprocess.run"
            ) as verifier_run:
                verifier_run.return_value = mock.Mock(
                    returncode=0,
                    stdout=b"pass",
                    stderr=b"",
                )
                evaluation = evaluate_mutation_post_worker_authority(
                    canonical_launch.package,
                    canonical_launch.launch_authorization,
                    contract_bridge.active_contract,
                    completion,
                    project,
                    worker_payload,
                    timeout=30,
                )
            self.assertIs(
                evaluation.post_completion.assessment.overall_state,
                CompletionState.SATISFIED,
            )
            self.assertTrue(evaluation.worker_gate.eligible_for_post_quality)
            self.assertEqual(evaluation.worker_gate.reason_taxonomy, "PASS")


if __name__ == "__main__":
    unittest.main()

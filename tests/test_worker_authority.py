from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionState,
    CriterionResult,
    ExecutionObligation,
    TaskEffectPolicy,
)
from runtime.orchestrator.execution_contract import (
    ActivationProfile,
    ApprovalContext,
    ApprovedExecutionProjection,
    PreflightResult,
    QualityCriterion,
    RunBinding,
    activate_contract,
    build_contract_candidate,
    build_execution_package,
    build_migration_quality_criteria_contract,
    cross_check_contract,
)
from runtime.orchestrator.worker_authority import (
    BLOCKED_POST_QUALITY,
    BLOCKED_REMEDIATION_EXHAUSTED,
    GovernedEffectEvidence,
    QualityAssessment,
    QualityState,
    RemediationLedger,
    RemediationMode,
    RemediationPolicy,
    RemediationRoute,
    WorkerAuthorityError,
    WorkerGateState,
    WorkerResultEnvelope,
    WorkerTerminalState,
    authorize_worker_launch,
    evaluate_worker_result,
    execution_package_ref,
    review_post_quality,
    route_quality_failure,
)


def assessment(state: CompletionState, digest: str = "crit-digest") -> CompletionAssessment:
    return CompletionAssessment(
        criterion_results=(
            CriterionResult(
                criterion_id="C-1",
                verifier_type="fixture",
                authoritative_source_ref="src://1",
                state=state,
                evidence_refs=("ev://completion/1",),
            ),
        ),
        overall_state=state,
        criterion_set_digest=digest,
        evidence_refs=("ev://completion/1",),
    )


def approval() -> ApprovalContext:
    return ApprovalContext(
        full_plan_approval_required=True,
        full_plan_approval_ref="approval://full-plan",
        approved_semantic_digest="sem-digest",
        reviewed_semantic_digest="sem-digest",
    )


def active_contract(*, effect_policy: TaskEffectPolicy = TaskEffectPolicy.MUTATING):
    projection = ApprovedExecutionProjection(
        requirement_refs=("REQ-035", "REQ-036", "REQ-037", "REQ-038"),
        plan_task_ref="TASK-ORCH-03",
        purpose="Worker Authority + Post-Quality + Explicit Bounded Remediation",
        task_effect_policy=effect_policy,
        completion_criteria_ids=("C-1",),
        validation_criteria=("TEST-WRK-001", "TEST-QUAL-003"),
        quality_criteria_contract_ref="quality://migration/1",
        change_targets=("runtime/orchestrator/worker_authority.py",),
        owned_scope=("runtime/orchestrator/worker_authority.py",),
        allowed_worker_terminal_states=(
            "CHANGED",
            "COMPLETED",
            "SKIPPED_SATISFIED",
            "BLOCKED",
            "INVALID_COMPLETION",
        ),
        allowed_capabilities=("LIST", "READ", "WRITE"),
        permission_requirements=("PERM-WRITE",),
        security_requirements=("SEC-NO-SECRET",),
        evidence_requirements=("EFFECT-RECEIPT", "OUTPUT-PROVENANCE", "SECURITY-EVIDENCE"),
        remediation_policy_ref="remediation://orch03/v1",
        source_digests={"plan": "plan-digest", "requirement": "req-digest", "semantic": "sem-digest"},
    )
    a = approval()
    candidate = build_contract_candidate(
        contract_id="orch03-contract",
        contract_version="1.0",
        approved_projection=projection,
        approval_context=a,
    )
    check = cross_check_contract(candidate, projection, a)
    return activate_contract(candidate, cross_check=check, approved_projection=projection, approval_context=a)


def package(
    *,
    pre_state: CompletionState = CompletionState.UNSATISFIED,
    effect_policy: TaskEffectPolicy = TaskEffectPolicy.MUTATING,
    activation_profile: ActivationProfile = ActivationProfile.MIGRATION_APPROVED_PLAN,
):
    contract = active_contract(effect_policy=effect_policy)
    rb = RunBinding(
        project_id="global-gpt-harness-engineering",
        gate_id="G-ORCH-03",
        lv_id="LV-4A",
        run_id="run-orch03-001",
        worker_task_id="TASK-ORCH-03",
        plan_version="DP-6.0-R4.1",
        plan_digest="plan-digest",
        requirement_version="CRB-2.0-R4.1",
        requirement_digest="req-digest",
        semantic_version="SC-5.0-R4.1",
        semantic_digest="sem-digest",
    )
    pkg = build_execution_package(
        package_id="pkg-orch03",
        package_revision=1,
        previous_package_digest="",
        activation_profile=activation_profile,
        run_binding=rb,
        active_contract=contract,
        pre_execution_assessment_ref="assessment://pre/orch03",
        pre_execution_assessment=assessment(pre_state),
        runtime_selection={"mode": "broker-native-codex", "worker": "TASK-ORCH-03"},
        exact_tool_authorization_projection=("LIST", "READ", "WRITE"),
        security_policy_refs=("security://v1",),
        quality_policy_refs=("quality://migration/1",),
        codex_backed_worker=False,
        codex_auth_readiness=None,
    )
    return contract, pkg


def launch(pkg):
    return authorize_worker_launch(pkg, PreflightResult(ready=True, evidence_digest="preflight-digest"))


def mutation(
    *,
    scope: str = "runtime/orchestrator/worker_authority.py",
    operation: str = "WRITE",
    authorized: bool = True,
    receipt_intent: str = "intent-1",
    security: bool = True,
    mutation_performed: bool = True,
):
    return GovernedEffectEvidence(
        effect_id="effect-1",
        operation=operation,
        scope_ref=scope,
        intent_digest="intent-1",
        receipt_intent_digest=receipt_intent,
        receipt_digest="receipt-1",
        authorized=authorized,
        mutation_performed=mutation_performed,
        security_passed=security,
        evidence_refs=("effect://receipt/1",),
    )


def worker_result(pkg, *, terminal: str = "CHANGED", effects=None, reason: str = "", claimed: str = ""):
    return WorkerResultEnvelope(
        worker_id="worker-A",
        task_ref=pkg.run_binding.worker_task_id,
        package_ref=execution_package_ref(pkg),
        package_digest=pkg.package_digest,
        contract_ref=pkg.contract_ref,
        contract_digest=pkg.contract_digest,
        terminal_state=terminal,
        reason_taxonomy=reason,
        effect_evidence=tuple(effects if effects is not None else (mutation(),)),
        output_artifact_refs=("artifact://worker/result",),
        output_provenance_refs=("provenance://broker/output",),
        security_evidence_refs=("security://broker/private-scan",),
        worker_claimed_obligation=claimed,
    )


def quality(contract, pkg, result, *, passed: bool = True, reviewer: str = "quality-B", criterion_digest: str | None = None, quality_ref: str | None = None, worker_digest: str | None = None, validation=None, security_refs=("security://reviewer/independent-scan",)):
    return QualityAssessment(
        reviewer_id=reviewer,
        worker_result_digest=worker_digest or result.result_digest,
        contract_digest=contract.contract_digest,
        package_digest=pkg.package_digest,
        completion_criterion_set_digest=criterion_digest or pkg.criterion_set_digest,
        validation_criteria=tuple(validation if validation is not None else contract.validation_criteria),
        quality_criteria_contract_ref=quality_ref or contract.quality_criteria_contract_ref,
        objective_tests_passed=passed,
        security_passed=passed,
        quality_passed=passed,
        review_evidence_refs=("quality://evidence/review",),
        security_evidence_refs=tuple(security_refs),
    )


class WorkerAuthorityTests(unittest.TestCase):
    def test_wrk_001_mutation_required_exact_write_post_satisfied_candidate_success(self):
        contract, pkg = package()
        result = worker_result(pkg)
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertTrue(gate.eligible_for_post_quality)
        self.assertIs(gate.authoritative_execution_obligation, ExecutionObligation.MUTATION_REQUIRED)

    def test_wrk_002_mutation_required_write_zero_normal_completion_invalid(self):
        _, pkg = package()
        result = worker_result(pkg, effects=())
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertIs(gate.state, WorkerGateState.INVALID_COMPLETION)
        self.assertEqual(gate.reason_taxonomy, "REQUIRED_GOVERNED_MUTATION_EVIDENCE_MISSING")

    def test_wrk_003_technical_impossible_blocks_with_bounded_reason(self):
        _, pkg = package()
        result = worker_result(pkg, terminal="BLOCKED", effects=(), reason="TECHNICAL_IMPOSSIBLE")
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=None)
        self.assertIs(gate.state, WorkerGateState.BLOCKED)

    def test_wrk_004_scope_expansion_is_invalid_and_effect_not_accepted(self):
        _, pkg = package()
        result = worker_result(pkg, effects=(mutation(scope="outside/scope"),))
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertIs(gate.state, WorkerGateState.INVALID_COMPLETION)

    def test_wrk_005_unknown_or_unapproved_tool_is_invalid_no_fallback(self):
        _, pkg = package()
        result = worker_result(pkg, effects=(mutation(operation="NATIVE_SHELL"),))
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertIs(gate.state, WorkerGateState.INVALID_COMPLETION)

    def test_wrk_006_none_satisfied_only_allows_skipped_satisfied(self):
        _, pkg = package(pre_state=CompletionState.SATISFIED)
        self.assertIs(pkg.execution_obligation, ExecutionObligation.NONE_SATISFIED)
        result = worker_result(pkg, terminal="SKIPPED_SATISFIED", effects=())
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=None)
        self.assertTrue(gate.eligible_for_post_quality)

    def test_auth_002_integration_worker_claim_cannot_override_package_obligation(self):
        _, pkg = package()
        result = worker_result(pkg, claimed="NONE_SATISFIED")
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertIs(gate.authoritative_execution_obligation, ExecutionObligation.MUTATION_REQUIRED)

    def test_auth_003_integration_launch_authorization_is_exact_package_consumption(self):
        _, pkg = package()
        auth = launch(pkg)
        forged = replace(auth, contract_digest="forged")
        result = worker_result(pkg)
        with self.assertRaises(WorkerAuthorityError) as caught:
            evaluate_worker_result(pkg, forged, result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertEqual(caught.exception.reason_taxonomy, "WORKER_LAUNCH_AUTHORIZATION_TAMPER")

    def test_mixed_valid_write_and_unapproved_tool_is_invalid(self):
        _, pkg = package()
        result = worker_result(
            pkg,
            effects=(
                mutation(),
                mutation(operation="NATIVE_SHELL", authorized=False, mutation_performed=False),
            ),
        )
        gate = evaluate_worker_result(
            pkg,
            launch(pkg),
            result,
            post_completion_assessment=assessment(CompletionState.SATISFIED),
        )
        self.assertIs(gate.state, WorkerGateState.INVALID_COMPLETION)
        self.assertEqual(gate.reason_taxonomy, "EFFECT_OUTSIDE_PACKAGE_AUTHORITY")

    def test_read_only_success_requires_output_and_security_provenance(self):
        _, pkg = package(
            pre_state=CompletionState.UNSATISFIED,
            effect_policy=TaskEffectPolicy.READ_ONLY,
        )
        result = worker_result(
            pkg,
            terminal="COMPLETED",
            effects=(mutation(operation="READ", mutation_performed=False),),
        )
        result = replace(result, output_artifact_refs=(), output_provenance_refs=())
        gate = evaluate_worker_result(
            pkg,
            launch(pkg),
            result,
            post_completion_assessment=assessment(CompletionState.UNSATISFIED),
        )
        self.assertIs(gate.state, WorkerGateState.INVALID_COMPLETION)
        self.assertEqual(gate.reason_taxonomy, "WORKER_OUTPUT_PROVENANCE_MISSING")


class PostQualityTests(unittest.TestCase):
    def _eligible(self):
        contract, pkg = package()
        result = worker_result(pkg)
        gate = evaluate_worker_result(pkg, launch(pkg), result, post_completion_assessment=assessment(CompletionState.SATISFIED))
        return contract, pkg, result, gate

    def test_qual_003_worker_claims_complete_but_quality_criterion_fail(self):
        contract, pkg, result, gate = self._eligible()
        reviewed = review_post_quality(pkg, contract, result, gate, quality(contract, pkg, result, passed=False))
        self.assertIs(reviewed.state, QualityState.FAIL)

    def test_qual_004_same_lineage_objective_evidence_pass(self):
        contract, pkg, result, gate = self._eligible()
        reviewed = review_post_quality(pkg, contract, result, gate, quality(contract, pkg, result, passed=True))
        self.assertTrue(reviewed.passed)

    def test_qual_005_approved_requirement_and_harness_policy_deterministic_quality_contract(self):
        criterion = QualityCriterion(
            criterion_id="Q-ORCH03",
            rule_ref="rule://orch03",
            source_ref="FINAL-DP-2.0",
            requirement_refs=("REQ-037",),
            scope_refs=("runtime/orchestrator/worker_authority.py",),
            permission_refs=("PERM-WRITE",),
        )
        kwargs = dict(
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            source_refs=("FINAL-DP-2.0", "FINAL-SC-1.0"),
            policy_version="harness-quality-v1",
            approved_quality_obligations=(criterion,),
            harness_policy_criteria=(),
            approved_requirement_refs=("REQ-037",),
            approved_scope=("runtime/orchestrator/worker_authority.py",),
            approved_permissions=("PERM-WRITE",),
        )
        self.assertEqual(
            build_migration_quality_criteria_contract(**kwargs).digest,
            build_migration_quality_criteria_contract(**kwargs).digest,
        )

    def test_qual_006_quality_candidate_cannot_invent_product_requirement(self):
        criterion = QualityCriterion(
            criterion_id="Q-BAD",
            rule_ref="rule://bad",
            source_ref="source://bad",
            requirement_refs=("REQ-999",),
        )
        with self.assertRaises(Exception):
            build_migration_quality_criteria_contract(
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                source_refs=("FINAL-DP-2.0",),
                policy_version="harness-quality-v1",
                approved_quality_obligations=(criterion,),
                harness_policy_criteria=(),
                approved_requirement_refs=("REQ-037",),
                approved_scope=("runtime/orchestrator/worker_authority.py",),
                approved_permissions=("PERM-WRITE",),
            )

    def test_qual_007_pre_post_quality_lineage_mismatch_blocks(self):
        contract, pkg, result, gate = self._eligible()
        reviewed = review_post_quality(
            pkg,
            contract,
            result,
            gate,
            quality(contract, pkg, result, criterion_digest="different-digest"),
        )
        self.assertFalse(reviewed.passed)
        self.assertEqual(reviewed.reason_taxonomy, "PRE_POST_COMPLETION_LINEAGE_DRIFT")

    def test_qual_008_quality_reviewer_cannot_mutate_sealed_worker_artifact(self):
        contract, pkg, result, gate = self._eligible()
        sealed_quality = quality(contract, pkg, result)
        tampered = replace(result, output_artifact_refs=("artifact://mutated",))
        reviewed = review_post_quality(pkg, contract, tampered, gate, sealed_quality)
        self.assertFalse(reviewed.passed)
        self.assertEqual(reviewed.reason_taxonomy, "SEALED_WORKER_RESULT_DRIFT")

    def test_post_quality_cannot_reuse_eligible_gate_for_different_worker_result(self):
        contract, pkg, result, gate = self._eligible()
        tampered = replace(result, effect_evidence=())
        reviewed = review_post_quality(
            pkg,
            contract,
            tampered,
            gate,
            quality(contract, pkg, tampered),
        )
        self.assertFalse(reviewed.passed)
        self.assertEqual(reviewed.reason_taxonomy, "WORKER_GATE_RESULT_BINDING_DRIFT")

    def test_output_and_complementary_security_provenance_are_required(self):
        contract, pkg, result, gate = self._eligible()
        no_provenance = replace(result, output_provenance_refs=())
        bad_gate = evaluate_worker_result(pkg, launch(pkg), no_provenance, post_completion_assessment=assessment(CompletionState.SATISFIED))
        self.assertFalse(bad_gate.eligible_for_post_quality)
        same_security = quality(
            contract,
            pkg,
            result,
            security_refs=result.security_evidence_refs,
        )
        reviewed = review_post_quality(pkg, contract, result, gate, same_security)
        self.assertEqual(reviewed.reason_taxonomy, "SECURITY_REVIEW_NOT_COMPLEMENTARY")


class RemediationTests(unittest.TestCase):
    def policy(
        self,
        *,
        mode=RemediationMode.BOUNDED,
        max_attempts=2,
        scope=("runtime/orchestrator/worker_authority.py",),
        policy_ref="remediation://orch03/v1",
    ):
        return RemediationPolicy(
            policy_ref=policy_ref,
            mode=mode,
            max_attempts=max_attempts if mode is RemediationMode.BOUNDED else 0,
            allowed_fix_scope=scope if mode is RemediationMode.BOUNDED else (),
        )

    def bounded_context(self):
        contract, pkg = package(activation_profile=ActivationProfile.FULL_ORCHESTRATION)
        return contract, pkg, self.policy()

    def disabled_context(self):
        contract, pkg = package(activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN)
        return contract, pkg, self.policy(mode=RemediationMode.DISABLED)

    def reserve(self, ledger, *, contract=None, pkg=None, policy=None):
        if contract is None or pkg is None or policy is None:
            contract, pkg, policy = self.bounded_context()
        return ledger.reserve_attempt(
            policy,
            package=pkg,
            active_contract=contract,
            failure_owner="QUALITY_CRITERIA_DEFECT",
        )

    def launch(self, ledger, event, *, contract, pkg, policy):
        return ledger.authorize_remediation_launch(
            event,
            policy,
            package=pkg,
            active_contract=contract,
            requested_fix_scope=("runtime/orchestrator/worker_authority.py",),
        )

    def review(self, ledger, event, *, contract, pkg, policy, passed=False, digest="quality-review"):
        return ledger.commit_attempt_review(
            event,
            policy,
            package=pkg,
            active_contract=contract,
            quality_passed=passed,
            quality_assessment_digest=digest,
        )

    def test_rem_001_quality_fail_policy_disabled_immediate_block_no_retry(self):
        contract, pkg, policy = self.disabled_context()
        self.assertIs(
            route_quality_failure(policy, package=pkg, active_contract=contract),
            RemediationRoute.BLOCKED,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(caught.exception.reason_taxonomy, BLOCKED_POST_QUALITY)

    def test_rem_002_bounded_policy_missing_max_attempts_invalid(self):
        with self.assertRaises(WorkerAuthorityError) as caught:
            RemediationPolicy(
                policy_ref="remediation://bad",
                mode=RemediationMode.BOUNDED,
                max_attempts=0,
                allowed_fix_scope=("runtime/orchestrator/worker_authority.py",),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_MAX_ATTEMPTS_INVALID")

    def test_rem_003_last_committed_zero_next_index_one_commit_before_running(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            ledger = RemediationLedger(path)
            event = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(event.attempt_index, 1)
            records_before_launch = [
                json.loads(line) for line in path.read_text().splitlines() if line.strip()
            ]
            self.assertEqual(records_before_launch[-1]["record_type"], "REMEDIATION_ATTEMPT_STARTED")
            launch_digest = self.launch(
                ledger, event, contract=contract, pkg=pkg, policy=policy
            )
            self.assertTrue(launch_digest)
            records_after_launch = [
                json.loads(line) for line in path.read_text().splitlines() if line.strip()
            ]
            self.assertEqual(
                records_after_launch[-1]["record_type"],
                "REMEDIATION_ATTEMPT_LAUNCH_AUTHORIZED",
            )

    def test_rem_004_restart_restores_durable_attempt_index(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = self.reserve(
                RemediationLedger(path), contract=contract, pkg=pkg, policy=policy
            )
            restored = RemediationLedger(path).resume_open_attempt(
                policy,
                package=pkg,
                active_contract=contract,
            )
            self.assertEqual(restored.attempt_index, 1)
            self.assertEqual(restored.attempt_event_id, first.attempt_event_id)

    def test_rem_005_last_committed_max_attempts_exhausted_blocks(self):
        contract, pkg = package(activation_profile=ActivationProfile.FULL_ORCHESTRATION)
        policy = self.policy(max_attempts=1)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.launch(ledger, first, contract=contract, pkg=pkg, policy=policy)
            self.review(
                ledger,
                first,
                contract=contract,
                pkg=pkg,
                policy=policy,
                passed=False,
                digest="quality-fail-1",
            )
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(caught.exception.reason_taxonomy, BLOCKED_REMEDIATION_EXHAUSTED)

    def test_rem_006_remediation_exceeds_allowed_fix_scope_blocks(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            event = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            with self.assertRaises(WorkerAuthorityError) as caught:
                ledger.authorize_remediation_launch(
                    event,
                    policy,
                    package=pkg,
                    active_contract=contract,
                    requested_fix_scope=("outside/scope",),
                )
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_FIX_SCOPE_EXCEEDED")

    def test_rem_007_silent_contract_meaning_change_blocks(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            event = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            forged_contract = replace(contract, contract_digest="changed")
            with self.assertRaises(WorkerAuthorityError) as caught:
                ledger.authorize_remediation_launch(
                    event,
                    policy,
                    package=pkg,
                    active_contract=forged_contract,
                    requested_fix_scope=("runtime/orchestrator/worker_authority.py",),
                )
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_POLICY_BINDING_DRIFT")

    def test_rem_008_no_automatic_corrective_extra_turn_without_approved_semantics(self):
        contract, pkg, policy = self.bounded_context()
        self.assertIs(
            route_quality_failure(policy, package=pkg, active_contract=contract),
            RemediationRoute.REMEDIATION_REQUIRED,
        )
        # Routing yields a governed state only. No Worker callback/executor exists here.

    def test_rem_009_uncommitted_attempt_event_cannot_authorize_worker_launch(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            fake = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            Path(tmp, "events.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.launch(
                    ledger, fake, contract=contract, pkg=pkg, policy=policy
                )
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_ATTEMPT_NOT_DURABLE")

    def test_rem_010_committed_start_then_crash_before_worker_no_duplicate_attempt(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            ledger = RemediationLedger(path)
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            # Crash occurs before launch authorization. Restart restores the same
            # consumed attempt and may authorize that exact attempt once.
            restarted = RemediationLedger(path)
            restored = restarted.resume_open_attempt(
                policy,
                package=pkg,
                active_contract=contract,
            )
            self.assertEqual(restored, first)
            self.assertTrue(
                self.launch(
                    restarted,
                    restored,
                    contract=contract,
                    pkg=pkg,
                    policy=policy,
                )
            )
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.reserve(
                    restarted, contract=contract, pkg=pkg, policy=policy
                )
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_ATTEMPT_ALREADY_RESERVED")
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertEqual(
                sum(1 for r in records if r["record_type"] == "REMEDIATION_ATTEMPT_STARTED"),
                1,
            )

    def test_rem_011_crash_after_worker_starts_resume_exact_attempt_lineage_no_blind_allocation(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            ledger = RemediationLedger(path)
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            launch_digest = self.launch(
                ledger, first, contract=contract, pkg=pkg, policy=policy
            )
            self.assertTrue(launch_digest)

            restarted = RemediationLedger(path)
            restored = restarted.resume_open_attempt(
                policy,
                package=pkg,
                active_contract=contract,
            )
            self.assertEqual(restored, first)

            # The durable one-shot launch marker prevents blind replay of the
            # same Worker turn after crash.
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.launch(
                    restarted,
                    restored,
                    contract=contract,
                    pkg=pkg,
                    policy=policy,
                )
            self.assertEqual(
                caught.exception.reason_taxonomy,
                "REMEDIATION_ATTEMPT_ALREADY_LAUNCHED",
            )
            with self.assertRaises(WorkerAuthorityError):
                self.reserve(
                    restarted, contract=contract, pkg=pkg, policy=policy
                )

    def test_reviewed_failed_attempt_allows_monotonic_next_index(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.launch(ledger, first, contract=contract, pkg=pkg, policy=policy)
            self.review(
                ledger,
                first,
                contract=contract,
                pkg=pkg,
                policy=policy,
                passed=False,
                digest="quality-fail-1",
            )
            second = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(second.attempt_index, 2)
            self.assertNotEqual(first.attempt_event_id, second.attempt_event_id)

    def test_reviewed_pass_attempt_prohibits_further_reservation(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RemediationLedger(Path(tmp) / "events.jsonl")
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.launch(ledger, first, contract=contract, pkg=pkg, policy=policy)
            self.review(
                ledger,
                first,
                contract=contract,
                pkg=pkg,
                policy=policy,
                passed=True,
                digest="quality-pass-1",
            )
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_NOT_REQUIRED_AFTER_PASS")

    def test_bounded_policy_must_match_active_contract_and_profile(self):
        contract, migration_pkg = package(
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN
        )
        bounded = self.policy()
        with self.assertRaises(WorkerAuthorityError) as caught:
            route_quality_failure(
                bounded,
                package=migration_pkg,
                active_contract=contract,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "REMEDIATION_POLICY_PROFILE_VIOLATION",
        )

        full_contract, full_pkg, policy = self.bounded_context()
        forged = self.policy(policy_ref="remediation://forged")
        with self.assertRaises(WorkerAuthorityError) as caught:
            route_quality_failure(
                forged,
                package=full_pkg,
                active_contract=full_contract,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "REMEDIATION_POLICY_BINDING_DRIFT",
        )

    def test_review_record_tamper_is_fail_closed(self):
        contract, pkg, policy = self.bounded_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            ledger = RemediationLedger(path)
            first = self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.launch(ledger, first, contract=contract, pkg=pkg, policy=policy)
            self.review(
                ledger,
                first,
                contract=contract,
                pkg=pkg,
                policy=policy,
                passed=False,
                digest="quality-fail-1",
            )
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            records[-1]["quality_passed"] = True
            path.write_text(
                "\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(WorkerAuthorityError) as caught:
                self.reserve(ledger, contract=contract, pkg=pkg, policy=policy)
            self.assertEqual(caught.exception.reason_taxonomy, "REMEDIATION_LEDGER_CORRUPT")


if __name__ == "__main__":
    unittest.main()

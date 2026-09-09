from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from runtime.orchestrator.completion_contract import (
    CompletionAssessment,
    CompletionState,
    CriterionResult,
    ExecutionObligation,
    TaskEffectPolicy,
)
from runtime.orchestrator.execution_contract import (
    ALWAYS_BEFORE_CODEX_LAUNCH,
    PRE_QUALITY_REFERENCE_SATISFIED,
    ActivationProfile,
    ApprovalContext,
    ApprovedExecutionProjection,
    CanonicalExecutionContract,
    CodexAuthReadinessEvidence,
    ContractActivationError,
    ContractBuildError,
    ContractStatus,
    CrossCheckFailureOwner,
    GovernedContractError,
    PackageBuildError,
    PreflightBlocked,
    PreflightContext,
    QualityCriterion,
    READY,
    RunBinding,
    activate_contract,
    build_contract_candidate,
    build_execution_package,
    build_migration_quality_criteria_contract,
    codex_launch_binding_digest,
    cross_check_contract,
    preflight_execution_package,
)


def assessment(state: CompletionState = CompletionState.UNSATISFIED, digest: str = "crit-digest") -> CompletionAssessment:
    return CompletionAssessment(
        criterion_results=(
            CriterionResult(
                criterion_id="C-1",
                verifier_type="fixture",
                authoritative_source_ref="src://1",
                state=state,
                evidence_refs=("ev://1",),
            ),
        ),
        overall_state=state,
        criterion_set_digest=digest,
        evidence_refs=("ev://1",),
    )


def approval(*, required: bool = True, approved: bool = True, stale: bool = False) -> ApprovalContext:
    return ApprovalContext(
        full_plan_approval_required=required,
        full_plan_approval_ref="approval://full-plan" if approved else "",
        approved_semantic_digest="sem-digest",
        reviewed_semantic_digest="stale-sem-digest" if stale else "sem-digest",
        other_approval_refs=("approval://tool-use",),
    )


def projection() -> ApprovedExecutionProjection:
    return ApprovedExecutionProjection(
        requirement_refs=("REQ-031", "REQ-032", "REQ-033"),
        plan_task_ref="TASK-ORCH-02",
        purpose="Unified Execution Contract & Execution Packaging",
        task_effect_policy=TaskEffectPolicy.MUTATING,
        completion_criteria_ids=("C-1",),
        validation_criteria=("V-1",),
        quality_criteria_contract_ref="quality://migration/1",
        change_targets=("runtime/orchestrator/execution_contract.py",),
        owned_scope=("runtime/orchestrator/execution_contract.py",),
        allowed_worker_terminal_states=("CHANGED", "BLOCKED", "INVALID_COMPLETION"),
        allowed_capabilities=("LIST", "READ", "WRITE"),
        permission_requirements=("PERM-WRITE",),
        security_requirements=("SEC-NO-SECRET",),
        evidence_requirements=("EVIDENCE-RECEIPT",),
        remediation_policy_ref="remediation://disabled",
        source_digests={"plan": "plan-digest", "requirement": "req-digest", "semantic": "sem-digest"},
    )


def candidate(*, approval_context: ApprovalContext | None = None) -> CanonicalExecutionContract:
    return build_contract_candidate(
        contract_id="contract-1",
        contract_version="1.0",
        approved_projection=projection(),
        approval_context=approval_context or approval(),
    )


def active_contract() -> CanonicalExecutionContract:
    p = projection()
    a = approval()
    c = candidate(approval_context=a)
    check = cross_check_contract(c, p, a)
    return activate_contract(c, cross_check=check, approved_projection=p, approval_context=a)


def run_binding() -> RunBinding:
    return RunBinding(
        project_id="global-gpt-harness-engineering",
        gate_id="G-ORCH-02",
        lv_id="LV-4A",
        run_id="run-001",
        worker_task_id="worker-001",
        plan_version="DP-6.0-R4.1",
        plan_digest="plan-digest",
        requirement_version="CRB-2.0-R4.1",
        requirement_digest="req-digest",
        semantic_version="SC-5.0-R4.1",
        semantic_digest="sem-digest",
    )


def auth_evidence(
    rb: RunBinding | None = None,
    *,
    status: str = READY,
    cli: str = "0.150.1",
    env: str = "env-A",
    schema: str = "schema-A",
    package_id: str = "pkg-1",
    package_revision: int = 1,
) -> CodexAuthReadinessEvidence:
    rb = rb or run_binding()
    return CodexAuthReadinessEvidence(
        evidence_id="auth-ready-1",
        verified_at_utc=datetime.now(timezone.utc).isoformat(),
        cli_version=cli,
        environment_fingerprint=env,
        transport_schema_digest=schema,
        auth_status=status,
        source_evidence_refs=("evidence://codex-auth-recheck",),
        recheck_policy=ALWAYS_BEFORE_CODEX_LAUNCH,
        launch_binding_digest=codex_launch_binding_digest(
            cli_version=cli,
            environment_fingerprint=env,
            transport_schema_digest=schema,
            run_id=rb.run_id,
            worker_task_id=rb.worker_task_id,
            package_id=package_id,
            package_revision=package_revision,
        ),
    )


_AUTO_AUTH = object()

def package(*, contract: CanonicalExecutionContract | None = None, rb: RunBinding | None = None, auth: CodexAuthReadinessEvidence | None | object = _AUTO_AUTH, codex: bool = False):
    contract = contract or active_contract()
    rb = rb or run_binding()
    if codex and auth is _AUTO_AUTH:
        auth = auth_evidence(rb)
    if auth is _AUTO_AUTH:
        auth = None
    return build_execution_package(
        package_id="pkg-1",
        package_revision=1,
        previous_package_digest="",
        activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
        run_binding=rb,
        active_contract=contract,
        pre_execution_assessment_ref="assessment://pre/1",
        pre_execution_assessment=assessment(),
        runtime_selection={"mode": "codex-cli" if codex else "mock", "worker": "worker-001"},
        exact_tool_authorization_projection=("LIST", "READ", "WRITE"),
        security_policy_refs=("security://v1",),
        quality_policy_refs=("quality://migration/1",),
        codex_backed_worker=codex,
        codex_auth_readiness=auth,
    )


class ContractApprovalTests(unittest.TestCase):
    def test_apr_001_missing_full_plan_approval_denies_contract_build(self) -> None:
        with self.assertRaisesRegex(ContractBuildError, "Full Plan Approval"):
            candidate(approval_context=approval(approved=False))

    def test_apr_002_full_plan_approved_is_build_eligible(self) -> None:
        self.assertEqual(candidate().status, ContractStatus.CANDIDATE)

    def test_apr_003_stale_approval_requires_reapproval(self) -> None:
        with self.assertRaises(ContractBuildError) as caught:
            candidate(approval_context=approval(stale=True))
        self.assertEqual(caught.exception.reason_taxonomy, "PLAN_REAPPROVAL_REQUIRED")

    def test_apr_004_other_approval_does_not_replace_full_plan_approval(self) -> None:
        a = ApprovalContext(
            full_plan_approval_required=True,
            full_plan_approval_ref="",
            approved_semantic_digest="sem-digest",
            reviewed_semantic_digest="sem-digest",
            other_approval_refs=("approval://discovery", "approval://install", "approval://use"),
        )
        with self.assertRaises(ContractBuildError):
            candidate(approval_context=a)


    def test_approval_lineage_cannot_be_disabled_by_required_flag(self) -> None:
        a = ApprovalContext(
            full_plan_approval_required=False,
            full_plan_approval_ref="",
            approved_semantic_digest="sem-digest",
            reviewed_semantic_digest="sem-digest",
            other_approval_refs=(),
        )
        with self.assertRaises(ContractBuildError) as caught:
            candidate(approval_context=a)
        self.assertEqual(caught.exception.reason_taxonomy, "APPROVAL_LINEAGE_MISSING")

    def test_approval_semantic_digest_missing_fails_closed(self) -> None:
        for approved_digest, reviewed_digest in (("", ""), ("sem-digest", ""), ("", "sem-digest")):
            with self.subTest(approved_digest=approved_digest, reviewed_digest=reviewed_digest):
                a = ApprovalContext(
                    full_plan_approval_required=True,
                    full_plan_approval_ref="approval://full-plan",
                    approved_semantic_digest=approved_digest,
                    reviewed_semantic_digest=reviewed_digest,
                    other_approval_refs=(),
                )
                with self.assertRaises(ContractBuildError) as caught:
                    candidate(approval_context=a)
                self.assertEqual(
                    caught.exception.reason_taxonomy,
                    "APPROVAL_SEMANTIC_DIGEST_MISSING",
                )


    def test_approval_semantic_digest_must_match_authoritative_projection(self) -> None:
        stale_but_self_consistent = ApprovalContext(
            full_plan_approval_required=True,
            full_plan_approval_ref="approval://full-plan",
            approved_semantic_digest="old-semantic-digest",
            reviewed_semantic_digest="old-semantic-digest",
            other_approval_refs=("approval://tool-use",),
        )
        with self.assertRaises(ContractBuildError) as caught:
            candidate(approval_context=stale_but_self_consistent)
        self.assertEqual(caught.exception.reason_taxonomy, "PLAN_REAPPROVAL_REQUIRED")


class MigrationBootstrapTests(unittest.TestCase):
    def _criterion(self, criterion_id: str, *, req: str = "REQ-031", scope: str = "runtime/orchestrator/execution_contract.py", perm: str = "PERM-WRITE") -> QualityCriterion:
        return QualityCriterion(
            criterion_id=criterion_id,
            rule_ref=f"rule://{criterion_id}",
            source_ref=f"source://{criterion_id}",
            requirement_refs=(req,),
            scope_refs=(scope,),
            permission_refs=(perm,),
        )

    def test_mig_003_bootstrap_is_deterministic_and_orch06_independent(self) -> None:
        kwargs = dict(
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            source_refs=("FINAL-DP-2.0", "FINAL-SC-1.0"),
            policy_version="harness-quality-v1",
            approved_quality_obligations=(self._criterion("Q-LEGACY"),),
            harness_policy_criteria=(self._criterion("Q-HARNESS"),),
            approved_requirement_refs=("REQ-031",),
            approved_scope=("runtime/orchestrator/execution_contract.py",),
            approved_permissions=("PERM-WRITE",),
        )
        first = build_migration_quality_criteria_contract(**kwargs)
        second = build_migration_quality_criteria_contract(**kwargs)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.pre_quality_state, PRE_QUALITY_REFERENCE_SATISFIED)

    def test_mig_004_bootstrap_persists_reference_satisfied_state(self) -> None:
        artifact = build_migration_quality_criteria_contract(
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            source_refs=("FINAL-DP-2.0",),
            policy_version="harness-quality-v1",
            approved_quality_obligations=(self._criterion("Q-1"),),
            harness_policy_criteria=(),
            approved_requirement_refs=("REQ-031",),
            approved_scope=("runtime/orchestrator/execution_contract.py",),
            approved_permissions=("PERM-WRITE",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "migration-quality.json"
            artifact.persist(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["pre_quality_state"], PRE_QUALITY_REFERENCE_SATISFIED)
            self.assertEqual(payload["digest"], artifact.digest)

    def test_migration_bootstrap_rejects_new_requirement_scope_or_permission(self) -> None:
        for criterion in (
            self._criterion("Q-X", req="REQ-999"),
            self._criterion("Q-X", scope="outside/scope"),
            self._criterion("Q-X", perm="PERM-ADMIN"),
        ):
            with self.subTest(criterion=criterion):
                with self.assertRaises(ContractBuildError):
                    build_migration_quality_criteria_contract(
                        activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                        source_refs=("FINAL-DP-2.0",),
                        policy_version="harness-quality-v1",
                        approved_quality_obligations=(criterion,),
                        harness_policy_criteria=(),
                        approved_requirement_refs=("REQ-031",),
                        approved_scope=("runtime/orchestrator/execution_contract.py",),
                        approved_permissions=("PERM-WRITE",),
                    )

    def test_full_orchestration_prohibits_migration_bootstrap(self) -> None:
        with self.assertRaises(ContractBuildError):
            build_migration_quality_criteria_contract(
                activation_profile=ActivationProfile.FULL_ORCHESTRATION,
                source_refs=("FINAL-DP-2.0",),
                policy_version="harness-quality-v1",
                approved_quality_obligations=(self._criterion("Q-1"),),
                harness_policy_criteria=(),
                approved_requirement_refs=("REQ-031",),
                approved_scope=("runtime/orchestrator/execution_contract.py",),
                approved_permissions=("PERM-WRITE",),
            )


class ContractCrossCheckTests(unittest.TestCase):
    def test_con_001_same_input_same_contract_digest(self) -> None:
        self.assertEqual(candidate().contract_digest, candidate().contract_digest)

    def test_con_002_unvalidated_scope_routes_builder_fix(self) -> None:
        c = replace(candidate(), owned_scope=("outside/scope",))
        result = cross_check_contract(c, projection(), approval())
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.CONTRACT_BUILDER_FIX)

    def test_con_003_candidate_cannot_build_package(self) -> None:
        with self.assertRaises(PackageBuildError):
            package(contract=candidate())

    def test_con_004_planning_semantic_defect_routes_planning_revision(self) -> None:
        c = replace(candidate(), plan_task_ref="TASK-OTHER")
        result = cross_check_contract(c, projection(), approval())
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.PLANNING_REVISION)

    def test_con_005_quality_defect_routes_quality_revision(self) -> None:
        c = replace(candidate(), quality_criteria_contract_ref="quality://wrong")
        result = cross_check_contract(c, projection(), approval())
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.QUALITY_CRITERIA_REVISION)

    def test_con_006_missing_or_stale_approval_routes_approval_resolution(self) -> None:
        c = candidate()
        result = cross_check_contract(c, projection(), approval(stale=True))
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.APPROVAL_RESOLUTION)

    def test_con_007_schema_defect_routes_engineering_block(self) -> None:
        c = replace(candidate(), schema_version="unsupported")
        result = cross_check_contract(c, projection(), approval())
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.ENGINEERING_BLOCK)

    def test_contract_digest_tamper_is_builder_defect(self) -> None:
        c = replace(candidate(), contract_digest="0" * 64)
        result = cross_check_contract(c, projection(), approval())
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.CONTRACT_BUILDER_FIX)

    def test_auth_003_scope_mismatch_without_reapproval_activation_denied(self) -> None:
        p = projection()
        a = approval()
        c = candidate()
        # Defense-in-depth at activation: even a forged PASS cannot bypass baseline scope check.
        forged_scope = replace(c, owned_scope=("outside/scope",))
        forged_pass = replace(cross_check_contract(c, p, a), passed=True, failure_owner=None, reason_taxonomy="PASS")
        with self.assertRaises(ContractActivationError) as caught:
            activate_contract(
                forged_scope,
                cross_check=forged_pass,
                approved_projection=p,
                approval_context=a,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "SCOPE_REAPPROVAL_REQUIRED")

    def test_active_contract_happy_path_has_activation_digest(self) -> None:
        active = active_contract()
        self.assertEqual(active.status, ContractStatus.ACTIVE)
        self.assertTrue(active.activation_digest)

    def test_con_008_failed_crosscheck_requires_fix_and_new_validation(self) -> None:
        p = projection()
        a = approval()
        bad = replace(candidate(), owned_scope=("outside/scope",))
        failed = cross_check_contract(bad, p, a)
        with self.assertRaises(ContractActivationError):
            activate_contract(bad, cross_check=failed, approved_projection=p, approval_context=a)
        fixed = candidate()
        passed = cross_check_contract(fixed, p, a)
        active = activate_contract(fixed, cross_check=passed, approved_projection=p, approval_context=a)
        self.assertEqual(active.status, ContractStatus.ACTIVE)

    def test_con_009_010_direct_active_forgery_cannot_build_package(self) -> None:
        forged = replace(candidate(), status=ContractStatus.ACTIVE, activation_digest="forged")
        with self.assertRaises(PackageBuildError):
            package(contract=forged)

    def test_con_011_happy_path_is_build_crosscheck_activate_only(self) -> None:
        p = projection()
        a = approval()
        c = candidate()
        check = cross_check_contract(c, p, a)
        self.assertTrue(check.passed)
        active = activate_contract(c, cross_check=check, approved_projection=p, approval_context=a)
        self.assertTrue(active.cross_check_digest)
        self.assertTrue(active.activation_digest)


    def test_stale_pass_crosscheck_cannot_activate_tampered_candidate(self) -> None:
        p = projection()
        a = approval()
        c = candidate(approval_context=a)
        stale_pass = cross_check_contract(c, p, a)
        tampered = replace(
            c,
            allowed_capabilities=tuple(sorted((*c.allowed_capabilities, "ADMIN"))),
        )
        with self.assertRaises(ContractActivationError) as caught:
            activate_contract(
                tampered,
                cross_check=stale_pass,
                approved_projection=p,
                approval_context=a,
            )
        self.assertIn(
            caught.exception.reason_taxonomy,
            {"CONTRACT_CROSS_CHECK_NOT_PASS", "CONTRACT_CROSS_CHECK_EVIDENCE_DRIFT"},
        )

    def test_active_contract_semantic_tamper_blocks_package_build(self) -> None:
        active = active_contract()
        tampered = replace(
            active,
            allowed_capabilities=tuple(sorted((*active.allowed_capabilities, "ADMIN"))),
        )
        with self.assertRaises(PackageBuildError) as caught:
            package(contract=tampered)
        self.assertEqual(caught.exception.reason_taxonomy, "CONTRACT_DIGEST_DRIFT")

    def test_obligation_derivation_version_drift_cannot_crosscheck(self) -> None:
        p = projection()
        a = approval()
        c = replace(candidate(approval_context=a), obligation_derivation_version="forged-v99")
        result = cross_check_contract(c, p, a)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_owner, CrossCheckFailureOwner.ENGINEERING_BLOCK)


class PackageTests(unittest.TestCase):
    def context(
        self,
        pkg,
        *,
        contract=None,
        rb=None,
        current_assessment=None,
        auth=None,
        profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
        approval_context=None,
        tool_authorization=None,
        codex_backed_worker=None,
        expected_package_revision=None,
        expected_previous_package_digest=None,
        security_policy_refs=None,
        resume_cursor=None,
        checkpoint_refs=None,
        effect_refs=None,
    ):
        return PreflightContext(
            activation_profile=profile,
            run_binding=rb or pkg.run_binding,
            active_contract=contract or active_contract(),
            current_pre_execution_assessment_ref="assessment://pre/1",
            current_pre_execution_assessment=current_assessment or assessment(),
            current_codex_auth_readiness=auth,
            current_exact_tool_authorization_projection=(
                tuple(tool_authorization)
                if tool_authorization is not None
                else pkg.exact_tool_authorization_projection
            ),
            current_codex_backed_worker=(
                pkg.codex_backed_worker
                if codex_backed_worker is None
                else codex_backed_worker
            ),
            expected_package_revision=(
                pkg.package_revision
                if expected_package_revision is None
                else expected_package_revision
            ),
            expected_previous_package_digest=(
                pkg.previous_package_digest
                if expected_previous_package_digest is None
                else expected_previous_package_digest
            ),
            current_approval_context=approval_context or approval(),
            current_security_policy_refs=(
                tuple(security_policy_refs)
                if security_policy_refs is not None
                else pkg.security_policy_refs
            ),
            current_resume_cursor=pkg.resume_cursor if resume_cursor is None else resume_cursor,
            current_checkpoint_refs=(
                tuple(checkpoint_refs) if checkpoint_refs is not None else pkg.checkpoint_refs
            ),
            current_effect_refs=tuple(effect_refs) if effect_refs is not None else pkg.effect_refs,
            expected_cli_version="0.150.1" if auth else "",
            expected_environment_fingerprint="env-A" if auth else "",
            expected_transport_schema_digest="schema-A" if auth else "",
        )

    def test_pkg_001_wrong_run_scope_or_auth_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        wrong_rb = replace(pkg.run_binding, run_id="wrong-run")
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(pkg, self.context(pkg, contract=active, rb=wrong_rb))
        tampered_scope = replace(pkg, owned_scope_projection=("outside/scope",))
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(tampered_scope, self.context(tampered_scope, contract=active))
        tampered_auth = replace(pkg, exact_tool_authorization_projection=("ADMIN",))
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(tampered_auth, self.context(tampered_auth, contract=active))

    def test_pkg_002_digest_or_schema_drift_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        for bad in (replace(pkg, package_digest="0" * 64), replace(pkg, schema_version="wrong")):
            with self.subTest(bad=bad):
                with self.assertRaises(PreflightBlocked):
                    preflight_execution_package(bad, self.context(bad, contract=active))

    def test_pkg_003_seal_then_in_place_semantic_change_is_tamper(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        tampered = replace(pkg, resume_cursor="changed-after-seal")
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(tampered, self.context(tampered, contract=active))
        self.assertEqual(caught.exception.reason_taxonomy, "PACKAGE_TAMPER_OR_DRIFT")

    def test_pkg_004_profile_mismatch_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(
                pkg,
                self.context(pkg, contract=active, profile=ActivationProfile.FULL_ORCHESTRATION),
            )

    def test_pkg_005_stale_contract_version_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        newer = replace(active, contract_version="2.0", activation_digest="new-activation")
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(pkg, self.context(pkg, contract=newer))

    def test_pkg_006_active_contract_run_profile_is_reconstructable_and_preflight_ready(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        result = preflight_execution_package(pkg, self.context(pkg, contract=active))
        self.assertTrue(result.ready)
        self.assertFalse(hasattr(pkg, "preflight_ready"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            pkg.persist(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["package_digest"], pkg.package_digest)
            self.assertEqual(payload["execution_obligation"], "MUTATION_REQUIRED")

    def test_pkg_007_current_assessment_projection_missing_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        missing = replace(pkg, pre_execution_completion_assessment_ref="")
        with self.assertRaises(PreflightBlocked):
            preflight_execution_package(missing, self.context(missing, contract=active))

    def test_pkg_008_obligation_or_criterion_digest_drift_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        for bad in (
            replace(pkg, execution_obligation=ExecutionObligation.NONE_SATISFIED),
            replace(pkg, criterion_set_digest="other-digest"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(PreflightBlocked):
                    preflight_execution_package(bad, self.context(bad, contract=active))

    def test_preflight_current_tool_authorization_drift_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                pkg,
                self.context(pkg, contract=active, tool_authorization=("READ",)),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "TOOL_AUTHORIZATION_BINDING_DRIFT")

    def test_preflight_approval_ref_set_drift_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        current = ApprovalContext(
            full_plan_approval_required=True,
            full_plan_approval_ref="approval://full-plan",
            approved_semantic_digest="sem-digest",
            reviewed_semantic_digest="sem-digest",
            other_approval_refs=(),
        )
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                pkg,
                self.context(pkg, contract=active, approval_context=current),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "APPROVAL_BINDING_DRIFT")

    def test_blocked_execution_obligation_never_reaches_preflight_ready(self) -> None:
        active = active_contract()
        unknown = assessment(CompletionState.UNKNOWN)
        pkg = build_execution_package(
            package_id="pkg-blocked",
            package_revision=1,
            previous_package_digest="",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=run_binding(),
            active_contract=active,
            pre_execution_assessment_ref="assessment://pre/blocked",
            pre_execution_assessment=unknown,
            runtime_selection={"mode": "mock"},
            exact_tool_authorization_projection=("READ",),
            security_policy_refs=("security://v1",),
            quality_policy_refs=("quality://migration/1",),
            codex_backed_worker=False,
            codex_auth_readiness=None,
        )
        ctx = PreflightContext(
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=pkg.run_binding,
            active_contract=active,
            current_pre_execution_assessment_ref="assessment://pre/blocked",
            current_pre_execution_assessment=unknown,
            current_codex_auth_readiness=None,
            current_exact_tool_authorization_projection=pkg.exact_tool_authorization_projection,
            current_codex_backed_worker=False,
            expected_package_revision=pkg.package_revision,
            expected_previous_package_digest=pkg.previous_package_digest,
            current_approval_context=approval(),
            current_security_policy_refs=pkg.security_policy_refs,
            current_resume_cursor=pkg.resume_cursor,
            current_checkpoint_refs=pkg.checkpoint_refs,
            current_effect_refs=pkg.effect_refs,
        )
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(pkg, ctx)
        self.assertEqual(caught.exception.reason_taxonomy, "BLOCKED_COMPLETION_CONTRACT")

    def test_preflight_current_approval_context_missing_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        ctx = self.context(pkg, contract=active)
        ctx = replace(ctx, current_approval_context=None)
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(pkg, ctx)
        self.assertEqual(caught.exception.reason_taxonomy, "APPROVAL_CONTEXT_MISSING")

    def test_preflight_security_policy_binding_drift_blocks(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                pkg,
                self.context(pkg, contract=active, security_policy_refs=("security://v2",)),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "SECURITY_BINDING_DRIFT")

    def test_preflight_resume_checkpoint_effect_binding_drift_blocks(self) -> None:
        active = active_contract()
        pkg = build_execution_package(
            package_id="pkg-resume",
            package_revision=1,
            previous_package_digest="",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=run_binding(),
            active_contract=active,
            pre_execution_assessment_ref="assessment://pre/1",
            pre_execution_assessment=assessment(),
            runtime_selection={"mode": "mock"},
            exact_tool_authorization_projection=("READ",),
            security_policy_refs=("security://v1",),
            quality_policy_refs=("quality://migration/1",),
            codex_backed_worker=False,
            codex_auth_readiness=None,
            resume_cursor="resume://1",
            checkpoint_refs=("checkpoint://1",),
            effect_refs=("effect://1",),
        )
        cases = (
            {"resume_cursor": "resume://2", "reason": "RESUME_BINDING_DRIFT"},
            {"checkpoint_refs": ("checkpoint://2",), "reason": "CHECKPOINT_BINDING_DRIFT"},
            {"effect_refs": ("effect://2",), "reason": "EFFECT_BINDING_DRIFT"},
        )
        for case in cases:
            reason = case.pop("reason")
            with self.subTest(reason=reason):
                with self.assertRaises(PreflightBlocked) as caught:
                    preflight_execution_package(
                        pkg,
                        self.context(pkg, contract=active, **case),
                    )
                self.assertEqual(caught.exception.reason_taxonomy, reason)

    def test_package_security_binding_required_when_contract_requires_security(self) -> None:
        active = active_contract()
        with self.assertRaises(PackageBuildError) as caught:
            build_execution_package(
                package_id="pkg-no-security",
                package_revision=1,
                previous_package_digest="",
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                run_binding=run_binding(),
                active_contract=active,
                pre_execution_assessment_ref="assessment://pre/1",
                pre_execution_assessment=assessment(),
                runtime_selection={"mode": "mock"},
                exact_tool_authorization_projection=("READ",),
                security_policy_refs=(),
                quality_policy_refs=("quality://migration/1",),
                codex_backed_worker=False,
                codex_auth_readiness=None,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "SECURITY_BINDING_MISSING")

    def test_package_source_digest_binding_is_exact(self) -> None:
        p = projection()
        p = replace(p, source_digests={"plan": "wrong", "requirement": "req-digest", "semantic": "sem-digest"})
        a = approval()
        c = build_contract_candidate(contract_id="contract-x", contract_version="1.0", approved_projection=p, approval_context=a)
        active = activate_contract(c, cross_check=cross_check_contract(c, p, a), approved_projection=p, approval_context=a)
        with self.assertRaises(PackageBuildError) as caught:
            package(contract=active)
        self.assertEqual(caught.exception.reason_taxonomy, "SOURCE_DIGEST_BINDING_DRIFT")

    def test_package_revision_lineage_is_append_only(self) -> None:
        active = active_contract()
        kwargs = dict(
            package_id="pkg-2",
            package_revision=2,
            previous_package_digest="",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=run_binding(),
            active_contract=active,
            pre_execution_assessment_ref="assessment://pre/1",
            pre_execution_assessment=assessment(),
            runtime_selection={"mode": "mock"},
            exact_tool_authorization_projection=("READ",),
            security_policy_refs=("security://v1",),
            quality_policy_refs=("quality://migration/1",),
            codex_backed_worker=False,
            codex_auth_readiness=None,
        )
        with self.assertRaises(PackageBuildError) as caught:
            build_execution_package(**kwargs)
        self.assertEqual(caught.exception.reason_taxonomy, "PACKAGE_REVISION_LINEAGE_INVALID")

    def test_preflight_rejects_non_authoritative_previous_package_digest(self) -> None:
        active = active_contract()
        pkg = build_execution_package(
            package_id="pkg-lineage",
            package_revision=2,
            previous_package_digest="forged-previous-digest",
            activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
            run_binding=run_binding(),
            active_contract=active,
            pre_execution_assessment_ref="assessment://pre/1",
            pre_execution_assessment=assessment(),
            runtime_selection={"mode": "mock"},
            exact_tool_authorization_projection=("READ",),
            security_policy_refs=("security://v1",),
            quality_policy_refs=("quality://migration/1",),
            codex_backed_worker=False,
            codex_auth_readiness=None,
        )
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                pkg,
                self.context(
                    pkg,
                    contract=active,
                    expected_package_revision=2,
                    expected_previous_package_digest="authoritative-previous-digest",
                ),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "PACKAGE_REVISION_LINEAGE_DRIFT")



    def test_package_seals_required_contract_projection_for_package_only_worker(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        self.assertEqual(pkg.purpose, active.purpose)
        self.assertIs(pkg.task_effect_policy, active.task_effect_policy)
        self.assertEqual(pkg.change_targets, active.change_targets)
        self.assertEqual(pkg.completion_criteria_ids, active.completion_criteria_ids)
        self.assertEqual(pkg.validation_criteria, active.validation_criteria)
        self.assertEqual(pkg.quality_criteria_contract_ref, active.quality_criteria_contract_ref)
        self.assertEqual(pkg.allowed_worker_terminal_states, active.allowed_worker_terminal_states)
        self.assertEqual(pkg.allowed_capabilities, active.allowed_capabilities)
        self.assertEqual(pkg.permission_requirements, active.permission_requirements)
        self.assertEqual(pkg.security_requirements, active.security_requirements)
        self.assertEqual(pkg.evidence_requirements, active.evidence_requirements)
        self.assertEqual(pkg.remediation_policy_ref, active.remediation_policy_ref)
        self.assertEqual(dict(pkg.source_digests), dict(active.source_digests))
        self.assertEqual(pkg.approval_refs, active.approval_refs)

    def test_package_contract_projection_tamper_fails_preflight(self) -> None:
        active = active_contract()
        pkg = package(contract=active)
        tampered = replace(pkg, remediation_policy_ref="remediation://forged")
        # Re-seal the forged package to prove Preflight checks semantic projection
        # against ACTIVE Contract, not only the package's self-digest.
        from runtime.orchestrator.execution_contract import _digest
        tampered = replace(tampered, package_digest=_digest(tampered.canonical_projection()))
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                tampered,
                self.context(tampered, contract=active),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "PACKAGE_CONTRACT_PROJECTION_DRIFT")


class CodexAuthReadinessTests(unittest.TestCase):
    def test_codex_001_current_secret_free_readiness_is_accepted(self) -> None:
        active = active_contract()
        rb = run_binding()
        auth = auth_evidence(rb)
        pkg = package(contract=active, rb=rb, auth=auth, codex=True)
        result = preflight_execution_package(pkg, PackageTests().context(pkg, contract=active, rb=rb, auth=auth))
        self.assertTrue(result.ready)

    def test_codex_002_missing_or_non_ready_evidence_blocks(self) -> None:
        active = active_contract()
        rb = run_binding()
        with self.assertRaises(PackageBuildError):
            package(contract=active, rb=rb, auth=None, codex=True)
        bad = auth_evidence(rb, status="NOT_READY")
        with self.assertRaises(PackageBuildError):
            package(contract=active, rb=rb, auth=bad, codex=True)

    def test_codex_003_cli_environment_or_schema_drift_blocks(self) -> None:
        active = active_contract()
        rb = run_binding()
        auth = auth_evidence(rb)
        pkg = package(contract=active, rb=rb, auth=auth, codex=True)
        for key, value in (
            ("expected_cli_version", "0.999.0"),
            ("expected_environment_fingerprint", "env-B"),
            ("expected_transport_schema_digest", "schema-B"),
        ):
            kwargs = dict(
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                run_binding=rb,
                active_contract=active,
                current_pre_execution_assessment_ref="assessment://pre/1",
                current_pre_execution_assessment=assessment(),
                current_codex_auth_readiness=auth,
                current_exact_tool_authorization_projection=pkg.exact_tool_authorization_projection,
                current_codex_backed_worker=True,
                expected_package_revision=pkg.package_revision,
                expected_previous_package_digest=pkg.previous_package_digest,
                current_approval_context=approval(),
                current_security_policy_refs=pkg.security_policy_refs,
                current_resume_cursor=pkg.resume_cursor,
                current_checkpoint_refs=pkg.checkpoint_refs,
                current_effect_refs=pkg.effect_refs,
                expected_cli_version="0.150.1",
                expected_environment_fingerprint="env-A",
                expected_transport_schema_digest="schema-A",
            )
            kwargs[key] = value
            with self.subTest(key=key):
                with self.assertRaises(PreflightBlocked):
                    preflight_execution_package(pkg, PreflightContext(**kwargs))

    def test_codex_004_secret_like_material_is_rejected(self) -> None:
        rb = run_binding()
        with self.assertRaises(GovernedContractError) as caught:
            CodexAuthReadinessEvidence(
                evidence_id="auth-ready-1",
                verified_at_utc=datetime.now(timezone.utc).isoformat(),
                cli_version="0.150.1",
                environment_fingerprint="env-A",
                transport_schema_digest="schema-A",
                auth_status=READY,
                source_evidence_refs=("token=super-secret-value",),
                recheck_policy=ALWAYS_BEFORE_CODEX_LAUNCH,
                launch_binding_digest=codex_launch_binding_digest(
                    cli_version="0.150.1",
                    environment_fingerprint="env-A",
                    transport_schema_digest="schema-A",
                    run_id=rb.run_id,
                    worker_task_id=rb.worker_task_id,
                    package_id="pkg-1",
                    package_revision=1,
                ),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "AUTH_EVIDENCE_SECRET_MATERIAL")

    def test_codex_backed_identity_is_sealed_and_preflight_revalidated(self) -> None:
        active = active_contract()
        rb = run_binding()
        non_codex = package(contract=active, rb=rb, codex=False)
        self.assertFalse(non_codex.codex_backed_worker)
        with self.assertRaises(PreflightBlocked) as caught:
            preflight_execution_package(
                non_codex,
                PackageTests().context(
                    non_codex,
                    contract=active,
                    rb=rb,
                    codex_backed_worker=True,
                ),
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_BACKEND_BINDING_DRIFT")

    def test_codex_readiness_cannot_be_reused_for_new_package_revision(self) -> None:
        active = active_contract()
        rb = run_binding()
        first_auth = auth_evidence(rb, package_id="pkg-1", package_revision=1)
        first = package(contract=active, rb=rb, auth=first_auth, codex=True)
        with self.assertRaises(PackageBuildError) as caught:
            build_execution_package(
                package_id="pkg-1",
                package_revision=2,
                previous_package_digest=first.package_digest,
                activation_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                run_binding=rb,
                active_contract=active,
                pre_execution_assessment_ref="assessment://pre/1",
                pre_execution_assessment=assessment(),
                runtime_selection={"mode": "codex-cli", "worker": "worker-001"},
                exact_tool_authorization_projection=("LIST", "READ", "WRITE"),
                security_policy_refs=("security://v1",),
                quality_policy_refs=("quality://migration/1",),
                codex_backed_worker=True,
                codex_auth_readiness=first_auth,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_AUTH_READINESS_STALE_OR_DRIFTED")

    def test_stale_launch_binding_cannot_be_reused_for_new_run(self) -> None:
        active = active_contract()
        rb = run_binding()
        auth = auth_evidence(rb)
        new_rb = replace(rb, run_id="run-002")
        with self.assertRaises(PackageBuildError):
            package(contract=active, rb=new_rb, auth=auth, codex=True)


if __name__ == "__main__":
    unittest.main()

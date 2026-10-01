from __future__ import annotations

import importlib
import importlib.util
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.dangerous_work_package import DangerousWorkPackageV1


MODULE_NAME = "runtime.orchestrator.dangerous_work_authorization"
AUTH_MODULE_AVAILABLE = importlib.util.find_spec(MODULE_NAME) is not None
auth_mod = importlib.import_module(MODULE_NAME) if AUTH_MODULE_AVAILABLE else None
UTC = timezone.utc


def package(*, lifecycle: bool = False) -> DangerousWorkPackageV1:
    if lifecycle:
        return DangerousWorkPackageV1.from_mapping({
            "schema_version": "orchestration.dangerous-work-package.v1",
            "project_id": "ocp-lifecycle-v2",
            "run_id": "RUN-P5-P6-01",
            "plan_digest": "a" * 64,
            "source_head": "b" * 40,
            "target_ref": "refs/heads/main",
            "operations": ["P5_PREDECESSOR_QUIESCE", "P6_PREDECESSOR_RETIREMENT"],
            "risk_classes": ["control-plane-retirement"],
            "precondition_evidence": ["P4_COMPLETE", "SUCCESSOR_QUALIFIED"],
            "required_post_verifiers": ["SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"],
            "recovery_refs": ["rollback://ocp/predecessor"],
            "created_at": "2026-10-01T01:00:00+00:00",
            "expires_at": "2026-10-01T02:00:00+00:00",
        })
    return DangerousWorkPackageV1.from_mapping({
        "schema_version": "orchestration.dangerous-work-package.v1",
        "project_id": "ai-office",
        "run_id": "RUN-20261001-01",
        "plan_digest": "a" * 64,
        "source_head": "b" * 40,
        "target_ref": "refs/heads/main",
        "operations": ["PR_MERGE", "RUNTIME_CURRENT_SWITCH", "SERVICE_RESTART"],
        "risk_classes": ["release", "runtime"],
        "precondition_evidence": ["CI_GREEN", "RELEASE_QUALIFIED"],
        "required_post_verifiers": ["POST_ACTIVATION_HEALTH"],
        "recovery_refs": ["rollback://ai-office/release-v1"],
        "created_at": "2026-10-01T01:00:00+00:00",
        "expires_at": "2026-10-01T02:00:00+00:00",
    })


def approval(pkg: DangerousWorkPackageV1, **overrides):
    raw = {
        "schema_version": "orchestration.dangerous-work-approval.v1",
        "approval_ref": "approval://two-action/RUN-20261001-01",
        "project_id": pkg.project_id,
        "run_id": pkg.run_id,
        "package_digest": pkg.package_digest,
        "issued_at": "2026-10-01T01:05:00+00:00",
        "expires_at": "2026-10-01T01:55:00+00:00",
        "issuer_identity": "oauth:user-owner",
        "approval_evidence_digest": "c" * 64,
    }
    raw.update(overrides)
    return raw


class DangerousWorkAuthorizationTests(unittest.TestCase):
    def require_module(self):
        self.assertTrue(AUTH_MODULE_AVAILABLE, "dangerous_work_authorization module must exist")
        return auth_mod

    def test_approval_contract_exists_and_binds_exact_package_digest(self) -> None:
        mod = self.require_module()
        pkg = package()
        good = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg))
        self.assertEqual(good.package_digest, pkg.package_digest)
        bad = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg, package_digest="d" * 64))
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.approval_coverage_for_package(pkg, bad, now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC))

    def test_project_run_mismatch_and_expired_approval_fail_closed(self) -> None:
        mod = self.require_module()
        pkg = package()
        mismatched = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg, run_id="OTHER-RUN"))
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.approval_coverage_for_package(pkg, mismatched, now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC))
        expired = mod.DangerousWorkApprovalV1.from_mapping(approval(
            pkg, issued_at="2026-10-01T00:30:00+00:00", expires_at="2026-10-01T00:59:00+00:00"
        ))
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.approval_coverage_for_package(pkg, expired, now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC))

    def test_coverage_is_derived_only_from_sealed_package(self) -> None:
        mod = self.require_module()
        pkg = package()
        apr = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg))
        coverage = mod.approval_coverage_for_package(pkg, apr, now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC))
        self.assertEqual(set(coverage.allowed_operations), set(pkg.operations))
        self.assertEqual(set(coverage.allowed_risk_classes), set(pkg.risk_classes))
        self.assertEqual(coverage.approved_semantic_digest, pkg.package_digest)
        self.assertEqual(coverage.reviewed_semantic_digest, pkg.package_digest)

    def test_operation_outside_package_source_drift_and_target_drift_are_rejected(self) -> None:
        mod = self.require_module()
        pkg = package()
        apr = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg))
        common = dict(
            package=pkg, approval=apr, requested_risk_class="release",
            now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC),
            satisfied_preconditions={"CI_GREEN", "RELEASE_QUALIFIED"},
            post_verifier_results={}, effect_reconciliation="NO_EFFECT",
        )
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(requested_operation="TAG_RELEASE", **common)
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                requested_operation="PR_MERGE", current_source_head="e" * 40, **common
            )
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                requested_operation="PR_MERGE", current_target_ref="refs/heads/other", **common
            )

    def test_missing_precondition_and_ambiguous_reexecution_are_rejected(self) -> None:
        mod = self.require_module()
        pkg = package()
        apr = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg))
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                package=pkg, approval=apr, requested_operation="PR_MERGE", requested_risk_class="release",
                now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC), satisfied_preconditions={"CI_GREEN"},
                post_verifier_results={}, effect_reconciliation="NO_EFFECT",
            )
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                package=pkg, approval=apr, requested_operation="PR_MERGE", requested_risk_class="release",
                now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC),
                satisfied_preconditions={"CI_GREEN", "RELEASE_QUALIFIED"}, post_verifier_results={},
                dangerous_reexecution=True, effect_reconciliation="UNKNOWN",
            )

    def test_p6_requires_execution_time_post_p5_health_pass(self) -> None:
        mod = self.require_module()
        pkg = package(lifecycle=True)
        apr = mod.DangerousWorkApprovalV1.from_mapping(approval(pkg))
        common = dict(
            package=pkg, approval=apr, requested_risk_class="control-plane-retirement",
            now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC),
            satisfied_preconditions={"P4_COMPLETE", "SUCCESSOR_QUALIFIED"}, effect_reconciliation="NO_EFFECT",
        )
        p5 = mod.authorize_protected_operation(
            requested_operation="P5_PREDECESSOR_QUIESCE", post_verifier_results={}, **common
        )
        self.assertTrue(p5.allowed)
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                requested_operation="P6_PREDECESSOR_RETIREMENT", post_verifier_results={}, **common
            )
        with self.assertRaises(mod.DangerousWorkAuthorizationError):
            mod.authorize_protected_operation(
                requested_operation="P6_PREDECESSOR_RETIREMENT",
                post_verifier_results={"SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE": "FAIL"}, **common
            )
        p6 = mod.authorize_protected_operation(
            requested_operation="P6_PREDECESSOR_RETIREMENT",
            post_verifier_results={"SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE": "PASS"}, **common
        )
        self.assertTrue(p6.allowed)


if __name__ == "__main__":
    unittest.main()

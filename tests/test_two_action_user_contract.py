from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.dangerous_work_authorization import (
    DangerousWorkApprovalV1,
    DangerousWorkAuthorizationError,
    approval_coverage_for_package,
)
from runtime.orchestrator.dangerous_work_package import DangerousWorkPackageV1
import runtime.orchestrator.user_interaction_policy as user_policy


UTC = timezone.utc


def package() -> DangerousWorkPackageV1:
    return DangerousWorkPackageV1.from_mapping({
        "schema_version": "orchestration.dangerous-work-package.v1",
        "project_id": "ai-office",
        "run_id": "RUN-2ACTION-01",
        "plan_digest": "a" * 64,
        "source_head": "b" * 40,
        "target_ref": "refs/heads/main",
        "operations": ["PR_MERGE", "RUNTIME_CURRENT_SWITCH", "SERVICE_RESTART"],
        "risk_classes": ["release", "runtime"],
        "precondition_evidence": ["CI_GREEN"],
        "required_post_verifiers": ["POST_ACTIVATION_HEALTH"],
        "recovery_refs": ["rollback://ai-office/release"],
        "created_at": "2026-10-01T01:00:00+00:00",
        "expires_at": "2026-10-01T02:00:00+00:00",
    })


def approval(pkg: DangerousWorkPackageV1, *, issuer="oauth:user-owner") -> DangerousWorkApprovalV1:
    return DangerousWorkApprovalV1.from_mapping({
        "schema_version": "orchestration.dangerous-work-approval.v1",
        "approval_ref": "approval://two-action/RUN-2ACTION-01",
        "project_id": pkg.project_id,
        "run_id": pkg.run_id,
        "package_digest": pkg.package_digest,
        "issued_at": "2026-10-01T01:05:00+00:00",
        "expires_at": "2026-10-01T01:55:00+00:00",
        "issuer_identity": issuer,
        "approval_evidence_digest": "c" * 64,
    })


class TwoActionUserContractTests(unittest.TestCase):
    def test_operation_authority_boundary_is_explicit(self) -> None:
        self.assertTrue(hasattr(user_policy, "classify_operation_authority"))
        self.assertEqual(
            user_policy.classify_operation_authority("FEATURE_BRANCH_PUSH"),
            "IMPLEMENTATION_APPROVAL",
        )
        for operation in (
            "PROTECTED_PUSH", "PR_MERGE", "TAG_RELEASE", "RUNTIME_CURRENT_SWITCH",
            "PRODUCTION_ACTIVATION", "SERVICE_RESTART", "BOUNDED_REBOOT",
            "P5_PREDECESSOR_QUIESCE", "P6_PREDECESSOR_RETIREMENT",
        ):
            self.assertEqual(
                user_policy.classify_operation_authority(operation),
                "DANGEROUS_WORK_APPROVAL",
            )

    def test_one_dangerous_approval_covers_every_operation_sealed_in_package(self) -> None:
        pkg = package()
        coverage = approval_coverage_for_package(
            pkg, approval(pkg), now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC)
        )
        for operation in pkg.operations:
            self.assertIn(operation, coverage.allowed_operations)
        self.assertNotIn("TAG_RELEASE", coverage.allowed_operations)

    def test_after_action_two_unsealed_operation_fails_closed_not_third_approval(self) -> None:
        pkg = package()
        coverage = approval_coverage_for_package(
            pkg, approval(pkg), now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC)
        )
        out = user_policy.evaluate_two_action_user_decision(
            approval_coverage=coverage,
            material_contract_change=False,
            requested_risk_class="release",
            requested_operation="TAG_RELEASE",
            dangerous_reexecution=False,
            final_dangerous_approval_granted=True,
        )
        self.assertEqual(out.action, "FAIL_CLOSED")
        self.assertEqual(out.decision_type, "RISK_ESCALATION")

    def test_github_app_identity_cannot_be_dangerous_user_approval(self) -> None:
        pkg = package()
        app_approval = approval(pkg, issuer="github-app:chatgpt")
        with self.assertRaises(DangerousWorkAuthorizationError):
            approval_coverage_for_package(
                pkg, app_approval, now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC)
            )

    def test_material_change_after_implementation_approval_fails_closed(self) -> None:
        pkg = package()
        coverage = approval_coverage_for_package(
            pkg, approval(pkg), now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC)
        )
        out = user_policy.evaluate_two_action_user_decision(
            approval_coverage=coverage,
            material_contract_change=True,
            requested_risk_class="release",
            requested_operation="PR_MERGE",
            dangerous_reexecution=False,
            final_dangerous_approval_granted=True,
        )
        self.assertEqual(out.action, "FAIL_CLOSED")
        self.assertNotEqual(out.action, "REQUEST_DANGEROUS_APPROVAL")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.dangerous_work_authorization import (
    DangerousWorkApprovalV1,
    DangerousWorkAuthorizationError,
    authorize_protected_operation,
)
from runtime.orchestrator.dangerous_work_package import DangerousWorkPackageV1
from runtime.orchestrator.user_interaction_policy import classify_operation_authority


UTC = timezone.utc
P5 = "P5_PREDECESSOR_QUIESCE"
P6 = "P6_PREDECESSOR_RETIREMENT"
POST_P5 = "SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"


def lifecycle_package() -> DangerousWorkPackageV1:
    return DangerousWorkPackageV1.from_mapping({
        "schema_version": "orchestration.dangerous-work-package.v1",
        "project_id": "ocp-lifecycle-v2",
        "run_id": "RUN-P5-P6-RETIREMENT",
        "plan_digest": "a" * 64,
        "source_head": "b" * 40,
        "target_ref": "refs/heads/main",
        "operations": [P5, P6],
        "risk_classes": ["control-plane-retirement"],
        "precondition_evidence": ["P4_COMPLETE", "SUCCESSOR_QUALIFIED", "ROLLBACK_READY"],
        "required_post_verifiers": [POST_P5],
        "recovery_refs": ["rollback://ocp/predecessor"],
        "created_at": "2026-10-01T01:00:00+00:00",
        "expires_at": "2026-10-01T02:00:00+00:00",
    })


def approval(pkg: DangerousWorkPackageV1) -> DangerousWorkApprovalV1:
    return DangerousWorkApprovalV1.from_mapping({
        "schema_version": "orchestration.dangerous-work-approval.v1",
        "approval_ref": "approval://two-action/RUN-P5-P6-RETIREMENT",
        "project_id": pkg.project_id,
        "run_id": pkg.run_id,
        "package_digest": pkg.package_digest,
        "issued_at": "2026-10-01T01:05:00+00:00",
        "expires_at": "2026-10-01T01:55:00+00:00",
        "issuer_identity": "oauth:user-owner",
        "approval_evidence_digest": "c" * 64,
    })


class P5P6RetirementAuthorityTests(unittest.TestCase):
    def test_p5_and_p6_remain_dangerous_work_authority(self) -> None:
        self.assertEqual(classify_operation_authority(P5), "DANGEROUS_WORK_APPROVAL")
        self.assertEqual(classify_operation_authority(P6), "DANGEROUS_WORK_APPROVAL")

    def test_p6_requires_recorded_p5_completion_even_after_health_verifier_passes(self) -> None:
        pkg = lifecycle_package()
        apr = approval(pkg)
        common = dict(
            package=pkg,
            approval=apr,
            requested_risk_class="control-plane-retirement",
            now=datetime(2026, 10, 1, 1, 10, tzinfo=UTC),
            satisfied_preconditions={"P4_COMPLETE", "SUCCESSOR_QUALIFIED", "ROLLBACK_READY"},
            effect_reconciliation="NO_EFFECT",
        )
        p5 = authorize_protected_operation(
            requested_operation=P5,
            post_verifier_results={},
            completed_operations=set(),
            **common,
        )
        self.assertTrue(p5.allowed)

        with self.assertRaises(DangerousWorkAuthorizationError):
            authorize_protected_operation(
                requested_operation=P6,
                post_verifier_results={POST_P5: "PASS"},
                completed_operations=set(),
                **common,
            )

        p6 = authorize_protected_operation(
            requested_operation=P6,
            post_verifier_results={POST_P5: "PASS"},
            completed_operations={P5},
            **common,
        )
        self.assertTrue(p6.allowed)

    def test_p5_p6_package_is_distinct_from_ai_office_release_rollback_domain(self) -> None:
        lifecycle = lifecycle_package()
        release = DangerousWorkPackageV1.from_mapping({
            "schema_version": "orchestration.dangerous-work-package.v1",
            "project_id": "ai-office",
            "run_id": "RUN-AI-OFFICE-RELEASE",
            "plan_digest": "a" * 64,
            "source_head": "b" * 40,
            "target_ref": "refs/heads/main",
            "operations": ["PR_MERGE", "RUNTIME_CURRENT_SWITCH"],
            "risk_classes": ["release"],
            "precondition_evidence": ["CI_GREEN"],
            "required_post_verifiers": ["POST_ACTIVATION_HEALTH"],
            "recovery_refs": ["rollback://ai-office/release"],
            "created_at": "2026-10-01T01:00:00+00:00",
            "expires_at": "2026-10-01T02:00:00+00:00",
        })
        self.assertNotEqual(lifecycle.project_id, release.project_id)
        self.assertNotEqual(lifecycle.package_digest, release.package_digest)


if __name__ == "__main__":
    unittest.main()

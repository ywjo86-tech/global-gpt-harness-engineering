from __future__ import annotations

import importlib
import importlib.util
import unittest


MODULE_NAME = "runtime.orchestrator.dangerous_work_package"
PACKAGE_MODULE_AVAILABLE = importlib.util.find_spec(MODULE_NAME) is not None
package_mod = importlib.import_module(MODULE_NAME) if PACKAGE_MODULE_AVAILABLE else None


def base_package(**overrides):
    raw = {
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
        "expires_at": "2026-10-01T01:30:00+00:00",
    }
    raw.update(overrides)
    return raw


class DangerousWorkPackageTests(unittest.TestCase):
    def require_module(self):
        self.assertTrue(PACKAGE_MODULE_AVAILABLE, "dangerous_work_package module must exist")
        return package_mod

    def test_module_contract_exists(self) -> None:
        mod = self.require_module()
        self.assertTrue(hasattr(mod, "DangerousWorkPackageV1"))

    def test_digest_is_canonical_and_deterministic(self) -> None:
        mod = self.require_module()
        one = mod.DangerousWorkPackageV1.from_mapping(base_package())
        reordered = dict(reversed(list(base_package().items())))
        two = mod.DangerousWorkPackageV1.from_mapping(reordered)
        self.assertEqual(one.package_digest, two.package_digest)
        self.assertEqual(len(one.package_digest), 64)

    def test_unknown_and_duplicate_operations_are_rejected(self) -> None:
        mod = self.require_module()
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(operations=["PR_MERGE", "ROOT_SHELL"]))
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(operations=["PR_MERGE", "PR_MERGE"]))

    def test_expiry_must_be_after_creation(self) -> None:
        mod = self.require_module()
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(
                created_at="2026-10-01T01:30:00+00:00",
                expires_at="2026-10-01T01:00:00+00:00",
            ))

    def test_p6_requires_p5_before_it(self) -> None:
        mod = self.require_module()
        verifier = ["SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"]
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(
                operations=["P6_PREDECESSOR_RETIREMENT"], required_post_verifiers=verifier,
            ))
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(
                operations=["P6_PREDECESSOR_RETIREMENT", "P5_PREDECESSOR_QUIESCE"],
                required_post_verifiers=verifier,
            ))

    def test_p6_requires_post_p5_successor_health_verifier(self) -> None:
        mod = self.require_module()
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(
                operations=["P5_PREDECESSOR_QUIESCE", "P6_PREDECESSOR_RETIREMENT"],
                required_post_verifiers=["POST_ACTIVATION_HEALTH"],
            ))
        valid = mod.DangerousWorkPackageV1.from_mapping(base_package(
            operations=["P5_PREDECESSOR_QUIESCE", "P6_PREDECESSOR_RETIREMENT"],
            required_post_verifiers=["SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"],
        ))
        self.assertIn("P6_PREDECESSOR_RETIREMENT", valid.operations)

    def test_lifecycle_retirement_operations_cannot_mix_with_release_operations(self) -> None:
        mod = self.require_module()
        with self.assertRaises(mod.DangerousWorkPackageError):
            mod.DangerousWorkPackageV1.from_mapping(base_package(
                project_id="ocp-lifecycle-v2",
                run_id="RUN-MIXED-DOMAIN",
                operations=[
                    "PR_MERGE",
                    "P5_PREDECESSOR_QUIESCE",
                    "P6_PREDECESSOR_RETIREMENT",
                ],
                risk_classes=["release", "control-plane-retirement"],
                required_post_verifiers=["SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"],
                recovery_refs=["rollback://ocp/predecessor"],
            ))

    def test_ai_office_release_and_p5_p6_retirement_are_separate_authority_packages(self) -> None:
        mod = self.require_module()
        release = mod.DangerousWorkPackageV1.from_mapping(base_package())
        lifecycle = mod.DangerousWorkPackageV1.from_mapping(base_package(
            project_id="ocp-lifecycle-v2",
            run_id="RUN-P5-P6-01",
            operations=["P5_PREDECESSOR_QUIESCE", "P6_PREDECESSOR_RETIREMENT"],
            risk_classes=["control-plane-retirement"],
            required_post_verifiers=["SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE"],
            recovery_refs=["rollback://ocp/predecessor"],
        ))
        self.assertNotEqual(release.package_digest, lifecycle.package_digest)
        self.assertNotEqual(release.project_id, lifecycle.project_id)


if __name__ == "__main__":
    unittest.main()

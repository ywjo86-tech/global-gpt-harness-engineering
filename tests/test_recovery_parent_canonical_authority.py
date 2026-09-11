from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.production_canonical_authority import (
    ProductionCanonicalAuthorityError,
    validate_recovery_parent_lv_authority,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_DECISION_REF,
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)

PROJECT = "wallet-affiliate-collector"
GATE = "G1"
LV = "LV3-5"
RUN = "run-recovery-parent"
PLAN = "1" * 64
OWNED = (
    "app/services/deduplicator.py",
    "tests/test_deduplicator.py",
)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def make_parent_manifest():
    approved = build_dec007_approved_contracts(
        project_id=PROJECT,
        gate_id=GATE,
        lv_id=LV,
        run_id=RUN,
        canonical_plan_sha256=PLAN,
        owned_files=OWNED,
    )
    package_binding = "3" * 64
    active = [
        activate_contract(
            item,
            package_binding_sha256=package_binding,
            authorized_decisions={DEC007_DECISION_REF: "USER_DECISION"},
        ).to_dict()
        for item in approved
    ]
    projection = {
        "decision_ref": DEC007_DECISION_REF,
        "worker_task_id": "TASK-4A-08",
        "active_contract_count": len(active),
        "contract_ids": sorted(item["contract_id"] for item in active),
        "operation_class_ids": sorted(item["operation_class_id"] for item in active),
        "owned_scope_sha256": owned_scope_digest(OWNED),
        "package_binding_sha256": package_binding,
        "requirement_digests": {
            item["operation_class_id"]: item["requirement_digest"]
            for item in active
        },
    }
    return {
        "project_id": PROJECT,
        "gate_id": GATE,
        "lv_id": LV,
        "run_id": RUN,
        "canonical_plan_sha256": PLAN,
        "task": {"purpose": "deduplicator", "execution": "implementation"},
        "owned_files": list(OWNED),
        "completion_checks": [
            "키 안정성·중복 제거 테스트 통과",
            "중복키 규칙 → 키·중복 제거 / 안정성 테스트",
        ],
        "active_tool_authorization_contracts": active,
        "tool_authorization_projection": projection,
        "tool_authorization_projection_sha256": digest(projection),
    }


def make_recovery():
    binding = {
        "project_id": PROJECT,
        "gate_id": GATE,
        "lv_id": LV,
        "run_id": RUN,
        "canonical_plan_sha256": PLAN,
        "approval_event_id": "approval-1",
        "active_transition_sha256": "4" * 64,
        "recovery_id": "recovery-1",
        "recovery_attempt": 2,
    }
    package = {
        "schema_version": "orchestration.recovery-package.v1",
        **binding,
        "branch": "task-orch-04-proof97-readiness",
        "baseline_head": "5" * 40,
        "current_head": "6" * 40,
    }
    package["package_sha256"] = digest(package)
    preflight = {
        "schema_version": "orchestration.recovery-preflight.v1",
        **binding,
        "package_sha256": package["package_sha256"],
        "status": "READY",
    }
    preflight["preflight_sha256"] = digest(preflight)
    return package, preflight


class RecoveryParentAuthorityTests(unittest.TestCase):
    def _root(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        manifest = make_parent_manifest()
        raw = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        (root / "package.manifest.json").write_bytes(raw)
        (root / "package.manifest.sha256").write_text(
            hashlib.sha256(raw).hexdigest(),
            encoding="ascii",
        )
        return root

    def test_recovery_uses_original_sealed_lv_manifest_as_authority_source(self):
        package, preflight = make_recovery()
        value = validate_recovery_parent_lv_authority(
            parent_package_root=self._root(),
            recovery_package=package,
            recovery_preflight=preflight,
            project_id=PROJECT,
            gate_id=GATE,
            lv_id=LV,
            run_id=RUN,
            canonical_plan_sha256=PLAN,
        )
        self.assertEqual(
            value.parent_manifest["tool_authorization_projection"]["worker_task_id"],
            "TASK-4A-08",
        )
        self.assertEqual(value.recovery_package_sha256, package["package_sha256"])
        self.assertEqual(
            value.recovery_preflight_sha256,
            preflight["preflight_sha256"],
        )

    def test_parent_manifest_sidecar_tamper_blocks(self):
        root = self._root()
        (root / "package.manifest.sha256").write_text("0" * 64, encoding="ascii")
        package, preflight = make_recovery()
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            validate_recovery_parent_lv_authority(
                parent_package_root=root,
                recovery_package=package,
                recovery_preflight=preflight,
                project_id=PROJECT,
                gate_id=GATE,
                lv_id=LV,
                run_id=RUN,
                canonical_plan_sha256=PLAN,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_RECOVERY_PARENT_DIGEST_DRIFT",
        )

    def test_recovery_package_identity_drift_blocks(self):
        package, preflight = make_recovery()
        package["lv_id"] = "OTHER-LV"
        package["package_sha256"] = digest(
            {k: v for k, v in package.items() if k != "package_sha256"}
        )
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            validate_recovery_parent_lv_authority(
                parent_package_root=self._root(),
                recovery_package=package,
                recovery_preflight=preflight,
                project_id=PROJECT,
                gate_id=GATE,
                lv_id=LV,
                run_id=RUN,
                canonical_plan_sha256=PLAN,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_RECOVERY_IDENTITY_DRIFT",
        )

    def test_recovery_preflight_package_lineage_drift_blocks(self):
        package, preflight = make_recovery()
        preflight["package_sha256"] = "9" * 64
        preflight["preflight_sha256"] = digest(
            {k: v for k, v in preflight.items() if k != "preflight_sha256"}
        )
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            validate_recovery_parent_lv_authority(
                parent_package_root=self._root(),
                recovery_package=package,
                recovery_preflight=preflight,
                project_id=PROJECT,
                gate_id=GATE,
                lv_id=LV,
                run_id=RUN,
                canonical_plan_sha256=PLAN,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_RECOVERY_PREFLIGHT_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()

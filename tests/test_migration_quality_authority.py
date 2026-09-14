from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.migration_quality_authority import (
    APPROVED_FILE_SHA256,
    AMENDMENT_RELATIVE,
    POLICY_RELATIVE,
    SOURCE_MODE,
    PRE_QUALITY_REFERENCE_SATISFIED,
    MIGRATION_APPROVED_PLAN,
    FULL_ORCHESTRATION,
    MigrationQualityAuthorityError,
    build_approved_migration_quality_contract,
    load_approved_migration_quality_authority,
    validate_policy_semantics,
    validate_pre_post_quality_lineage,
)

ROOT = Path(__file__).resolve().parents[1]


class MigrationQualityAuthorityTests(unittest.TestCase):
    def _copied_root(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        for relative in APPROVED_FILE_SHA256:
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return temp, root

    def test_mig_007_missing_approved_amendment_blocks(self):
        temp, root = self._copied_root()
        self.addCleanup(temp.cleanup)
        (root / AMENDMENT_RELATIVE).unlink()
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            load_approved_migration_quality_authority(root)
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_APPROVAL_MISSING")

    def test_mig_008_exact_approved_policy_materializes_deterministically(self):
        authority = load_approved_migration_quality_authority(ROOT)
        kwargs = dict(
            authority=authority,
            activation_profile=MIGRATION_APPROVED_PLAN,
            contract_id="MQC-TASK-4A-08",
            contract_version="1",
            created_at_utc="2026-09-10T02:00:00Z",
        )
        first = build_approved_migration_quality_contract(**kwargs)
        second = build_approved_migration_quality_contract(**kwargs)
        self.assertEqual(first.contract_digest, second.contract_digest)
        self.assertEqual(first.source_mode, SOURCE_MODE)
        self.assertEqual(first.pre_quality_state, PRE_QUALITY_REFERENCE_SATISFIED)
        self.assertEqual([item.criterion_id for item in first.criteria], [f"MQC-{i:03d}" for i in range(1, 9)])
        self.assertTrue(first.contract_ref.endswith(first.contract_digest))

    def test_mig_009_policy_file_tamper_blocks(self):
        temp, root = self._copied_root()
        self.addCleanup(temp.cleanup)
        path = root / POLICY_RELATIVE
        value = json.loads(path.read_text(encoding="utf-8"))
        value["policy_version"] = "9.9"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            load_approved_migration_quality_authority(root)
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_APPROVAL_DRIFT")

    def test_mig_010_meaning_expansion_is_rejected(self):
        payload = json.loads((ROOT / POLICY_RELATIVE).read_text(encoding="utf-8"))
        payload["criteria"][0]["permission_refs"] = ["PERM-ADMIN"]
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            validate_policy_semantics(payload)
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_MEANING_EXPANSION")

    def test_mig_011_pre_post_lineage_drift_blocks(self):
        authority = load_approved_migration_quality_authority(ROOT)
        contract = build_approved_migration_quality_contract(
            authority=authority,
            activation_profile=MIGRATION_APPROVED_PLAN,
            contract_id="MQC-TASK-4A-08",
            contract_version="1",
            created_at_utc="2026-09-10T02:00:00Z",
        )
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            validate_pre_post_quality_lineage(
                contract,
                post_policy_digest=contract.policy_digest,
                post_criterion_set_digest="0" * 64,
                post_lineage_digest=contract.pre_post_lineage_digest,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_PRE_POST_LINEAGE_DRIFT")

    def test_mig_012_full_orchestration_is_prohibited(self):
        authority = load_approved_migration_quality_authority(ROOT)
        with self.assertRaises(MigrationQualityAuthorityError) as caught:
            build_approved_migration_quality_contract(
                authority=authority,
                activation_profile=FULL_ORCHESTRATION,
                contract_id="MQC-TASK-4A-08",
                contract_version="1",
                created_at_utc="2026-09-10T02:00:00Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_QUALITY_PROFILE_INVALID")

    def test_exact_approved_artifact_bytes_are_bound(self):
        for relative, expected in APPROVED_FILE_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from runtime.orchestrator.execution_contract import ActivationProfile
from runtime.orchestrator.migration_authority import (
    APPROVAL_RELATIVE,
    AUTHORITY_MANIFEST_RELATIVE,
    R4_1_SC_EVIDENCE_ONLY_SHA256,
    R4_SEMANTIC_SHA256,
    MigrationAuthorityError,
    load_migration_authority,
    validate_activation_profile,
    validate_migration_authority_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class MigrationAuthorityTests(unittest.TestCase):
    def _payload(self):
        return json.loads((ROOT / AUTHORITY_MANIFEST_RELATIVE).read_text(encoding="utf-8"))

    def _approval_bytes(self):
        return (ROOT / APPROVAL_RELATIVE).read_bytes()

    def _rehash(self, payload):
        import hashlib
        unsigned = {k: v for k, v in payload.items() if k != "manifest_digest"}
        raw = json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        payload["manifest_digest"] = hashlib.sha256(raw).hexdigest()
        return payload

    def test_mig_001_current_phase4a_profile_is_bound_to_migration(self):
        evidence = load_migration_authority(ROOT)
        self.assertIs(evidence.activation_profile, ActivationProfile.MIGRATION_APPROVED_PLAN)
        self.assertEqual(evidence.approval_context().approved_semantic_digest, R4_SEMANTIC_SHA256)

    def test_mig_002_approved_final_lineage_is_reference_satisfied_with_durable_refs(self):
        evidence = load_migration_authority(ROOT)
        self.assertEqual(
            evidence.preserved_lineage_refs,
            ("FINAL Requirement Baseline 1.0", "FINAL DP-2.0", "FINAL SC-1.0"),
        )
        context = evidence.approval_context()
        self.assertFalse(context.full_plan_approval_required)
        self.assertTrue(context.full_plan_approval_ref)
        self.assertEqual(context.approved_semantic_digest, context.reviewed_semantic_digest)

    def test_gate_authorization_cannot_be_substituted_for_plan_design_approval(self):
        payload = copy.deepcopy(self._payload())
        payload["approval_context_projection"]["gate_authorization_reused_as_full_plan_approval"] = True
        self._rehash(payload)
        with self.assertRaises(MigrationAuthorityError) as caught:
            validate_migration_authority_payload(payload, approval_bytes=self._approval_bytes())
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_APPROVAL_AUTHORITY_MIXED")

    def test_r4_1_sc_byte_digest_cannot_replace_preserved_semantic_authority(self):
        payload = copy.deepcopy(self._payload())
        payload["approval_context_projection"]["approved_semantic_digest"] = R4_1_SC_EVIDENCE_ONLY_SHA256
        payload["approval_context_projection"]["reviewed_semantic_digest"] = R4_1_SC_EVIDENCE_ONLY_SHA256
        payload["source_digests"]["semantic"] = R4_1_SC_EVIDENCE_ONLY_SHA256
        payload["canonical_authority_projection"]["semantic_digest"] = R4_1_SC_EVIDENCE_ONLY_SHA256
        self._rehash(payload)
        with self.assertRaises(MigrationAuthorityError) as caught:
            validate_migration_authority_payload(payload, approval_bytes=self._approval_bytes())
        self.assertIn(
            caught.exception.reason_taxonomy,
            {"MIGRATION_SOURCE_DIGEST_DRIFT", "MIGRATION_SEMANTIC_AUTHORITY_DRIFT"},
        )

    def test_manifest_tamper_fails_closed(self):
        payload = copy.deepcopy(self._payload())
        payload["decision"]["selection"] = "B"
        with self.assertRaises(MigrationAuthorityError) as caught:
            validate_migration_authority_payload(payload, approval_bytes=self._approval_bytes())
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_AUTHORITY_DIGEST_DRIFT")

    def test_architecture_projection_digests_are_not_implicit_run_bindings(self):
        evidence = load_migration_authority(ROOT)
        architecture = evidence.architecture_source_digests()
        self.assertEqual(architecture["semantic"], R4_SEMANTIC_SHA256)
        with self.assertRaises(MigrationAuthorityError) as caught:
            evidence.source_digests()
        self.assertEqual(caught.exception.reason_taxonomy, "RUN_SOURCE_BINDING_REQUIRED")

    def test_run_source_digests_use_gate_plan_and_requirement_with_frozen_semantic_authority(self):
        evidence = load_migration_authority(ROOT)
        plan = "1" * 64
        requirement = "2" * 64
        run_sources = evidence.run_source_digests(
            plan_digest=plan,
            requirement_digest=requirement,
        )
        self.assertEqual(
            dict(run_sources),
            {"plan": plan, "requirement": requirement, "semantic": R4_SEMANTIC_SHA256},
        )
        self.assertNotEqual(run_sources["plan"], evidence.plan_digest)
        self.assertNotEqual(run_sources["requirement"], evidence.requirement_digest)

    def test_run_source_digests_reject_missing_or_non_sha_bindings(self):
        evidence = load_migration_authority(ROOT)
        with self.assertRaises(MigrationAuthorityError) as caught:
            evidence.run_source_digests(plan_digest="", requirement_digest="2" * 64)
        self.assertEqual(caught.exception.reason_taxonomy, "RUN_SOURCE_BINDING_INVALID")
        with self.assertRaises(MigrationAuthorityError) as caught:
            evidence.run_source_digests(plan_digest="1" * 64, requirement_digest="not-a-sha")
        self.assertEqual(caught.exception.reason_taxonomy, "RUN_SOURCE_BINDING_INVALID")

    def test_mig_005_same_run_profile_switch_blocks(self):
        with self.assertRaises(MigrationAuthorityError) as caught:
            validate_activation_profile(
                ActivationProfile.FULL_ORCHESTRATION,
                existing_run_profile=ActivationProfile.MIGRATION_APPROVED_PLAN,
                new_run=False,
                full_orchestration_ready=False,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_PROFILE_SWITCH_PROHIBITED")

    def test_mig_006_new_run_after_full_orchestration_readiness_blocks_migration(self):
        with self.assertRaises(MigrationAuthorityError) as caught:
            validate_activation_profile(
                ActivationProfile.MIGRATION_APPROVED_PLAN,
                existing_run_profile=None,
                new_run=True,
                full_orchestration_ready=True,
            )
        self.assertEqual(caught.exception.reason_taxonomy, "MIGRATION_PROFILE_EXPIRED")


if __name__ == "__main__":
    unittest.main()

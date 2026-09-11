from __future__ import annotations

import json
import os
import stat
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.schemas import CandidateUseState
from runtime.orchestrator.skill_installer import MANIFEST_NAME, install_project_skill
from runtime.orchestrator.skill_use_authorization import (
    attest_installed_artifact, authorize_candidate_use, seal_project_use_approval,
    transition_used_asset, validate_authorization_ledger_handoff, verify_attestation_evidence,
    verify_use_authorization_evidence,
)
from tests import test_skill_installer as installer_fixtures


NOW = "2026-09-01T02:00:00Z"
PLAN_SHA = installer_fixtures.PLAN_SHA


class SkillUseAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = installer_fixtures.SkillInstallerTests("runTest")
        self.fx.setUp()
        self.request = self.fx.request()
        self.install = install_project_skill(self.request)
        self.destination = self.fx.root / "safe"

    def tearDown(self) -> None:
        self.fx.tearDown()

    def attest(self, request=None, install=None):
        return attest_installed_artifact(request or self.request, install or self.install, timestamp=NOW)

    def approval(self, attestation=None, **changes):
        attestation = attestation or self.attest()
        values = dict(project_id="project", gate_id="GATE-1", lv_id="LV-1",
            candidate_id="owner/repo@safe", canonical_plan_sha256=PLAN_SHA,
            install_approval_digest=self.fx.approval.approval_digest,
            attestation_digest=attestation.attestation_digest, status="ACTIVE",
            intent="project_skill_use", evidence_reference="approval/use.json")
        values.update(changes)
        return seal_project_use_approval(**values)

    def authorize(self, attestation=None, approval=True, request=None):
        attestation = attestation or self.attest(request=request)
        use_approval = self.approval(attestation) if approval is True else approval
        return authorize_candidate_use(request or self.request, self.install, attestation,
                                       use_approval, timestamp=NOW)

    def rewrite_manifest(self, change):
        path = self.destination / MANIFEST_NAME
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        path.chmod(0o600)

    def test_01_install_completed_does_not_authorize_use(self):
        self.assertEqual(self.install.install_status, "INSTALL_COMPLETED")
        result = authorize_candidate_use(self.request, self.install,
            attest_installed_artifact(self.request, replace(self.install, install_status="BLOCKED"), timestamp=NOW),
            None, timestamp=NOW)
        self.assertFalse(result.candidate_use_authorized)

    def test_02_valid_installed_fixture_attests(self):
        result = self.attest()
        self.assertEqual(result.state, CandidateUseState.ATTESTED)
        self.assertTrue(verify_attestation_evidence(result.evidence))

    def test_03_skill_md_mutation_blocks(self):
        (self.destination / "SKILL.md").write_text("tampered")
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_04_manifest_mutation_blocks(self):
        self.rewrite_manifest(lambda value: value.update(repository="other/repo"))
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_05_aggregate_digest_mismatch_blocks(self):
        manifest = dict(self.install.installed_file_manifest)
        manifest["aggregate_digest"] = "0" * 64
        self.assertEqual(self.attest(install=replace(self.install, installed_file_manifest=manifest)).state,
                         CandidateUseState.BLOCKED)

    def test_06_unexpected_file_blocks(self):
        (self.destination / "extra.txt").write_text("extra")
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_07_missing_file_blocks(self):
        (self.destination / "SKILL.md").unlink()
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_08_mode_change_blocks(self):
        (self.destination / "SKILL.md").chmod(0o644)
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_09_symlink_replacement_blocks(self):
        skill = self.destination / "SKILL.md"
        outside = Path(self.fx.temp.name) / "outside.md"
        outside.write_text(skill.read_text())
        skill.unlink(); skill.symlink_to(outside)
        self.assertEqual(self.attest().state, CandidateUseState.BLOCKED)

    def test_10_project_binding_mismatch_blocks(self):
        self.assertEqual(self.attest(request=replace(self.request, project_id="other")).state,
                         CandidateUseState.BLOCKED)

    def test_11_gate_and_lv_mismatch_block(self):
        for field in ("gate_id", "lv_id"):
            with self.subTest(field=field):
                self.assertEqual(self.attest(request=replace(self.request, **{field: "OTHER"})).state,
                                 CandidateUseState.BLOCKED)

    def test_12_canonical_plan_mismatch_blocks(self):
        self.assertEqual(self.attest(request=replace(self.request, canonical_plan_sha256="0" * 64)).state,
                         CandidateUseState.BLOCKED)

    def test_13_resolver_evidence_mismatch_blocks(self):
        evidence = dict(self.fx.resolution.evidence); evidence["evidence_digest"] = "0" * 64
        request = replace(self.request, resolution=replace(self.fx.resolution, evidence=evidence))
        self.assertEqual(self.attest(request=request).state, CandidateUseState.BLOCKED)

    def test_14_evaluation_evidence_mismatch_blocks(self):
        evidence = dict(self.fx.evaluation.evidence); evidence["evidence_digest"] = "0" * 64
        request = replace(self.request, evaluation=replace(self.fx.evaluation, evidence=evidence))
        self.assertEqual(self.attest(request=request).state, CandidateUseState.BLOCKED)

    def test_15_supply_chain_evidence_mismatch_blocks(self):
        request = replace(self.request, review=replace(self.fx.review, review_digest="0" * 64))
        self.assertEqual(self.attest(request=request).state, CandidateUseState.BLOCKED)

    def test_16_install_approval_mismatch_blocks(self):
        request = replace(self.request, approval=replace(self.fx.approval, approval_digest="0" * 64))
        self.assertEqual(self.attest(request=request).state, CandidateUseState.BLOCKED)

    def test_17_valid_attestation_and_separate_approval_authorizes(self):
        result = self.authorize()
        self.assertEqual(result.use_authorization_status, "USE_AUTHORIZED")

    def test_18_authorized_sets_candidate_flag(self):
        self.assertTrue(self.authorize().candidate_use_authorized)

    def test_19_used_assets_rejects_before_authorization(self):
        with self.assertRaises(ValueError):
            transition_used_asset({}, self.request, self.install,
                                  self.authorize(approval=None), timestamp=NOW)

    def test_20_used_assets_accepts_only_stable_binding(self):
        ledger = {"used_assets": []}
        authorization = self.authorize()
        result = transition_used_asset(ledger, self.request, self.install, authorization, timestamp=NOW)
        self.assertEqual(ledger["used_assets"], [result["stable_asset_identifier"]])
        self.assertTrue(ledger["used_assets"][0].startswith("installed-skill:sha256:"))
        self.assertNotIn("owner/repo@safe", ledger["used_assets"])
        handoff = dict(ledger)
        validate_authorization_ledger_handoff(ledger, handoff, authorization)
        handoff["use_authorized_candidates"] = ["other"]
        with self.assertRaises(ValueError):
            validate_authorization_ledger_handoff(ledger, handoff, authorization)
        unauthorized = dict(ledger)
        unauthorized["used_assets"] = [*ledger["used_assets"], "installed-skill:sha256:" + "0" * 64]
        unauthorized["use_authorized_candidates"] = [*ledger["use_authorized_candidates"], "other"]
        unauthorized["use_authorization_evidence_references"] = [
            *ledger["use_authorization_evidence_references"], "sha256:" + "0" * 64]
        with self.assertRaises(ValueError):
            validate_authorization_ledger_handoff(unauthorized, unauthorized, authorization)

    def test_21_used_assets_does_not_pass_gate(self):
        ledger = {"used_assets": [], "gate_passed": False}
        result = transition_used_asset(ledger, self.request, self.install, self.authorize(), timestamp=NOW)
        self.assertFalse(result["gate_passed"]); self.assertFalse(ledger["gate_passed"])
        malformed = {"used_assets": [], "gate_passed": "false"}
        with self.assertRaises(ValueError):
            transition_used_asset(malformed, self.request, self.install, self.authorize(), timestamp=NOW)
        self.assertEqual(malformed, {"used_assets": [], "gate_passed": "false"})

    def test_22_time_of_use_mutation_blocks(self):
        attestation = self.attest(); approval = self.approval(attestation)
        (self.destination / "SKILL.md").write_text("post-attestation mutation")
        result = authorize_candidate_use(self.request, self.install, attestation, approval, timestamp=NOW)
        self.assertFalse(result.candidate_use_authorized)

    def test_23_global_target_escalates(self):
        plan = replace(self.fx.plan, target_scope="global", proposed_install_location="~/.agents/skills/safe", plan_digest="")
        plan = replace(plan, plan_digest=plan.expected_digest())
        result = self.attest(request=replace(self.request, install_plan=plan))
        self.assertEqual(result.state, CandidateUseState.ESCALATION_REQUIRED)

    def test_24_authorization_evidence_tamper_fails_closed(self):
        authorization = self.authorize()
        evidence = dict(authorization.authorization_evidence); evidence["gate_passed"] = True
        tampered = replace(authorization, authorization_evidence=evidence)
        self.assertFalse(verify_use_authorization_evidence(evidence))
        with self.assertRaises(ValueError):
            transition_used_asset({}, self.request, self.install, tampered, timestamp=NOW)
        forged_fields = replace(authorization, stable_asset_identifier="raw-discovery-candidate",
                                authorization_evidence_reference="unsealed-ref")
        ledger = {"used_assets": []}
        with self.assertRaises(ValueError):
            transition_used_asset(ledger, self.request, self.install, forged_fields, timestamp=NOW)
        self.assertEqual(ledger, {"used_assets": []})

    def test_25_no_skill_execution_network_or_subprocess(self):
        with patch("subprocess.run", side_effect=AssertionError), \
             patch("subprocess.Popen", side_effect=AssertionError), \
             patch("urllib.request.urlopen", side_effect=AssertionError), \
             patch.object(os, "system", side_effect=AssertionError):
            result = self.authorize()
        self.assertTrue(result.candidate_use_authorized)
        self.assertTrue(result.authorization_evidence["ready_for_runtime_selection"])


if __name__ == "__main__":
    unittest.main()

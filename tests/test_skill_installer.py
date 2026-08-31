from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.candidate_content_resolver import (RESOLUTION_CONTRACT,
    CandidateContentResolutionResult)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.schemas import (CandidateAdoptionState, CandidateEvaluationState,
    CandidateRisk, CapabilityRequirement, DiscoveryStatus)
from runtime.orchestrator.skill_adoption import (CandidateAdoptionDecision, seal_install_plan,
    seal_project_install_approval, seal_supply_chain_review)
from runtime.orchestrator.skill_candidate_evaluator import CandidateEvaluationResult
from runtime.orchestrator.skill_installer import (MANIFEST_NAME, SkillInstallRequest,
    install_project_skill, verify_installed_manifest)


SKILL = "---\nname: safe\ndescription: fixture\n---\nRead tests.\n"
PLAN_SHA = "a" * 64


class SkillInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.root = self.project / ".agents" / "skills"
        self.root.mkdir(parents=True)
        self.digest = hashlib.sha256(SKILL.encode()).hexdigest()
        resolution = {"schema_version": RESOLUTION_CONTRACT, "candidate_id": "owner/repo@safe",
            "source": "fixture", "repository": "owner/repo", "owner": "owner", "provider": "fixture",
            "source_url": "file:///fixture", "immutable_revision": "b"*40, "candidate_path": "skills/safe",
            "skill_md_relative_path": "skills/safe/SKILL.md", "skill_md_digest": self.digest,
            "source_evidence_reference": "fixture:index", "source_evidence_digest": "c"*64,
            "project_id": "project", "gate_id": "GATE-1", "lv_id": "LV-1",
            "timestamp": "2026-09-01T00:00:00Z", "provenance_state": "VERIFIED",
            "install_authorized": False, "candidate_use_authorized": False, "gate_passed": False}
        resolution["evidence_digest"] = hashlib.sha256(canonical_json_bytes(resolution)).hexdigest()
        self.resolution = CandidateContentResolutionResult(DiscoveryStatus.DISCOVERY_COMPLETED, "VERIFIED",
            {"owner":"owner","repository":"repo","provider":"fixture","source_url":"file:///fixture"},
            "b"*40, "skills/safe", SKILL, self.digest, {}, resolution,
            "sha256:"+resolution["evidence_digest"], "", "")
        evaluation = {"candidate_id":"owner/repo@safe", "project_id":"project", "gate_id":"GATE-1",
            "lv_id":"LV-1", "skill_md_digest":self.digest, "resolver_evidence_digest":resolution["evidence_digest"]}
        evaluation["evidence_digest"] = hashlib.sha256(canonical_json_bytes(evaluation)).hexdigest()
        self.evaluation = CandidateEvaluationResult(DiscoveryStatus.DISCOVERY_COMPLETED,
            CandidateEvaluationState.SAFE_FOR_CONSIDERATION, (), CandidateRisk(), (), (), (), "NO_EXACT_DUPLICATE",
            False, False, evaluation, "sha256:"+evaluation["evidence_digest"])
        self.review = seal_supply_chain_review(candidate_id="owner/repo@safe", source="fixture",
            repository="owner/repo", maintainer="owner", provider="fixture", immutable_revision="b"*40,
            candidate_path="skills/safe", skill_md_digest=self.digest,
            resolver_evidence_digest=resolution["evidence_digest"], license="MIT",
            package_install_required=False, shell_execution=False, network_required=False,
            secret_required=False, file_write_scope=("tests/",), install_scope="project",
            external_service=False, paid_service=False, deployment=False, destructive_action=False,
            requested_permissions=("read",), owned_file_scope=("tests/",), provenance_state="VERIFIED",
            evaluator_evidence_digest=evaluation["evidence_digest"], review_state="COMPLETE")
        self.plan = seal_install_plan(candidate_id="owner/repo@safe", target_project="project",
            target_scope="project", proposed_install_location=".agents/skills/safe", expected_source="fixture",
            expected_revision="b"*40, expected_files=("SKILL.md",), required_permissions=("read",),
            required_package_runtime=(), network_required=False, operation_type="PROJECT_FILE_MATERIALIZATION",
            rollback_expectation="remove owned files", evaluation_evidence_reference=self.evaluation.evidence_reference,
            supply_chain_evidence_reference="sha256:"+self.review.review_digest,
            approval_requirement="SEPARATE_PROJECT_INSTALL_APPROVAL", install_method_state="VERIFIED_FIXTURE_METHOD")
        self.approval = seal_project_install_approval(project_id="project", gate_id="GATE-1", lv_id="LV-1",
            intent="project_skill_install", candidate_id="owner/repo@safe",
            evaluation_digest=evaluation["evidence_digest"], supply_chain_review_digest=self.review.review_digest,
            install_scope="project", canonical_plan_sha256=PLAN_SHA, status="ACTIVE",
            evidence_reference="approval/install.json")
        req = CapabilityRequirement("python.testing", "GATE-1", "LV-1", ("read",), ("tests/",))
        self.decision = CandidateAdoptionDecision(req, "owner/repo@safe", self.evaluation.evidence_reference,
            CandidateEvaluationState.SAFE_FOR_CONSIDERATION.value, "VERIFIED_GAP",
            CandidateAdoptionState.INSTALL_AUTHORIZED, True, "project", True, False, "", "",
            self.approval.evidence_reference, "sha256:"+self.review.review_digest,
            "sha256:"+self.plan.plan_digest, "d"*64)

    def tearDown(self) -> None: self.temp.cleanup()

    def request(self, **changes):
        values = dict(decision=self.decision, evaluation=self.evaluation, resolution=self.resolution,
            review=self.review, approval=self.approval, install_plan=self.plan, project_id="project",
            gate_id="GATE-1", lv_id="LV-1", canonical_plan_sha256=PLAN_SHA,
            project_root=self.project, target_skill_root=self.root, timestamp="2026-09-01T01:00:00Z")
        values.update(changes); return SkillInstallRequest(**values)

    def test_01_not_authorized_executor_fails_before_attempt(self):
        d = replace(self.decision, adoption_state=CandidateAdoptionState.BLOCKED, install_authorized=False)
        result = install_project_skill(self.request(decision=d)); self.assertFalse(result.install_attempted)

    def test_02_unverified_target_blocks(self):
        other = self.project / "skills"; other.mkdir()
        self.assertEqual(install_project_skill(self.request(target_skill_root=other)).install_status, "BLOCKED")

    def test_03_outside_project_blocks(self):
        outside = Path(self.temp.name) / "outside"; outside.mkdir()
        self.assertEqual(install_project_skill(self.request(target_skill_root=outside)).install_status, "BLOCKED")

    def test_04_traversal_and_encoded_traversal_block(self):
        for path in (".agents/skills/../evil", ".agents/skills/%2e%2e"):
            plan = replace(self.plan, proposed_install_location=path, plan_digest="")
            plan = replace(plan, plan_digest=plan.expected_digest())
            with self.subTest(path=path): self.assertEqual(install_project_skill(self.request(install_plan=plan)).install_status, "BLOCKED")

    def test_05_symlink_escape_blocks(self):
        outside = Path(self.temp.name) / "outside"; outside.mkdir()
        (self.root / "safe").symlink_to(outside, target_is_directory=True)
        self.assertEqual(install_project_skill(self.request()).install_status, "BLOCKED")

    def test_06_valid_fixture_install(self):
        result = install_project_skill(self.request())
        self.assertEqual(result.install_status, "INSTALL_COMPLETED"); self.assertTrue((self.root/"safe"/"SKILL.md").is_file())
        self.assertEqual(result.installed_content_digest, self.resolution.skill_md_digest)

    def test_07_resolved_staged_mismatch_rolls_back(self):
        def hook(event, path):
            if event == "after_stage_write": (path/"SKILL.md").write_text("tampered")
        result = install_project_skill(self.request(), hook=hook)
        self.assertEqual(result.rollback_evidence["status"], "COMPLETE"); self.assertFalse((self.root/"safe").exists())

    def test_08_staged_installed_mismatch_rolls_back(self):
        def hook(event, path):
            if event == "after_promote": (path/"SKILL.md").write_text("tampered")
        result = install_project_skill(self.request(), hook=hook)
        self.assertEqual(result.rollback_evidence["status"], "COMPLETE"); self.assertFalse((self.root/"safe").exists())

    def test_09_skill_digest_mismatch_blocks(self):
        resolution = replace(self.resolution, skill_md_digest="0"*64)
        self.assertEqual(install_project_skill(self.request(resolution=resolution)).install_status, "BLOCKED")

    def test_10_partial_write_failure_rolls_back(self):
        def hook(event, path):
            if event == "after_stage_write": raise OSError("fixture write failure")
        result = install_project_skill(self.request(), hook=hook)
        self.assertEqual(result.rollback_evidence["status"], "COMPLETE")

    def test_11_identical_is_idempotent(self):
        install_project_skill(self.request()); result = install_project_skill(self.request())
        self.assertEqual(result.install_status, "IDENTICAL"); self.assertFalse(result.install_attempted)

    def test_12_different_does_not_overwrite(self):
        dest = self.root/"safe"; dest.mkdir(); (dest/"SKILL.md").write_text("different"); (dest/MANIFEST_NAME).write_text("{}")
        result = install_project_skill(self.request())
        self.assertEqual(result.install_status, "BLOCKED"); self.assertEqual((dest/"SKILL.md").read_text(), "different")

    def test_13_global_target_escalates(self):
        plan = replace(self.plan, target_scope="global", plan_digest=""); plan = replace(plan, plan_digest=plan.expected_digest())
        self.assertEqual(install_project_skill(self.request(install_plan=plan)).install_status, "ESCALATION_REQUIRED")

    def test_14_home_target_escalates(self):
        plan = replace(self.plan, proposed_install_location="~/.agents/skills/safe", plan_digest=""); plan=replace(plan, plan_digest=plan.expected_digest())
        self.assertEqual(install_project_skill(self.request(install_plan=plan)).install_status, "ESCALATION_REQUIRED")

    def test_15_16_17_success_does_not_authorize_use_assets_or_gate(self):
        result = install_project_skill(self.request())
        self.assertFalse(result.candidate_use_authorized); self.assertFalse(result.used_assets_changed); self.assertFalse(result.gate_passed)

    def test_18_manifest_digest_generated(self):
        result = install_project_skill(self.request())
        self.assertRegex(result.installation_evidence_digest, r"^[0-9a-f]{64}$"); self.assertTrue(verify_installed_manifest(result.installed_file_manifest, self.root/"safe"))

    def test_19_manifest_tamper_fails_closed(self):
        result = install_project_skill(self.request()); manifest = dict(result.installed_file_manifest); manifest["gate_passed"] = True
        self.assertFalse(verify_installed_manifest(manifest, self.root/"safe"))
        installed = self.root/"safe"/"SKILL.md"; installed.chmod(0o644)
        self.assertFalse(verify_installed_manifest(result.installed_file_manifest, self.root/"safe"))

    def test_20_approval_digest_mismatch_prevents_attempt(self):
        result=install_project_skill(self.request(approval=replace(self.approval, approval_digest="0"*64)))
        self.assertFalse(result.install_attempted)

    def test_21_plan_digest_mismatch_prevents_attempt(self):
        result=install_project_skill(self.request(install_plan=replace(self.plan, plan_digest="0"*64)))
        self.assertFalse(result.install_attempted)

    def test_22_resolver_provenance_mismatch_prevents_attempt(self):
        evidence=dict(self.resolution.evidence); evidence["repository"]="evil/repo"
        result=install_project_skill(self.request(resolution=replace(self.resolution, evidence=evidence)))
        self.assertFalse(result.install_attempted)

    def test_23_rollback_failure_escalates(self):
        def hook(event, path):
            if event == "after_stage_write": raise OSError("write failure")
            if event == "before_rollback": raise OSError("rollback failure")
        result=install_project_skill(self.request(), hook=hook)
        self.assertEqual(result.install_status, "ESCALATION_REQUIRED"); self.assertEqual(result.rollback_evidence["status"], "FAILED")

    def test_24_unsafe_permissions_block(self):
        for mode in (0o602, stat.S_ISUID | 0o600, stat.S_ISGID | 0o600):
            with self.subTest(mode=mode): self.assertEqual(install_project_skill(self.request(source_mode=mode)).install_status, "BLOCKED")

    def test_25_no_network_or_subprocess(self):
        with patch("subprocess.run", side_effect=AssertionError), patch("subprocess.Popen", side_effect=AssertionError), patch("urllib.request.urlopen", side_effect=AssertionError):
            self.assertEqual(install_project_skill(self.request()).install_status, "INSTALL_COMPLETED")


if __name__ == "__main__": unittest.main()

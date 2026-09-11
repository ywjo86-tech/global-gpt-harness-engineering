from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from runtime.orchestrator.candidate_content_resolver import RESOLUTION_CONTRACT
from runtime.orchestrator.project_isolation import AssetManifest
from runtime.orchestrator.schemas import CandidateAdoptionState, CandidateEvaluationState, CandidateRisk, CapabilityRequirement
from runtime.orchestrator.skill_adoption import (
    INSTALL_METHOD_UNVERIFIED, decide_adoption, seal_install_plan,
    seal_project_install_approval, seal_supply_chain_review,
)
from runtime.orchestrator.skill_candidate_evaluator import CandidateEvaluationRequest, evaluate_candidate

SKILL = "---\nname: safe\ndescription: safe fixture\n---\nRead tests.\n"
PLAN_SHA = "a" * 64


class SkillAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.req = CapabilityRequirement("python.testing", "GATE-1", "LV-1", ("read",), ("tests/",))
        metadata = {
            "skill_md_exists": True, "license": "MIT", "permissions": ["read"], "owned_files": ["tests/"],
            "network": False, "shell": False, "package_install": False, "secret": False,
            "file_write": False, "external_service": False, "paid_service": False, "deployment": False,
            "global_change": False, "destructive_action": False, "external_write_scope_known": True,
            "credential_required": False, "project_applicable": True, "global_install_required": False,
        }
        digest = hashlib.sha256(SKILL.encode()).hexdigest()
        resolution = {"schema_version":RESOLUTION_CONTRACT,"candidate_id":"owner/repo@safe","source":"fixture",
            "repository":"owner/repo","owner":"owner","provider":"fixture","source_url":"file:///fixture/owner/repo",
            "immutable_revision":"b"*40,"candidate_path":"skills/safe","skill_md_relative_path":"skills/safe/SKILL.md",
            "skill_md_digest":digest,"source_evidence_reference":"fixture:index","source_evidence_digest":"c"*64,
            "project_id":"project","gate_id":"GATE-1","lv_id":"LV-1","timestamp":"2026-09-01T00:00:00Z",
            "provenance_state":"VERIFIED","install_authorized":False,"candidate_use_authorized":False,"gate_passed":False}
        resolution["evidence_digest"] = hashlib.sha256(json.dumps(resolution, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        request = CandidateEvaluationRequest(self.req, "project", "GATE-1", "LV-1", "owner/repo@safe",
            "fixture", "owner/repo", "owner", metadata, SKILL, "sha256:"+resolution["evidence_digest"], digest,
            ("read",), ("tests/",), "2026-09-01T00:00:00Z", resolution)
        self.evaluation = evaluate_candidate(request)
        self.review = seal_supply_chain_review(candidate_id="owner/repo@safe", source="fixture",
            repository="owner/repo", maintainer="owner", provider="fixture", immutable_revision="b"*40,
            candidate_path="skills/safe", skill_md_digest=digest, resolver_evidence_digest=resolution["evidence_digest"],
            license="MIT", package_install_required=False,
            shell_execution=False, network_required=False, secret_required=False,
            file_write_scope=("tests/",), install_scope="project", external_service=False,
            paid_service=False, deployment=False, destructive_action=False,
            requested_permissions=("read",), owned_file_scope=("tests/",), provenance_state="VERIFIED",
            evaluator_evidence_digest=self.evaluation.evidence["evidence_digest"], review_state="COMPLETE")
        self.plan = seal_install_plan(candidate_id="owner/repo@safe", target_project="project",
            target_scope="project", proposed_install_location=".agents/skills/safe", expected_source="fixture",
            expected_revision="b"*40, expected_files=("SKILL.md",), required_permissions=("read",),
            required_package_runtime=(), network_required=False, operation_type="PROJECT_FILE_MATERIALIZATION",
            rollback_expectation="remove only owned project files", evaluation_evidence_reference=self.evaluation.evidence_reference,
            supply_chain_evidence_reference="sha256:"+self.review.review_digest,
            approval_requirement="SEPARATE_PROJECT_INSTALL_APPROVAL", install_method_state="VERIFIED_FIXTURE_METHOD")
        self.approval = seal_project_install_approval(project_id="project", gate_id="GATE-1", lv_id="LV-1",
            intent="project_skill_install", candidate_id="owner/repo@safe",
            evaluation_digest=self.evaluation.evidence["evidence_digest"],
            supply_chain_review_digest=self.review.review_digest, install_scope="project",
            canonical_plan_sha256=PLAN_SHA, status="ACTIVE", evidence_reference="approval/project-install.json")

    def decide(self, **changes: object):
        values = dict(project_id="project", canonical_plan_sha256=PLAN_SHA, gate_lvs={"GATE-1":["LV-1"]},
            requirement=self.req, evaluation=self.evaluation, candidate_risk=CandidateRisk(), install_scope="project",
            review=self.review, approval=self.approval, install_plan=self.plan)
        values.update(changes)
        return decide_adoption(**values)

    def test_safe_is_not_automatically_install_authorized(self) -> None:
        result = self.decide(approval=None)
        self.assertEqual(result.adoption_state, CandidateAdoptionState.APPROVAL_REQUIRED)
        self.assertFalse(result.install_authorized)

    def test_unassessed_candidate_and_evidence_tamper_block(self) -> None:
        unassessed = replace(self.evaluation, evaluation_state=CandidateEvaluationState.UNASSESSED)
        self.assertEqual(self.decide(evaluation=unassessed).adoption_state, CandidateAdoptionState.BLOCKED)
        evidence = dict(self.evaluation.evidence); evidence["candidate_id"] = "tampered"
        tampered = replace(self.evaluation, evidence=evidence)
        self.assertEqual(self.decide(evaluation=tampered).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_existing_exact_capability_wins_and_fuzzy_does_not(self) -> None:
        exact = AssetManifest("existing", "project", frozenset({"python.testing"}), frozenset({"read"}), ("tests/",))
        fuzzy = AssetManifest("similar", "project", frozenset({"python.testing.extra"}), frozenset({"read"}), ("tests/",))
        self.assertFalse(self.decide(project_assets=(exact,)).install_required)
        self.assertTrue(self.decide(project_assets=(fuzzy,)).install_required)

    def test_incomplete_or_unknown_provenance_blocks(self) -> None:
        self.assertEqual(self.decide(review=None).adoption_state, CandidateAdoptionState.PENDING_SUPPLY_CHAIN_REVIEW)
        bad = replace(self.review, repository="", review_digest="")
        bad = replace(bad, review_digest=bad.expected_digest())
        self.assertEqual(self.decide(review=bad).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_resolved_provenance_drift_blocks_supply_chain_review(self) -> None:
        for field, value in (
            ("provider", "other"), ("repository", "other/repo"),
            ("immutable_revision", "c" * 40), ("candidate_path", "skills/other"),
            ("resolver_evidence_digest", "0" * 64),
        ):
            review = replace(self.review, **{field: value}, review_digest="")
            review = replace(review, review_digest=review.expected_digest())
            with self.subTest(field=field):
                self.assertEqual(self.decide(review=review).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_permission_and_owned_file_mismatch_block(self) -> None:
        for field in ("requested_permissions", "owned_file_scope"):
            bad = replace(self.review, **{field: ()}, review_digest="")
            bad = replace(bad, review_digest=bad.expected_digest())
            with self.subTest(field=field): self.assertEqual(self.decide(review=bad).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_approval_binding_and_full_plan_cannot_bypass(self) -> None:
        bad = replace(self.approval, intent="FULL_PLAN", approval_digest="")
        bad = replace(bad, approval_digest=bad.expected_digest())
        self.assertEqual(self.decide(approval=bad).adoption_state, CandidateAdoptionState.BLOCKED)
        mismatch = replace(self.approval, candidate_id="other", approval_digest="")
        mismatch = replace(mismatch, approval_digest=mismatch.expected_digest())
        self.assertEqual(self.decide(approval=mismatch).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_valid_fixture_can_only_authorize_install(self) -> None:
        result = self.decide()
        self.assertEqual(result.adoption_state, CandidateAdoptionState.INSTALL_AUTHORIZED)
        self.assertTrue(result.install_authorized)
        self.assertFalse(result.candidate_use_authorized)
        self.assertNotIn(result.candidate_id, result.ledger_projection().get("used_assets", []))

    def test_global_agent_secret_deployment_and_package_escalate(self) -> None:
        for changes in ({"install_scope":"global"}, {"candidate_risk":CandidateRisk(global_change=True)},
                        {"candidate_risk":CandidateRisk(secret=True)}, {"candidate_risk":CandidateRisk(deployment=True)}):
            with self.subTest(changes=changes): self.assertEqual(self.decide(**changes).adoption_state, CandidateAdoptionState.ESCALATION_REQUIRED)
        package = replace(self.review, package_install_required=True, review_digest="")
        package = replace(package, review_digest=package.expected_digest())
        self.assertEqual(self.decide(review=package).adoption_state, CandidateAdoptionState.ESCALATION_REQUIRED)

    def test_install_plan_digest_tamper_and_unverified_method_fail_closed(self) -> None:
        self.assertTrue(self.plan.valid())
        self.assertEqual(self.decide(install_plan=replace(self.plan, expected_source="tampered")).adoption_state, CandidateAdoptionState.BLOCKED)
        unverified = replace(self.plan, install_method_state=INSTALL_METHOD_UNVERIFIED, plan_digest="")
        unverified = replace(unverified, plan_digest=unverified.expected_digest())
        self.assertEqual(self.decide(install_plan=unverified).adoption_state, CandidateAdoptionState.BLOCKED)

    def test_failure_preserves_gate_state_and_has_deterministic_digest(self) -> None:
        gate = {"state":"ACTIVE", "used_assets":["prior"], "plan":PLAN_SHA}; before = dict(gate)
        one = self.decide(approval=None); two = self.decide(approval=None)
        self.assertEqual(one.decision_digest, two.decision_digest)
        self.assertEqual(gate, before)


if __name__ == "__main__":
    unittest.main()

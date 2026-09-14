from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.candidate_content_resolver import (
    CandidateContentResolutionRequest,
    CandidateResolutionIntent,
    ResolutionTransportContract,
    resolve_candidate_content,
    verify_resolution_evidence,
)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.schemas import CandidateEvaluationState, CapabilityRequirement, DiscoveryStatus
from runtime.orchestrator.skill_adoption import seal_supply_chain_review
from runtime.orchestrator.skill_candidate_evaluator import CandidateEvaluationRequest, evaluate_candidate
from runtime.orchestrator.skill_discovery import RawDiscoveredCandidate


SKILL = b"---\nname: safe\ndescription: Safe fixture.\n---\nRead tests.\n"
DIGEST = hashlib.sha256(SKILL).hexdigest()


class CandidateContentResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        skill_dir = self.root / "skills" / "safe"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_bytes(SKILL)
        self.candidate = RawDiscoveredCandidate(
            "owner/repo@safe", "safe", "owner/repo@safe", "fixture-discovery", 1, "d" * 64,
        )
        self.intent = CandidateResolutionIntent(
            "project", "GATE-1", "LV-1", self.candidate.candidate_id,
            "read_only_candidate_content_resolution", "APPROVED",
        )
        source_binding = {
            "provider": "fixture", "owner": "owner", "repository": "repo",
            "source_url": "file:///fixture/owner/repo", "immutable_revision": "a" * 40,
            "candidate_path": "skills/safe", "source_evidence_reference": "fixture:index",
        }
        source_digest = hashlib.sha256(canonical_json_bytes(source_binding)).hexdigest()
        self.transport = ResolutionTransportContract(
            "LOCAL_FIXTURE", "fixture-discovery", "fixture", "owner", "repo",
            "file:///fixture/owner/repo", "a" * 40, "skills/safe", "fixture:index", source_digest,
            expected_skill_md_digest=DIGEST,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(self, **changes: object) -> CandidateContentResolutionRequest:
        values = dict(
            raw_candidate=self.candidate, source="fixture-discovery", candidate_id=self.candidate.candidate_id,
            project_id="project", gate_id="GATE-1", lv_id="LV-1", intent=self.intent,
            transport=self.transport, timestamp="2026-09-01T00:00:00Z",
        )
        values.update(changes)
        return CandidateContentResolutionRequest(**values)

    def resolve(self, **changes: object):
        return resolve_candidate_content(self.request(**changes), fixture_root=self.root)

    def bound_transport(self, **changes: object) -> ResolutionTransportContract:
        transport = replace(self.transport, **changes)
        binding = {
            "provider": transport.provider, "owner": transport.owner, "repository": transport.repository,
            "source_url": transport.source_url, "immutable_revision": transport.immutable_revision,
            "candidate_path": transport.candidate_path,
            "source_evidence_reference": transport.source_evidence_reference,
        }
        return replace(transport, source_evidence_digest=hashlib.sha256(canonical_json_bytes(binding)).hexdigest())

    # TEST 1, 17-20
    def test_resolution_never_authorizes_install_use_used_assets_or_gate(self) -> None:
        raw_only = self.candidate
        self.assertEqual(raw_only.evaluation_state, "UNASSESSED")
        result = self.resolve()
        self.assertFalse(result.install_authorized)
        self.assertFalse(result.candidate_use_authorized)
        self.assertFalse(result.gate_passed)
        self.assertNotIn("used_assets", result.ledger_projection())

    # TEST 2, 13
    def test_valid_fixture_has_immutable_verified_provenance(self) -> None:
        result = self.resolve()
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        self.assertEqual(result.provenance_state, "VERIFIED")
        self.assertEqual(result.repository_identity["owner"], "owner")
        self.assertEqual(result.immutable_revision, "a" * 40)
        self.assertEqual(result.skill_md_digest, DIGEST)
        self.assertTrue(verify_resolution_evidence(result.evidence))

    # TEST 3
    def test_unknown_repository_is_blocked(self) -> None:
        result = self.resolve(transport=replace(self.transport, repository="UNKNOWN"))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("repository UNKNOWN", result.blocked_reason)

    # TEST 4-5
    def test_unknown_or_mutable_revision_is_blocked(self) -> None:
        for revision in ("UNKNOWN", "main", "master"):
            with self.subTest(revision=revision):
                result = self.resolve(transport=replace(self.transport, immutable_revision=revision))
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertNotEqual(result.provenance_state, "VERIFIED")

    # TEST 6
    def test_missing_skill_md_is_blocked(self) -> None:
        result = self.resolve(transport=self.bound_transport(candidate_path="skills/missing"))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("SKILL.md missing", result.blocked_reason)

    # TEST 7
    def test_skill_md_digest_mismatch_is_blocked(self) -> None:
        result = self.resolve(transport=replace(self.transport, expected_skill_md_digest="0" * 64))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("digest mismatch", result.blocked_reason)

    # TEST 8
    def test_revision_binding_mismatch_fails_evaluator(self) -> None:
        resolved = self.resolve()
        evaluation = self._evaluate(resolved)
        evidence = dict(resolved.evidence)
        evidence["immutable_revision"] = "e" * 40
        result = self._evaluate(replace(resolved, evidence=evidence))
        self.assertEqual(evaluation.evaluation_state, CandidateEvaluationState.SAFE_FOR_CONSIDERATION)
        self.assertEqual(result.evaluation_state, CandidateEvaluationState.BLOCKED)

    # TEST 9
    def test_repository_binding_mismatch_is_blocked(self) -> None:
        github = self.bound_transport(provider="github", source_url="https://github.com/other/repo")
        result = self.resolve(transport=github)
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("source/repository mismatch", result.blocked_reason)

    # TEST 10-11 and encoded traversal
    def test_unsafe_candidate_paths_are_blocked(self) -> None:
        for path in ("../safe", "/skills/safe", "%2e%2e/safe", ""):
            with self.subTest(path=path):
                self.assertEqual(
                    self.resolve(transport=self.bound_transport(candidate_path=path)).status,
                    DiscoveryStatus.BLOCKED,
                )

    # TEST 12
    def test_symlink_escape_is_blocked(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        try:
            (outside / "SKILL.md").write_bytes(SKILL)
            (self.root / "skills" / "escape").symlink_to(outside, target_is_directory=True)
            result = self.resolve(transport=self.bound_transport(candidate_path="skills/escape"))
            self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
            self.assertIn("symlink", result.blocked_reason)
        finally:
            (outside / "SKILL.md").unlink()
            outside.rmdir()

    # TEST 14
    def test_resolver_evidence_tamper_is_blocked_by_verifier(self) -> None:
        evidence = dict(self.resolve().evidence)
        evidence["candidate_path"] = "skills/other"
        self.assertFalse(verify_resolution_evidence(evidence))

    # TEST 15
    def test_evaluator_is_bound_to_resolved_provenance(self) -> None:
        resolved = self.resolve()
        evaluation = self._evaluate(resolved)
        self.assertEqual(evaluation.evaluation_state, CandidateEvaluationState.SAFE_FOR_CONSIDERATION)
        self.assertEqual(evaluation.evidence["resolver_evidence_digest"], resolved.evidence["evidence_digest"])
        drifted = dict(resolved.evidence)
        drifted["skill_md_digest"] = "0" * 64
        self.assertEqual(self._evaluate(replace(resolved, evidence=drifted)).status, DiscoveryStatus.BLOCKED)

    # TEST 16
    def test_supply_chain_review_is_bound_to_resolved_provenance(self) -> None:
        resolved = self.resolve()
        evaluation = self._evaluate(resolved)
        review = seal_supply_chain_review(
            candidate_id=self.candidate.candidate_id, source="fixture-discovery", repository="owner/repo",
            maintainer="owner", provider="fixture", immutable_revision="a" * 40, candidate_path="skills/safe",
            skill_md_digest=DIGEST, resolver_evidence_digest=resolved.evidence["evidence_digest"], license="MIT",
            package_install_required=False, shell_execution=False, network_required=False, secret_required=False,
            file_write_scope=("tests/",), install_scope="project", external_service=False, paid_service=False,
            deployment=False, destructive_action=False, requested_permissions=("read",), owned_file_scope=("tests/",),
            provenance_state="VERIFIED", evaluator_evidence_digest=evaluation.evidence["evidence_digest"],
            review_state="COMPLETE",
        )
        self.assertTrue(review.valid())
        self.assertFalse(replace(review, resolver_evidence_digest="0" * 64).valid())

    # TEST 21
    def test_network_executor_is_never_called(self) -> None:
        calls: list[object] = []
        network = replace(self.transport, transport="NETWORK_READ_ONLY")
        result = resolve_candidate_content(
            self.request(transport=network), fixture_root=self.root,
            network_executor=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertEqual(calls, [])

    # TEST 22
    def test_private_authenticated_or_paid_source_requires_escalation(self) -> None:
        for field in ("private_repository", "authentication_required", "paid_service_required"):
            with self.subTest(field=field):
                result = self.resolve(transport=replace(self.transport, **{field: True}))
                self.assertEqual(result.status, DiscoveryStatus.ESCALATION_REQUIRED)

    def _evaluate(self, resolved):
        requirement = CapabilityRequirement("python.testing", "GATE-1", "LV-1", ("read",), ("tests/",))
        metadata = {
            "skill_md_exists": True, "license": "MIT", "permissions": ["read"], "owned_files": ["tests/"],
            "network": False, "shell": False, "package_install": False, "secret": False,
            "file_write": False, "external_service": False, "paid_service": False, "deployment": False,
            "global_change": False, "destructive_action": False, "external_write_scope_known": True,
            "credential_required": False, "project_applicable": True, "global_install_required": False,
        }
        return evaluate_candidate(CandidateEvaluationRequest(
            requirement, "project", "GATE-1", "LV-1", self.candidate.candidate_id, "fixture-discovery",
            "owner/repo", "owner", metadata, resolved.skill_md_content,
            f"sha256:{resolved.evidence.get('evidence_digest', '')}", resolved.skill_md_digest,
            ("read",), ("tests/",), "2026-09-01T00:00:00Z", resolved.evidence,
        ))


if __name__ == "__main__":
    unittest.main()

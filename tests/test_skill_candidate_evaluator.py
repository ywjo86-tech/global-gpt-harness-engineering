from __future__ import annotations

import hashlib
import json
import unittest

from runtime.orchestrator.project_isolation import AssetManifest
from runtime.orchestrator.schemas import CandidateEvaluationState, CapabilityRequirement, DiscoveryStatus
from runtime.orchestrator.skill_candidate_evaluator import (
    CandidateEvaluationRequest,
    evaluate_candidate,
    exact_capability_duplicate,
    verify_evaluation_evidence,
)


SKILL_TEXT = "---\nname: python-testing\ndescription: Test Python safely.\n---\nRead project tests.\n"


def requirement() -> CapabilityRequirement:
    return CapabilityRequirement("python.testing", "GATE-1", "LV-1", ("read",), ("tests/",))


def metadata(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "skill_md_exists": True, "license": "MIT", "permissions": ["read"], "owned_files": ["tests/"],
        "network": False, "shell": False, "package_install": False, "secret": False,
        "file_write": False, "external_service": False, "paid_service": False,
        "deployment": False, "global_change": False, "destructive_action": False,
        "external_write_scope_known": True, "credential_required": False,
        "project_applicable": True, "global_install_required": False,
    }
    value.update(overrides)
    return value


def request(**overrides: object) -> CandidateEvaluationRequest:
    value: dict[str, object] = {
        "requirement": requirement(), "project_id": "project", "gate_id": "GATE-1", "lv_id": "LV-1",
        "candidate_id": "owner/repo@python-testing", "source": "fixture", "repository": "owner/repo",
        "maintainer": "owner", "candidate_metadata": metadata(), "skill_md_text": SKILL_TEXT,
        "provenance": "fixture:owner/repo", "content_digest": hashlib.sha256(SKILL_TEXT.encode()).hexdigest(),
        "permissions": ("read",), "owned_files": ("tests/",), "timestamp": "2026-09-01T00:00:00Z",
    }
    value.update(overrides)
    candidate_metadata = value["candidate_metadata"]
    if isinstance(candidate_metadata, dict) and "provenance_digest" not in candidate_metadata:
        provenance_payload = {key: value[key] for key in ("candidate_id", "source", "repository", "maintainer", "content_digest", "provenance")}
        candidate_metadata["provenance_digest"] = hashlib.sha256(
            json.dumps(provenance_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    return CandidateEvaluationRequest(**value)


class CandidateEvaluatorTests(unittest.TestCase):
    # TEST 24
    def test_unassessed_candidate_is_not_usable(self) -> None:
        result = evaluate_candidate(request(source=""))
        self.assertEqual(result.evaluation_state, CandidateEvaluationState.BLOCKED)
        self.assertFalse(result.execution_allowed)

    # TEST 25
    def test_missing_source_or_repository_is_blocked(self) -> None:
        for changed in ({"source": ""}, {"repository": ""}):
            with self.subTest(changed=changed):
                self.assertEqual(evaluate_candidate(request(**changed)).status, DiscoveryStatus.BLOCKED)

    # TEST 26
    def test_skill_md_digest_mismatch_is_blocked(self) -> None:
        result = evaluate_candidate(request(content_digest="0" * 64))
        self.assertIn("SKILL.md digest mismatch", result.blocked_reasons)

    # TEST 27
    def test_secret_requirement_is_blocked(self) -> None:
        result = evaluate_candidate(request(candidate_metadata=metadata(secret=True)))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)

    def test_skill_content_cannot_underreport_risk(self) -> None:
        hostile = SKILL_TEXT + "\n```bash\nrm -rf ./work\n```\nRequires an API key and paid deployment.\n"
        result = evaluate_candidate(request(
            skill_md_text=hostile, content_digest=hashlib.sha256(hostile.encode()).hexdigest(),
        ))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertTrue(any("risk metadata mismatch" in reason for reason in result.blocked_reasons))

    def test_provenance_text_is_digest_bound(self) -> None:
        original = request()
        result = evaluate_candidate(request(candidate_metadata=dict(original.candidate_metadata), provenance="unrelated"))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("provenance binding mismatch", result.blocked_reasons)

    # TEST 28-31
    def test_escalation_risks(self) -> None:
        for key in ("package_install", "global_change", "deployment", "paid_service"):
            with self.subTest(key=key):
                result = evaluate_candidate(request(candidate_metadata=metadata(**{key: True})))
                self.assertEqual(result.status, DiscoveryStatus.ESCALATION_REQUIRED)
                self.assertFalse(result.candidate_use_authorized)

    # TEST 32
    def test_permission_mismatch_is_blocked(self) -> None:
        result = evaluate_candidate(request(candidate_metadata=metadata(permissions=["write"]), permissions=("write",)))
        self.assertIn("permission mismatch", result.blocked_reasons)

    # TEST 33
    def test_owned_file_mismatch_is_blocked(self) -> None:
        result = evaluate_candidate(request(candidate_metadata=metadata(owned_files=["docs/"]), owned_files=("docs/",)))
        self.assertIn("owned-file mismatch", result.blocked_reasons)

    # TEST 34
    def test_safe_fixture_is_only_safe_for_consideration(self) -> None:
        result = evaluate_candidate(request())
        self.assertEqual(result.evaluation_state, CandidateEvaluationState.SAFE_FOR_CONSIDERATION)
        self.assertFalse(result.execution_allowed)
        self.assertFalse(result.candidate_use_authorized)

    # TEST 35-36
    def test_projection_separates_discovered_evaluated_and_used(self) -> None:
        projection = evaluate_candidate(request()).handoff_projection()
        self.assertEqual(projection["discovered_candidates"], ["owner/repo@python-testing"])
        self.assertEqual(projection["evaluated_candidates"], ["owner/repo@python-testing"])
        self.assertNotIn("used_assets", projection)
        self.assertFalse(projection["candidate_use_authorized"])

    # TEST 37-38
    def test_evidence_digest_and_tamper_detection(self) -> None:
        evidence = dict(evaluate_candidate(request()).evidence)
        self.assertTrue(verify_evaluation_evidence(evidence))
        evidence["evaluation_state"] = "INSTALLED"
        self.assertFalse(verify_evaluation_evidence(evidence))

    # TEST 39
    def test_secret_like_evidence_is_redacted(self) -> None:
        result = evaluate_candidate(request(candidate_id="token=do-not-store"))
        self.assertNotIn("do-not-store", json.dumps(result.evidence, sort_keys=True))

    # TEST 40
    def test_exact_capability_duplicate(self) -> None:
        manifest = AssetManifest("existing", "global", frozenset({"python.testing"}), frozenset({"read"}), ("tests/",))
        self.assertEqual(exact_capability_duplicate(requirement(), [manifest], {}), "EXACT_DUPLICATE")

    # TEST 41
    def test_substring_and_fuzzy_duplicate_are_forbidden(self) -> None:
        manifest = AssetManifest("similar", "global", frozenset({"python.testing.extra"}), frozenset({"read"}), ("tests/",))
        self.assertEqual(exact_capability_duplicate(requirement(), [manifest], {"python.testing.helper": object()}), "NO_EXACT_DUPLICATE")

    # TEST 42
    def test_malformed_input_fails_closed(self) -> None:
        result = evaluate_candidate(request(candidate_metadata=None))  # type: ignore[arg-type]
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_allowed)

    # TEST 43
    def test_evaluator_failure_preserves_caller_gate_and_plan(self) -> None:
        canonical = {"gate_status": "ACTIVE", "plan_sha256": "a" * 64}
        before = json.dumps(canonical, sort_keys=True)
        evaluate_candidate(request(candidate_metadata=None))  # type: ignore[arg-type]
        self.assertEqual(json.dumps(canonical, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()

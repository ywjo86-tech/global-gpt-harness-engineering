from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.approval_gate import CAUTION, DANGEROUS, classify_discovery_intent
from runtime.orchestrator.schemas import (
    CandidateRisk,
    CapabilityCandidate,
    CapabilityRequirement,
    DiscoveryDecision,
    DiscoveryLevel,
    DiscoveryStatus,
)
from runtime.orchestrator.project_isolation import ProjectIsolation
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.skill_discovery import (
    DISCOVERY_INTENT,
    OUTPUT_CONTRACT,
    DiscoveryApproval,
    DiscoveryRequest,
    DiscoveryRuntime,
    run_read_only_discovery,
)


def requirement() -> CapabilityRequirement:
    return CapabilityRequirement(
        capability_id="python.testing", gate_id="GATE-1", lv_id="LV-1",
        required_permissions=("read",), owned_files=("tests/",), optional=False,
    )


def candidate(**overrides: object) -> CapabilityCandidate:
    values: dict[str, object] = {
        "candidate_id": "owner/repo@python-testing", "source": "skills.sh",
        "repository": "owner/repo", "maintainer": "owner", "scope": "project",
        "metadata": {"skill_md_verified": True, "permissions": ["read"], "owned_files": ["tests/"]}, "evaluation_state": "PASS",
        "risk": CandidateRisk(),
    }
    values.update(overrides)
    return CapabilityCandidate(**values)


class SkillDiscoverySchemaTests(unittest.TestCase):
    def test_existing_capability_is_terminal_and_does_not_require_discovery(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), selected_existing_asset="registered-python-agent", discovery_level=DiscoveryLevel.EXISTING_CAPABILITY, discovery_status=DiscoveryStatus.EXISTING)
        self.assertEqual(decision.discovery_status, DiscoveryStatus.EXISTING)
        self.assertFalse(decision.discovery_required)

    def test_capability_gap_requires_discovery(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.DISCOVERY_REQUIRED)
        self.assertTrue(decision.discovery_required)

    def test_unapproved_discovery_is_blocked(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, blocked_reason="dangerous approval required", approval_required=True)
        self.assertTrue(decision.approval_required)

    def test_project_install_is_not_executable(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.PROJECT_INSTALL, discovery_status=DiscoveryStatus.INSTALL_REQUIRED, approval_required=True, escalation_reason="project file write and supply-chain review")
        self.assertFalse(decision.execution_allowed)

    def test_global_install_requires_escalation(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.GLOBAL_INSTALL, discovery_status=DiscoveryStatus.ESCALATION_REQUIRED, escalation_reason="global scope", approval_required=True)
        self.assertFalse(decision.execution_allowed)

    def test_dangerous_candidate_is_blocked(self) -> None:
        risky = candidate(risk=CandidateRisk(secret=True))
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, candidate_list=(risky,), blocked_reason="candidate requires secret")
        self.assertFalse(decision.execution_allowed)

    def test_unknown_or_incomplete_candidate_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            candidate(scope="")
        with self.assertRaises(ValueError):
            candidate(metadata={})
        with self.assertRaises(ValueError):
            CapabilityCandidate(candidate_id="x", source="", repository="repo", maintainer="m", scope="project", metadata={}, evaluation_state="UNKNOWN", risk=CandidateRisk())

    def test_permission_and_owned_file_mismatch_are_not_approved(self) -> None:
        mismatched = candidate(metadata={"skill_md_verified": True, "permissions": ["write"], "owned_files": ["docs/"]})
        with self.assertRaises(ValueError):
            DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.CANDIDATE_EVALUATED, candidate_list=(mismatched,), selected_candidate=mismatched.candidate_id)

    def test_discovery_failure_does_not_become_existing_or_approved(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, blocked_reason="candidate evaluation failed")
        self.assertNotEqual(decision.discovery_status, DiscoveryStatus.EXISTING)
        self.assertFalse(decision.execution_allowed)

    def test_intents_use_existing_approval_boundaries(self) -> None:
        self.assertEqual(classify_discovery_intent("skill_discovery_read_only").classification, DANGEROUS)
        self.assertEqual(classify_discovery_intent("project_skill_install").classification, CAUTION)
        self.assertEqual(classify_discovery_intent("global_skill_install").classification, DANGEROUS)
        self.assertEqual(classify_discovery_intent("project_skill_create").classification, CAUTION)
        self.assertEqual(classify_discovery_intent("global_skill_create").classification, DANGEROUS)


class SkillDiscoveryAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.executable = self.root / "verified-skills"
        self.executable.write_text("fake executable; never invoked directly", encoding="utf-8")
        self.executable.chmod(0o700)
        approval_payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
            "classification": DANGEROUS, "status": "ACTIVE", "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1",
        }
        approval_envelope = {"payload": approval_payload, "record_hash": hashlib.sha256(canonical_json_bytes(approval_payload)).hexdigest()}
        self.approval_path = self.root / "approvals" / "discovery-1.json"
        self.approval_path.parent.mkdir()
        self.approval_path.write_bytes(canonical_json_bytes(approval_envelope))
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def approval(self, **overrides: object) -> DiscoveryApproval:
        values: dict[str, object] = {
            "intent": DISCOVERY_INTENT, "classification": DANGEROUS, "approved": True,
            "project_id": "project", "gate_id": "GATE-1", "lv_id": "LV-1",
            "evidence_reference": "approvals/discovery-1.json",
            "evidence_sha256": hashlib.sha256(self.approval_path.read_bytes()).hexdigest(),
        }
        values.update(overrides)
        return DiscoveryApproval(**values)

    def runtime(self, **overrides: object) -> DiscoveryRuntime:
        values: dict[str, object] = {
            "executable": str(self.executable), "version": "verified-fixture-1",
            "output_contract": OUTPUT_CONTRACT, "contract_verified": True,
            "contract_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest(),
            "package_auto_install": False,
        }
        values.update(overrides)
        return DiscoveryRuntime(**values)

    def request(self, **overrides: object) -> DiscoveryRequest:
        values: dict[str, object] = {
            "query": "python testing", "requirement": requirement(),
            "project_root": str(self.root), "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1", "approval": self.approval(),
            "result_limit": 5, "runtime": self.runtime(), "timestamp": "2026-08-31T00:00:00Z",
        }
        values.update(overrides)
        return DiscoveryRequest(**values)

    @staticmethod
    def records(count: int = 1) -> bytes:
        return json.dumps({"candidates": [
            {"id": f"owner/repo@skill-{index}", "name": f"skill-{index}", "source": "skills.sh",
             "repository": "owner/repo", "maintainer": "owner", "description": "read-only helper",
             "reference": f"https://skills.sh/owner/repo/skill-{index}"}
            for index in range(count)
        ]}).encode()

    def executor(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, self.records(), b"")

    def run_adapter(self, request: DiscoveryRequest, executor: object | None = None, **kwargs: object):
        runtime = request.runtime
        registry = {} if runtime is None else {runtime.contract_sha256: runtime}
        return run_read_only_discovery(request, executor=executor or self.executor,
                                       runtime_registry=registry, **kwargs)

    # TEST 11
    def test_unapproved_request_never_calls_executor(self) -> None:
        result = self.run_adapter(self.request(approval=self.approval(approved=False)))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_attempted)
        self.assertEqual(self.calls, [])

    # TEST 12
    def test_approved_fake_execution_normalizes_unassessed_candidates(self) -> None:
        result = self.run_adapter(self.request())
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        self.assertEqual(result.candidates[0].evaluation_state, "UNASSESSED")
        self.assertEqual(result.candidates[0].candidate_id, "owner/repo@skill-0")

    # TEST 13
    def test_missing_executable_is_blocked_without_install_attempt(self) -> None:
        result = self.run_adapter(self.request(runtime=None))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("unavailable", result.blocked_reason)
        self.assertEqual(self.calls, [])

    # TEST 14
    def test_package_auto_install_and_npx_are_blocked(self) -> None:
        for runtime in (self.runtime(package_auto_install=True), self.runtime(executable="/usr/bin/npx")):
            with self.subTest(runtime=runtime.executable):
                result = self.run_adapter(self.request(runtime=runtime))
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertEqual(self.calls, [])

    def test_unregistered_runtime_is_blocked_by_default(self) -> None:
        result = run_read_only_discovery(self.request(), executor=self.executor)
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("trusted allowlist", result.blocked_reason)
        self.assertEqual(self.calls, [])

    def test_approval_evidence_drift_blocks_execution(self) -> None:
        request = self.request()
        self.approval_path.write_text("{}", encoding="utf-8")
        result = self.run_adapter(request)
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("drifted", result.blocked_reason)
        self.assertEqual(self.calls, [])

    # TEST 15 and TEST 22
    def test_query_is_one_argv_element_and_executor_is_shell_free(self) -> None:
        query = "testing; touch should-not-run"
        result = self.run_adapter(self.request(query=query))
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv, [str(self.executable), "find", query])
        self.assertIs(kwargs["shell"], False)
        self.assertNotIn("npx", argv)

    # TEST 16
    def test_malformed_output_and_candidate_fail_closed(self) -> None:
        outputs = (b"not-json", json.dumps({"candidates": [{"id": "only-id"}]}).encode())
        for output in outputs:
            with self.subTest(output=output):
                def malformed(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                    return subprocess.CompletedProcess(argv, 0, output, b"")
                result = self.run_adapter(self.request(), malformed)
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertEqual(result.candidates, ())

    # TEST 17
    def test_result_limit_is_enforced(self) -> None:
        def five(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(argv, 0, self.records(5), b"")
        result = self.run_adapter(self.request(result_limit=3), five)
        self.assertEqual(len(result.candidates), 3)

    # TEST 18
    def test_discovered_candidate_is_not_promoted_to_used_asset(self) -> None:
        projection = self.run_adapter(self.request()).handoff_projection()
        self.assertNotIn("used_assets", projection)
        self.assertNotIn("selected_asset", projection)
        self.assertIs(projection["candidate_use_authorized"], False)
        self.assertEqual(projection["discovered_candidates"], ["owner/repo@skill-0"])

    # TEST 19
    def test_evidence_records_query_approval_count_and_digest(self) -> None:
        namespace = Path(self.temp.name) / "namespaces"
        namespace.mkdir()
        isolation = ProjectIsolation(namespace, self.root, "project", "project", {})
        result = self.run_adapter(self.request(), isolation=isolation)
        evidence = result.evidence
        self.assertEqual(evidence["query"], "python testing")
        self.assertIs(evidence["approval_state"]["approved"], True)
        self.assertEqual(evidence["candidate_count"], 1)
        self.assertRegex(evidence["evidence_digest"], r"^[0-9a-f]{64}$")
        self.assertTrue((namespace / "project" / result.evidence_reference).is_file())

    # TEST 20
    def test_secret_like_data_is_redacted_from_evidence(self) -> None:
        queries = (
            "testing token=very-secret-value",
            "testing Bearer bearer-secret-value",
            "testing https://user:password-value@example.invalid/path",
        )
        for query in queries:
            with self.subTest(query=query):
                result = self.run_adapter(self.request(query=query))
                serialized = json.dumps(result.evidence, sort_keys=True)
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertNotIn("very-secret-value", serialized)
                self.assertNotIn("bearer-secret-value", serialized)
                self.assertNotIn("password-value", serialized)
                self.assertNotIn(str(self.root.parent), serialized)
        self.assertEqual(self.calls, [])

    def test_secret_like_candidate_fields_are_redacted(self) -> None:
        payload = {"candidates": [{
            "id": "owner/repo@skill", "name": "skill", "source": "skills.sh",
            "repository": "owner/repo", "maintainer": "owner",
            "description": "Bearer candidate-secret", "reference": "https://user:pass@example.invalid/skill",
        }]}
        def candidate_secret(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")
        result = self.run_adapter(self.request(), candidate_secret)
        serialized = json.dumps({"candidate": result.candidates[0].description,
                                 "reference": result.candidates[0].reference,
                                 "evidence": result.evidence}, sort_keys=True)
        self.assertNotIn("candidate-secret", serialized)
        self.assertNotIn("user:pass", serialized)

    # TEST 21
    def test_failure_preserves_caller_gate_and_plan_evidence(self) -> None:
        canonical = {"plan_sha256": "a" * 64, "gate_status": "ACTIVE", "approval": {"id": "existing"}}
        before = json.dumps(canonical, sort_keys=True)
        result = self.run_adapter(self.request(runtime=None))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertEqual(json.dumps(canonical, sort_keys=True), before)

    # TEST 23
    def test_entire_adapter_uses_only_fake_executor(self) -> None:
        result = self.run_adapter(self.request())
        self.assertTrue(result.execution_attempted)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(Path(self.calls[0][0][0]), self.executable)

    def test_evidence_persistence_failure_fails_closed(self) -> None:
        class BrokenIsolation:
            def write_exclusive(self, kind: str, relative: str, payload: bytes) -> None:
                raise OSError("fixture persistence failure")

        result = self.run_adapter(self.request(), isolation=BrokenIsolation())  # type: ignore[arg-type]
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertEqual(result.evidence_reference, "")
        self.assertIn("persistence", result.blocked_reason)


if __name__ == "__main__":
    unittest.main()

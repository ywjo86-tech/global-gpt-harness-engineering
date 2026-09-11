from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
import unittest
import urllib.parse
from dataclasses import replace
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
    HTTP_TRANSPORT_TYPE,
    LEGACY_HTTP_TRANSPORT,
    LEGACY_HTTP_OUTPUT_CONTRACT,
    MUTABLE_UPSTREAM,
    OUTPUT_CONTRACT,
    UNDOCUMENTED_UPSTREAM_INTERNAL,
    DiscoveryApproval,
    DiscoveryRequest,
    DiscoveryRuntime,
    DiscoveryTransportContract,
    HTTPDiscoveryResponse,
    run_http_read_only_discovery,
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
        "metadata": {"skill_md_verified": True, "permissions": ["read"], "owned_files": ["tests/"]}, "evaluation_state": "SAFE_FOR_CONSIDERATION",
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
        self.discovery_contract_sha256 = self.runtime().contract_sha256
        approval_payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
            "classification": DANGEROUS, "status": "ACTIVE", "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1",
            "canonical_plan_sha256": "a" * 64,
            "discovery_contract_sha256": self.discovery_contract_sha256,
        }
        approval_envelope = {"payload": approval_payload, "record_hash": hashlib.sha256(canonical_json_bytes(approval_payload)).hexdigest()}
        self.approval_path = self.root / "approvals" / "discovery-1.json"
        self.approval_path.parent.mkdir()
        self.approval_path.write_bytes(canonical_json_bytes(approval_envelope))
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def approval(self, discovery_contract_sha256: str | None = None, **overrides: object) -> DiscoveryApproval:
        contract = discovery_contract_sha256 or self.discovery_contract_sha256
        payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
            "classification": DANGEROUS, "status": "ACTIVE", "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1", "canonical_plan_sha256": "a" * 64,
            "discovery_contract_sha256": contract,
        }
        envelope = {"payload": payload, "record_hash": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
        self.approval_path.write_bytes(canonical_json_bytes(envelope))
        values: dict[str, object] = {
            "intent": DISCOVERY_INTENT, "classification": DANGEROUS, "approved": True,
            "project_id": "project", "gate_id": "GATE-1", "lv_id": "LV-1",
            "evidence_reference": "approvals/discovery-1.json",
            "evidence_sha256": hashlib.sha256(self.approval_path.read_bytes()).hexdigest(),
            "canonical_plan_sha256": "a" * 64,
            "discovery_contract_sha256": contract,
        }
        values.update(overrides)
        return DiscoveryApproval(**values)

    def runtime(self, **overrides: object) -> DiscoveryRuntime:
        executable_sha256 = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        values: dict[str, object] = {
            "runtime_id": "fixture.skills", "executable_identity": "verified-skills",
            "resolved_executable": str(self.executable), "executable_sha256": executable_sha256,
            "version": "verified-fixture-1", "invocation_argv": ("find", "{query}"),
            "output_contract": OUTPUT_CONTRACT, "output_contract_verified": True,
            "timeout_seconds": 30.0, "result_limit": 5, "network_required": False,
            "package_auto_install_allowed": False, "shell_allowed": False,
            "environment_allowlist": (), "working_directory_policy": "verified_project_root",
            "contract_sha256": "",
        }
        values.update(overrides)
        provisional = DiscoveryRuntime(**values)
        values["contract_sha256"] = hashlib.sha256(canonical_json_bytes(provisional.contract_payload())).hexdigest()
        return DiscoveryRuntime(**values)

    def request(self, **overrides: object) -> DiscoveryRequest:
        values: dict[str, object] = {
            "query": "python testing", "requirement": requirement(),
            "project_root": str(self.root), "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1", "approval": self.approval(),
            "result_limit": 5, "runtime": self.runtime(), "timestamp": "2026-08-31T00:00:00Z",
            "canonical_plan_sha256": "a" * 64,
        }
        values.update(overrides)
        runtime = values.get("runtime")
        if "approval" not in overrides and isinstance(runtime, DiscoveryRuntime):
            values["approval"] = self.approval(runtime.contract_sha256)
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
        self.assertIn("binding mismatch", result.blocked_reason)
        self.assertEqual(self.calls, [])

    # TEST 14
    def test_package_auto_install_and_npx_are_blocked(self) -> None:
        for runtime in (self.runtime(package_auto_install_allowed=True), self.runtime(resolved_executable="/usr/bin/npx")):
            with self.subTest(runtime=runtime.resolved_executable):
                result = self.run_adapter(self.request(runtime=runtime))
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertEqual(self.calls, [])

    def test_unregistered_runtime_is_blocked_by_default(self) -> None:
        result = run_read_only_discovery(self.request(), executor=self.executor)
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertIn("trusted allowlist", result.blocked_reason)
        self.assertEqual(self.calls, [])

    # TEST 44
    def test_unverified_runtime_output_contract_blocks_execution(self) -> None:
        runtime = self.runtime(output_contract_verified=False)
        result = self.run_adapter(self.request(runtime=runtime))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_attempted)
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
        self.assertEqual(kwargs["env"], {})
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["timeout"], 30.0)
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


class HTTPDiscoveryTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.discovery_contract_sha256 = self.transport().contract_sha256
        approval_payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
            "classification": DANGEROUS, "status": "ACTIVE", "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1",
            "canonical_plan_sha256": "a" * 64,
            "discovery_contract_sha256": self.discovery_contract_sha256,
        }
        envelope = {"payload": approval_payload,
                    "record_hash": hashlib.sha256(canonical_json_bytes(approval_payload)).hexdigest()}
        self.approval_path = self.root / "approvals" / "discovery-1.json"
        self.approval_path.parent.mkdir()
        self.approval_path.write_bytes(canonical_json_bytes(envelope))
        self.http_calls: list[dict[str, object]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def approval(self, discovery_contract_sha256: str | None = None) -> DiscoveryApproval:
        contract = discovery_contract_sha256 or self.discovery_contract_sha256
        payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1", "intent": DISCOVERY_INTENT,
            "classification": DANGEROUS, "status": "ACTIVE", "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1", "canonical_plan_sha256": "a" * 64,
            "discovery_contract_sha256": contract,
        }
        envelope = {"payload": payload, "record_hash": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
        self.approval_path.write_bytes(canonical_json_bytes(envelope))
        return DiscoveryApproval(
            intent=DISCOVERY_INTENT, classification=DANGEROUS, approved=True,
            project_id="project", gate_id="GATE-1", lv_id="LV-1",
            evidence_reference="approvals/discovery-1.json",
            evidence_sha256=hashlib.sha256(self.approval_path.read_bytes()).hexdigest(),
            canonical_plan_sha256="a" * 64,
            discovery_contract_sha256=contract,
        )

    def transport(self, **overrides: object) -> DiscoveryTransportContract:
        relevant_source_digest = hashlib.sha256(b"observed upstream search implementation").hexdigest()
        observed_contract_digest = hashlib.sha256(b"observed legacy API contract").hexdigest()
        provenance = {
            "provenance_status": MUTABLE_UPSTREAM,
            "repository": "vercel-labs/skills",
            "ref": "main",
            "source_file": "src/find.ts",
            "relevant_source_digest": relevant_source_digest,
            "observed_contract_digest": observed_contract_digest,
        }
        values: dict[str, object] = {
            "transport_id": "skills.sh.legacy-search",
            "transport_type": HTTP_TRANSPORT_TYPE,
            "scheme": "https", "host": "skills.sh", "path": "/api/search",
            "method": "GET", "allowed_query_parameters": ("q", "limit", "owner"),
            "response_content_types": ("application/json",),
            "response_contract": LEGACY_HTTP_OUTPUT_CONTRACT,
            "max_response_bytes": 65536, "timeout_seconds": 5.0,
            "redirect_allowed": False, "authentication_required": False,
            "secret_required": False, "write_allowed": False,
            "allowed_status_codes": (200,), "result_limit": 5,
            "stability": UNDOCUMENTED_UPSTREAM_INTERNAL,
            "provenance_status": MUTABLE_UPSTREAM,
            "upstream_repository": "vercel-labs/skills", "upstream_ref": "main",
            "upstream_source_path": "src/find.ts",
            "relevant_source_digest": relevant_source_digest,
            "observed_contract_digest": observed_contract_digest,
            "upstream_evidence_digest": hashlib.sha256(canonical_json_bytes(provenance)).hexdigest(),
            "enabled": True, "contract_sha256": "",
        }
        values.update(overrides)
        provisional = DiscoveryTransportContract(**values)
        values["contract_sha256"] = hashlib.sha256(
            canonical_json_bytes(provisional.contract_payload())
        ).hexdigest()
        return DiscoveryTransportContract(**values)

    def request(self, **overrides: object) -> DiscoveryRequest:
        values: dict[str, object] = {
            "query": "python testing", "requirement": requirement(),
            "project_root": str(self.root), "project_id": "project",
            "gate_id": "GATE-1", "lv_id": "LV-1", "approval": self.approval(),
            "result_limit": 5, "runtime": None, "timestamp": "2026-09-01T00:00:00Z",
            "transport": self.transport(), "owner": "",
            "canonical_plan_sha256": "a" * 64,
        }
        values.update(overrides)
        transport = values.get("transport")
        if "approval" not in overrides and isinstance(transport, DiscoveryTransportContract):
            values["approval"] = self.approval(transport.contract_sha256)
        return DiscoveryRequest(**values)

    @staticmethod
    def legacy_body(count: int = 1, **overrides: object) -> bytes:
        payload: dict[str, object] = {
            "query": "python testing", "searchType": "semantic",
            "searchVersion": "observed-opaque-version",
            "skills": [
                {"id": f"owner/repo/skill-{index}", "name": f"skill-{index}",
                 "skillId": f"skill-{index}", "installs": index, "source": "owner/repo"}
                for index in range(count)
            ],
            "count": count, "duration_ms": 12,
        }
        payload.update(overrides)
        return json.dumps(payload).encode()

    def http_executor(self, **kwargs: object) -> HTTPDiscoveryResponse:
        self.http_calls.append(dict(kwargs))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(str(kwargs["url"])).query)["q"][0]
        return HTTPDiscoveryResponse(
            200, "application/json; charset=utf-8", self.legacy_body(query=query)
        )

    def run_http(self, request: DiscoveryRequest | None = None, executor: object | None = None):
        request = request or self.request()
        transport = request.transport
        registry = {} if transport is None else {transport.contract_sha256: transport}
        return run_http_read_only_discovery(
            request, http_executor=executor or self.http_executor,
            transport_registry=registry,
        )

    # TEST A, N, O, P, Q
    def test_valid_search_is_discovery_only(self) -> None:
        result = self.run_http()
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        self.assertEqual(result.candidates[0].candidate_id, "owner/repo/skill-0")
        self.assertEqual(result.candidates[0].skill_id, "skill-0")
        self.assertEqual(result.candidates[0].repository, "UNKNOWN")
        self.assertEqual(result.candidates[0].maintainer, "UNKNOWN")
        self.assertEqual(result.candidates[0].description, "UNKNOWN")
        self.assertEqual(result.candidates[0].reference, "UNKNOWN")
        self.assertEqual(result.candidates[0].evaluation_state, "UNASSESSED")
        projection = result.handoff_projection()
        self.assertFalse(projection["candidate_use_authorized"])
        self.assertNotIn("used_assets", projection)
        self.assertNotIn("gate_status", projection)

    def test_registered_legacy_contract_is_trusted_with_conditions(self) -> None:
        self.assertTrue(LEGACY_HTTP_TRANSPORT.trusted_with_conditions)
        self.assertEqual(LEGACY_HTTP_TRANSPORT.provenance_status, MUTABLE_UPSTREAM)
        self.assertEqual(LEGACY_HTTP_TRANSPORT.upstream_ref, "main")
        request = self.request(transport=LEGACY_HTTP_TRANSPORT)
        result = run_http_read_only_discovery(request, http_executor=self.http_executor)
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        resolution = result.evidence["transport_resolution"]
        self.assertEqual(resolution["provenance_status"], MUTABLE_UPSTREAM)
        self.assertEqual(resolution["upstream_evidence_digest"], LEGACY_HTTP_TRANSPORT.upstream_evidence_digest)
        self.assertEqual(resolution["observed_contract_digest"], LEGACY_HTTP_TRANSPORT.observed_contract_digest)

    # TEST B, E
    def test_http_executor_uses_get_without_credentials_or_body(self) -> None:
        self.run_http()
        call = self.http_calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["headers"], {})
        self.assertIsNone(call["body"])

    # TEST C, D, E, T
    def test_unsafe_or_credential_transport_is_blocked_before_execution(self) -> None:
        contracts = (
            self.transport(scheme="http"),
            self.transport(host="example.invalid"),
            self.transport(path="/api/changed"),
            self.transport(method="POST"),
            self.transport(authentication_required=True),
            self.transport(path="/api/v1/skills/search", authentication_required=True,
                           stability="DOCUMENTED_V1", response_contract="skills.sh.v1.search.json"),
        )
        for transport in contracts:
            with self.subTest(transport=transport):
                result = self.run_http(self.request(transport=transport))
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertFalse(result.execution_attempted)
        self.assertEqual(self.http_calls, [])

    # TEST F, G, H
    def test_redirect_timeout_and_oversize_fail_closed(self) -> None:
        def redirect(**kwargs: object) -> HTTPDiscoveryResponse:
            return HTTPDiscoveryResponse(302, "application/json", b"{}", redirected=True)
        def timeout(**kwargs: object) -> HTTPDiscoveryResponse:
            raise TimeoutError("fixture timeout")
        def oversized(**kwargs: object) -> HTTPDiscoveryResponse:
            return HTTPDiscoveryResponse(200, "application/json", b"x" * 65537)
        for executor in (redirect, timeout, oversized):
            with self.subTest(executor=executor.__name__):
                self.assertEqual(self.run_http(executor=executor).status, DiscoveryStatus.BLOCKED)

    # TEST I, J, K and count/query mismatch
    def test_invalid_json_schema_candidate_and_count_fail_closed(self) -> None:
        responses = (
            b"not-json",
            json.dumps({"skills": []}).encode(),
            self.legacy_body(skills=[{"id": "only-id"}], count=1),
            self.legacy_body(count=2, skills=[]),
            self.legacy_body(query="different query"),
        )
        for body in responses:
            with self.subTest(body=body):
                def malformed(**kwargs: object) -> HTTPDiscoveryResponse:
                    return HTTPDiscoveryResponse(200, "application/json", body)
                result = self.run_http(executor=malformed)
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertEqual(result.candidates, ())

    def test_observed_additive_fields_are_required_and_accepted(self) -> None:
        result = self.run_http(executor=lambda **kwargs: HTTPDiscoveryResponse(
            200, "application/json", self.legacy_body(searchVersion=2)
        ))
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        self.assertEqual(result.candidates[0].skill_id, "skill-0")

        for missing in ("searchVersion", "skillId"):
            with self.subTest(missing=missing):
                payload = json.loads(self.legacy_body())
                if missing == "searchVersion":
                    del payload[missing]
                else:
                    del payload["skills"][0][missing]
                response = lambda **kwargs: HTTPDiscoveryResponse(  # noqa: E731
                    200, "application/json", json.dumps(payload).encode()
                )
                self.assertEqual(self.run_http(executor=response).status, DiscoveryStatus.BLOCKED)

    def test_unknown_fields_are_contract_drift_and_blocked(self) -> None:
        payloads = []
        top = json.loads(self.legacy_body())
        top["futureField"] = "unexpected"
        payloads.append(top)
        candidate = json.loads(self.legacy_body())
        candidate["skills"][0]["futureField"] = "unexpected"
        payloads.append(candidate)
        for payload in payloads:
            with self.subTest(payload=payload):
                response = lambda **kwargs: HTTPDiscoveryResponse(  # noqa: E731
                    200, "application/json", json.dumps(payload).encode()
                )
                result = self.run_http(executor=response)
                self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
                self.assertIn("CONTRACT_DRIFT", result.blocked_reason)

    def test_wrong_observed_field_types_fail_closed(self) -> None:
        overrides = (
            {"searchVersion": None}, {"searchVersion": True}, {"searchVersion": ""},
            {"duration_ms": "12"}, {"count": True}, {"skills": {}},
        )
        for changed in overrides:
            with self.subTest(changed=changed):
                response = lambda **kwargs: HTTPDiscoveryResponse(  # noqa: E731
                    200, "application/json", self.legacy_body(**changed)
                )
                self.assertEqual(self.run_http(executor=response).status, DiscoveryStatus.BLOCKED)

    def test_non_json_content_type_fails_closed(self) -> None:
        def text_response(**kwargs: object) -> HTTPDiscoveryResponse:
            return HTTPDiscoveryResponse(200, "text/plain", self.legacy_body())
        self.assertEqual(self.run_http(executor=text_response).status, DiscoveryStatus.BLOCKED)

    # TEST L
    def test_result_limit_is_enforced(self) -> None:
        def many(**kwargs: object) -> HTTPDiscoveryResponse:
            return HTTPDiscoveryResponse(200, "application/json", self.legacy_body(5))
        result = self.run_http(self.request(result_limit=3), many)
        self.assertEqual(len(result.candidates), 3)

    # TEST M
    def test_query_and_owner_use_safe_url_encoding(self) -> None:
        result = self.run_http(self.request(query="python testing & QA", owner="Vercel-Labs"))
        self.assertEqual(result.status, DiscoveryStatus.DISCOVERY_COMPLETED)
        url = str(self.http_calls[0]["url"])
        self.assertNotIn("python testing", url)
        self.assertEqual(
            urllib.parse.parse_qs(urllib.parse.urlsplit(url).query),
            {"q": ["python testing & QA"], "limit": ["5"], "owner": ["vercel-labs"]},
        )

    # TEST R
    def test_transport_contract_digest_drift_is_blocked(self) -> None:
        transport = replace(self.transport(), contract_sha256="a" * 64)
        result = self.run_http(self.request(transport=transport))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_attempted)

    def test_upstream_provenance_tamper_is_blocked(self) -> None:
        transport = self.transport(upstream_evidence_digest="a" * 64)
        self.assertFalse(transport.trusted_with_conditions)
        result = self.run_http(self.request(transport=transport))
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_attempted)

    # TEST S
    def test_cli_transport_remains_not_trusted_without_runtime(self) -> None:
        result = run_read_only_discovery(
            self.request(transport=None), executor=lambda *args, **kwargs: self.fail("executor called"),
            runtime_registry={},
        )
        self.assertEqual(result.status, DiscoveryStatus.BLOCKED)
        self.assertFalse(result.execution_attempted)


if __name__ == "__main__":
    unittest.main()

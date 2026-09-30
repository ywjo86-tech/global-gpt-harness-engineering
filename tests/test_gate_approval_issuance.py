"""Safety boundaries for Gate approval issuance."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry, build_alias_entry
from runtime.orchestrator.gate_approval_issuance import (
    GateApprovalIssuer, GateApprovalIssuanceError, GateApprovalIssuanceRequest,
    _canonical, _sha,
)


class GateApprovalIssuanceTest(unittest.TestCase):
    def test_one_exact_owner_comment_can_issue_bounded_delegated_gate(self) -> None:
        from runtime.orchestrator.approved_full_plan_activation_contract import ApprovedFullPlanActivationRequestV1
        raw = dict(self.raw, mode="ISSUE", preflight_digest=self.digest,
                   owner_approval_comment_id=123,
                   approval_id="DELEGATED:OWNER-APPROVAL-001")
        request = GateApprovalIssuanceRequest.from_mapping(raw)
        self.binding["evidence"]["payload"].update({
            "plan_sha256": "d" * 64, "branch": "main", "head": "a" * 40,
        })
        scope = {
            "schema_version": "orchestration.full-plan-owner-delegation.v1",
            "decision_id": request.approval_ref, "project_id": "TEST-PROJECT",
            "plan_sha256": "d" * 64, "spec_sha256": "e" * 64,
            "gate_ids": ["GATE-001", "GATE-002"], "source_head": "a" * 40,
            "runtime_sha256": "f" * 64,
            "issued_at": self.raw["issued_at"], "expires_at": self.raw["expires_at"],
            "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
        }
        body = "OCP_FULL_PLAN_OWNER_DELEGATION_V1\n" + _canonical(scope).decode("utf-8")
        comment = {"id": 123, "user": {"id": 235775273}, "body": body,
                   "created_at": self.raw["issued_at"], "updated_at": self.raw["issued_at"],
                   "performed_via_github_app": None}
        gate_ref = lambda gate: {"gate_id": gate,
            "approval_evidence": {"path": gate + ".json", "sha256": "1" * 64},
            "engine_requirement_evidence": None, "project_requirement_evidence_by_lv": []}
        activation = ApprovedFullPlanActivationRequestV1.from_mapping({
            "schema_version": "orchestration.approved-full-plan-activation-request.v1",
            "activation_request_id": "A-1", "project_alias": "test-project",
            "approved_plan": {"path": "docs/plan", "sha256": "d" * 64},
            "approved_spec": {"path": "docs/spec", "sha256": "e" * 64},
            "expected_branch": "main", "expected_head": "a" * 40,
            "runtime_release_digest": "f" * 64, "approval_ref": request.approval_ref,
            "gate_bindings": [gate_ref("GATE-001"), gate_ref("GATE-002")],
        })
        with self.assertRaises(GateApprovalIssuanceError):
            self.issuer.execute(request, owner_approval_comment=comment, owner_actor_id="235775273")
        issued = self.issuer.execute(
            request, owner_approval_comment=comment, owner_actor_id="235775273",
            delegated_full_plan_scope=scope, activation_request=activation,
            serving_runtime_digest="f" * 64,
        )
        self.assertEqual(issued["status"], "ISSUED")
        with self.assertRaisesRegex(GateApprovalIssuanceError, "FULL_PLAN_DELEGATION_INVALID"):
            self.issuer.execute(
                request, owner_approval_comment=comment, owner_actor_id="235775273",
                delegated_full_plan_scope=scope, activation_request=activation,
                serving_runtime_digest="0" * 64,
            )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.namespace = root / "_workspace" / "global-gate" / "TEST-PROJECT" / "approval"
        self.issuer = object.__new__(GateApprovalIssuer)
        self.issuer.state_root = root
        now = datetime.now(timezone.utc)
        issued = (now - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        expires = (now + timedelta(minutes=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.raw = {
            "schema_version": "orchestration.gate-approval-issuance-request.v1",
            "request_id": "ISSUE-001", "project_alias": "test-project", "gate_id": "GATE-001",
            "expected_branch": "main", "expected_head": "a" * 40,
            "requirements_sha256": "b" * 64, "approval_id": "APPROVAL-001",
            "approval_ref": "OWNER-APPROVAL-001", "issued_at": issued,
            "expires_at": expires, "mode": "DRY_RUN", "preflight_digest": None,
            "owner_approval_comment_id": None,
            "engine_requirement_evidence": None,
            "project_requirement_evidence_by_lv": [],
        }
        self.binding = {"evidence": {"payload": {"project_id": "TEST-PROJECT"}, "record_hash": "c" * 64}}
        self.digest = _sha(self.binding)
        self.issuer._preflight = lambda _: (self.binding, self.digest)

    def test_delegated_request_fields_are_closed_and_preserve_legacy_digest(self) -> None:
        from tests.test_approved_full_plan_activation_contract import executable_request
        direct = GateApprovalIssuanceRequest.from_mapping(self.raw)
        self.assertEqual(direct.to_dict(), self.raw)
        self.assertNotIn("delegation_scope", direct.to_dict())
        scope = {
            "schema_version": "orchestration.full-plan-owner-delegation.v1",
            "decision_id": "OWNER-APPROVAL-001", "project_id": "TEST-PROJECT",
            "plan_sha256": "a" * 64, "spec_sha256": "b" * 64,
            "gate_ids": ["GATE-001"], "source_head": "c" * 40,
            "runtime_sha256": "d" * 64,
            "issued_at": self.raw["issued_at"], "expires_at": self.raw["expires_at"],
            "excluded_actions": ["PR_MERGE", "RUNTIME_SWITCH", "SERVICE_RESTART", "REBOOT"],
        }
        delegated = dict(self.raw, delegation_scope=scope,
                         delegation_activation=executable_request(),
                         finalize_delegation=True)
        parsed = GateApprovalIssuanceRequest.from_mapping(delegated)
        self.assertEqual(parsed.to_dict(), delegated)
        self.assertNotEqual(parsed.request_digest, direct.request_digest)
        for invalid in (
            dict(self.raw, delegation_scope=scope),
            dict(delegated, finalize_delegation="true"),
            dict(delegated, delegation_scope={**scope, "extra": "forbidden"}),
        ):
            with self.assertRaisesRegex(GateApprovalIssuanceError, "REQUEST_FIELDS_MISMATCH|FULL_PLAN_DELEGATION_INVALID"):
                GateApprovalIssuanceRequest.from_mapping(invalid)

    def test_requested_alias_ignores_unrelated_ambiguous_project(self) -> None:
        root = Path(self.temp.name)
        project = root / "CANARY"
        project.mkdir()
        (project / "IMPLEMENTATION_PLAN.md").write_text("# Canary\n")
        registry_root = root / "aliases"
        registry_root.mkdir()
        entry = build_alias_entry(project, "test-project")
        (registry_root / "test-project.json").write_text(json.dumps(entry))
        other = root / "OTHER"
        (other / "docs").mkdir(parents=True)
        (other / "IMPLEMENTATION_PLAN.md").write_text("# Other\n")
        (other / "docs" / "DEVELOPMENT_PLAN.txt").write_text("Other plan\n")
        (registry_root / "other.json").write_text(json.dumps({"alias": "other", "project_root": str(other)}))
        self.issuer.registry = OnboardingRegistry(registry_root)
        self.assertEqual(self.issuer._registered_alias("test-project"), entry)
        with self.assertRaisesRegex(GateApprovalIssuanceError, "PROJECT_NOT_REGISTERED"):
            self.issuer._registered_alias("missing")

    def test_preflight_has_no_write(self) -> None:
        request = GateApprovalIssuanceRequest.from_mapping(self.raw)
        result = self.issuer.execute(request)
        self.assertEqual(result["status"], "PREFLIGHT_READY")
        self.assertFalse(self.namespace.exists())

    def test_issue_requires_distinct_unedited_owner_comment_and_replays(self) -> None:
        raw = dict(self.raw, mode="ISSUE", preflight_digest=self.digest,
                   owner_approval_comment_id=123)
        request = GateApprovalIssuanceRequest.from_mapping(raw)
        body = "OCP_GATE_OWNER_APPROVAL_V1\n" + _canonical({
            "approval_ref": request.approval_ref, "preflight_digest": self.digest,
            "request_id": request.request_id,
        }).decode("utf-8")
        comment = {"id": 123, "user": {"id": 235775273}, "body": body,
                   "created_at": "2026-09-29T00:00:00Z", "updated_at": "2026-09-29T00:00:00Z",
                   "performed_via_github_app": None}
        with self.assertRaises(GateApprovalIssuanceError):
            self.issuer.execute(request, owner_actor_id="235775273")
        with self.assertRaises(GateApprovalIssuanceError):
            self.issuer.execute(request, owner_approval_comment=dict(
                comment, performed_via_github_app={"slug": "chatgpt-codex-connector"}),
                owner_actor_id="235775273")
        issued = self.issuer.execute(request, owner_approval_comment=comment,
                                     owner_actor_id="235775273")
        self.assertEqual(issued["status"], "ISSUED")
        self.assertEqual(json.loads((self.namespace / "ISSUE-001.json").read_text()), self.binding["evidence"])
        replay = self.issuer.execute(request, owner_approval_comment=comment,
                                     owner_actor_id="235775273")
        self.assertEqual(replay["status"], "ALREADY_ISSUED")
        self.assertEqual(sorted(p.name for p in self.namespace.iterdir()), ["ISSUE-001.json"])


if __name__ == "__main__":
    unittest.main()

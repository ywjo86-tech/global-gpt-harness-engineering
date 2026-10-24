from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from runtime.orchestrator.g1_gate_approval_route import G1_GATE_APPROVAL_PROFILE
from runtime.orchestrator.gate_approval_issuance import GateApprovalIssuanceRequest
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService


class _Transport:
    def __init__(self, envelope):
        self.envelope = envelope
        self.projections = []
        self.acks = []

    def receive(self, *, limit=16):
        return (object(),)[:limit]

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)


def _envelope(alias: str, policy_ref: str, *, gate_id=None, branch=None, head=None, requirements_sha256=None):
    now = datetime.now(timezone.utc)
    issued = (now - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expires = (now + timedelta(minutes=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    project_requirement_evidence_by_lv = []
    if alias == G1_GATE_APPROVAL_PROFILE.project_alias:
        project_requirement_evidence_by_lv = [{
            "lv_id": G1_GATE_APPROVAL_PROFILE.project_requirement_lv_id,
            "path": G1_GATE_APPROVAL_PROFILE.project_requirement_evidence_path,
            "sha256": G1_GATE_APPROVAL_PROFILE.project_requirement_evidence_sha256,
        }]
    request = GateApprovalIssuanceRequest.from_mapping({
        "schema_version": "orchestration.gate-approval-issuance-request.v1",
        "request_id": "G1-ROUTE-REQUEST-001",
        "project_alias": alias,
        "gate_id": gate_id or G1_GATE_APPROVAL_PROFILE.gate_id,
        "expected_branch": branch or G1_GATE_APPROVAL_PROFILE.expected_branch,
        "expected_head": head or G1_GATE_APPROVAL_PROFILE.expected_head,
        "requirements_sha256": requirements_sha256 or G1_GATE_APPROVAL_PROFILE.requirements_sha256,
        "approval_id": "G1-ROUTE-APPROVAL-001",
        "approval_ref": "G1-ROUTE-OWNER-APPROVAL",
        "issued_at": issued,
        "expires_at": expires,
        "mode": "DRY_RUN",
        "preflight_digest": None,
        "owner_approval_comment_id": None,
        "engine_requirement_evidence": None,
        "project_requirement_evidence_by_lv": project_requirement_evidence_by_lv,
    })
    raw = seal_remote_control_envelope({
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "GATE_APPROVAL_ISSUE",
        "message_id": "MSG-G1-ROUTE-001",
        "sequence": 1,
        "issued_at": issued,
        "expires_at": expires,
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:7",
            "source_actor_id": G1_GATE_APPROVAL_PROFILE.owner_actor_id,
            "source_message_id": "123",
        },
        "payload": request.to_dict(),
        "payload_digest": "",
        "authorization": {"gate_approval_issue_policy_ref": policy_ref},
        "envelope_sha256": "",
    })
    return validate_remote_control_envelope(raw, now=now)


class G1GateApprovalServiceRoutingTests(unittest.TestCase):
    def _poll(self, envelope, *, g1_enabled=True, g1_policy="G1-ISSUE-POLICY", g1_callback=None):
        transport = _Transport(envelope)
        generic = Mock(return_value={"schema_version": "test.projection.v1", "result_class": "GENERIC"})
        g1 = Mock(return_value={"schema_version": "test.projection.v1", "result_class": "G1"})
        if g1_callback is not None:
            g1 = g1_callback
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=Mock(),
            execute_authorized=Mock(),
            issue_gate_approval_authorized=generic,
            gate_approval_issue_enabled=True,
            gate_approval_issue_policy_ref="GENERIC-ISSUE-POLICY",
            issue_g1_gate_approval_authorized=g1,
            g1_gate_approval_issue_enabled=g1_enabled,
            g1_gate_approval_issue_policy_ref=g1_policy,
        )
        result = service.poll_once(mode=ControlMode.ACTIVE)
        return result, transport, generic, g1

    def test_g1_alias_uses_g1_callback_and_distinct_policy(self):
        envelope = _envelope(G1_GATE_APPROVAL_PROFILE.project_alias, "G1-ISSUE-POLICY")
        result, transport, generic, g1 = self._poll(envelope)

        self.assertEqual(result.blocked, 0)
        g1.assert_called_once_with(envelope)
        generic.assert_not_called()
        self.assertEqual(transport.projections[0]["result_class"], "G1")

    def test_g1_route_disabled_does_not_fall_through_to_generic_issuer(self):
        envelope = _envelope(G1_GATE_APPROVAL_PROFILE.project_alias, "GENERIC-ISSUE-POLICY")
        result, transport, generic, g1 = self._poll(envelope, g1_enabled=False)

        self.assertEqual(result.blocked, 1)
        self.assertEqual(transport.projections[0]["result_class"], "G1_GATE_APPROVAL_ISSUE_DISABLED")
        generic.assert_not_called()
        g1.assert_not_called()

    def test_g1_alias_rejects_generic_policy_even_if_generic_route_is_enabled(self):
        envelope = _envelope(G1_GATE_APPROVAL_PROFILE.project_alias, "GENERIC-ISSUE-POLICY")
        result, transport, generic, g1 = self._poll(envelope)

        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "G1_GATE_APPROVAL_ISSUE_AUTHORIZATION_MISMATCH",
        )
        generic.assert_not_called()
        g1.assert_not_called()

    def test_g1_callback_failure_is_logged_without_exception_message_and_stays_blocked(self):
        envelope = _envelope(G1_GATE_APPROVAL_PROFILE.project_alias, "G1-ISSUE-POLICY")

        def fail_with_sensitive_message(_envelope):
            raise RuntimeError("sensitive callback payload")

        with self.assertLogs("runtime.orchestrator.remote_operator_service", level="ERROR") as captured:
            result, transport, generic, _ = self._poll(envelope, g1_callback=fail_with_sensitive_message)

        self.assertEqual(result.blocked, 1)
        self.assertEqual(result.acknowledged, 1)
        self.assertEqual(transport.projections[0]["result_class"], "GATE_APPROVAL_ISSUE_ERROR")
        self.assertIn("GATE_APPROVAL_ISSUE_CALLBACK_FAILED route=G1", captured.output[0])
        self.assertIn("request_id=G1-ROUTE-REQUEST-001", captured.output[0])
        self.assertIn("exception_type=RuntimeError", captured.output[0])
        self.assertNotIn("sensitive callback payload", captured.output[0])
        generic.assert_not_called()

    def test_existing_g3_alias_continues_through_generic_route(self):
        envelope = _envelope(
            "ocp-rdc-exec-canary-20260923-r2",
            "GENERIC-ISSUE-POLICY",
            gate_id="GATE-003",
            branch="g3/revision-5-contract-20261022",
            head="6" * 40,
            requirements_sha256="b" * 64,
        )
        result, transport, generic, g1 = self._poll(envelope)

        self.assertEqual(result.blocked, 0)
        generic.assert_called_once_with(envelope)
        g1.assert_not_called()
        self.assertEqual(transport.projections[0]["result_class"], "GENERIC")


if __name__ == "__main__":
    unittest.main()

"""Safety boundaries for Gate approval issuance."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.gate_approval_issuance import (
    GateApprovalIssuer, GateApprovalIssuanceError, GateApprovalIssuanceRequest,
    _canonical, _sha,
)


class GateApprovalIssuanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.namespace = root / "_workspace" / "global-gate" / "TEST-PROJECT" / "approval"
        self.namespace.mkdir(parents=True)
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

    def test_preflight_has_no_write(self) -> None:
        request = GateApprovalIssuanceRequest.from_mapping(self.raw)
        result = self.issuer.execute(request)
        self.assertEqual(result["status"], "PREFLIGHT_READY")
        self.assertEqual(list(self.namespace.iterdir()), [])

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

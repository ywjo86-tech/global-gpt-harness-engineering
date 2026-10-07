"""Safety boundaries for Gate approval issuance."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.project_onboarding import OnboardingRegistry, build_alias_entry
from runtime.orchestrator.gate_approval_issuance import (
    GateApprovalIssuer, GateApprovalIssuanceError, GateApprovalIssuanceRequest,
    _canonical, _canonicalize_newlines, _sha,
)


class GateApprovalIssuanceTest(unittest.TestCase):
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

    def _sealed_recovery_fixture(self):
        root = Path(self.temp.name)
        project = root / "project"
        project.mkdir(exist_ok=True)
        owned = project / "owned.txt"
        owned.write_text("partial\n", encoding="utf-8")
        project_id = "TEST-PROJECT"
        plan_sha = "d" * 64
        baseline = "a" * 40
        current = "c" * 40
        run_id = "RUN-1"
        recovery_id = f"{run_id}-recovery-02"
        source = {
            "schema_version": "orchestration.pre-result-partial-source.v1",
            "project_id": project_id,
            "gate_id": "GATE-001",
            "lv_id": "TASK-006",
            "run_id": run_id,
            "attempt": 1,
            "canonical_plan_sha256": plan_sha,
            "approval_event_id": "OLD-GATE-APPROVAL",
            "branch": "main",
            "baseline_head": baseline,
            "source_head": current,
            "current_head": current,
            "owned_files": ["owned.txt"],
            "owned_diff": {
                "owned.txt": hashlib.sha256(owned.read_bytes()).hexdigest(),
            },
            "hard_stop": True,
        }
        source["source_payload_sha256"] = _sha(source)
        package_root = root / "_workspace" / "orchestration-runs" / run_id / "TASK-006"
        source_path = package_root / "pre-result-partial-source.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(_canonical(source))
        source_relative = source_path.relative_to(root).as_posix()
        source_file_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

        source_shas = {}
        for relative, payload in (
            (f"_workspace/orchestration-runs/{run_id}/TASK-006/package.manifest.json", b"package"),
            (f"_workspace/orchestration-runs/{run_id}/TASK-006/preflight/preflight.evidence.json", b"preflight"),
            (f"_workspace/orchestration-runs/{run_id}/TASK-006/worker.request.json", b"request"),
            (f"_workspace/orchestration-runs/{run_id}/TASK-006/executor.process.json", b"process"),
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            source_shas[relative] = hashlib.sha256(payload).hexdigest()
        source_shas[source_relative] = source_file_sha

        record = {
            "schema_version": "orchestration.production-recovery.v1",
            "recovery_id": recovery_id,
            "project_id": project_id,
            "gate_id": "GATE-001",
            "lv_id": "TASK-006",
            "run_id": run_id,
            "rejected_attempt": 1,
            "rejected_artifacts": {source_relative: source_file_sha},
            "rejection_reason_code": "REJECTED_PRE_RESULT_PARTIAL",
            "missing_bindings": ["worker.result"],
            "recovery_attempt": 2,
            "approval_event_id": "OLD-GATE-APPROVAL",
            "plan_sha256": plan_sha,
            "branch": "main",
            "baseline_head": baseline,
            "current_head": current,
            "active_transition_sha256": source_file_sha,
            "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE",
            "source_shas": source_shas,
            "predecessor": None,
            "supersedes": source_file_sha,
            "created_at": "2026-10-07T00:00:00Z",
            "hard_stop": True,
        }
        record["record_hash"] = _sha(record)
        recovery_root = root / "_workspace" / "global-gate" / project_id / "recovery"
        recovery_root.mkdir(parents=True, exist_ok=True)
        (recovery_root / f"{recovery_id}.json").write_bytes(_canonical(record))

        checkpoint = {
            "schema_version": "orchestration.production-recovery-checkpoint.v1",
            "project_id": project_id,
            "gate_id": "GATE-001",
            "lv_id": "TASK-006",
            "run_id": run_id,
            "recovery_id": recovery_id,
            "rejected_attempt": 1,
            "next_attempt": 2,
            "recovery_record_hash": record["record_hash"],
            "completion_evidence": [],
            "status": "REJECTED_PRE_RESULT_PARTIAL",
            "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE",
            "hard_stop": True,
        }
        checkpoint["checkpoint_sha256"] = _sha(checkpoint)
        (recovery_root / f"{recovery_id}.checkpoint.json").write_bytes(_canonical(checkpoint))
        return {
            "project": project,
            "owned": owned,
            "project_id": project_id,
            "plan_sha": plan_sha,
            "baseline": baseline,
            "current": current,
            "source": source,
            "record": record,
            "recovery_root": recovery_root,
        }

    def test_recovery_renewal_accepts_only_exact_sealed_partial_source(self) -> None:
        fixture = self._sealed_recovery_fixture()
        request = GateApprovalIssuanceRequest.from_mapping(dict(
            self.raw, expected_head=fixture["baseline"],
        ))
        verified = {
            "verified_only": True,
            "source": fixture["source"],
            "next_attempt": 2,
        }
        with patch(
            "runtime.orchestrator.gate_approval_issuance.prepare_pre_result_partial_recovery",
            return_value=verified,
        ) as validate:
            result = self.issuer._verified_recovery_renewal(
                request,
                project_root=fixture["project"],
                project_id=fixture["project_id"],
                plan_sha256=fixture["plan_sha"],
                actual_branch="main",
                actual_head=fixture["current"],
                status_text=" M owned.txt",
            )
        self.assertEqual(result["recovery_id"], fixture["record"]["recovery_id"])
        self.assertEqual(result["dirty_files"], ["owned.txt"])
        validate.assert_called_once()

        with patch(
            "runtime.orchestrator.gate_approval_issuance.prepare_pre_result_partial_recovery",
            return_value=verified,
        ):
            with self.assertRaisesRegex(
                GateApprovalIssuanceError, "RECOVERY_RENEWAL_DIRTY_SCOPE_MISMATCH"
            ):
                self.issuer._verified_recovery_renewal(
                    request,
                    project_root=fixture["project"],
                    project_id=fixture["project_id"],
                    plan_sha256=fixture["plan_sha"],
                    actual_branch="main",
                    actual_head=fixture["current"],
                    status_text=" M owned.txt\n?? extra.txt",
                )

        fixture["owned"].write_text("tampered\n", encoding="utf-8")
        with patch(
            "runtime.orchestrator.gate_approval_issuance.prepare_pre_result_partial_recovery",
            return_value=verified,
        ):
            with self.assertRaisesRegex(
                GateApprovalIssuanceError, "RECOVERY_RENEWAL_DIRTY_SCOPE_MISMATCH"
            ):
                self.issuer._verified_recovery_renewal(
                    request,
                    project_root=fixture["project"],
                    project_id=fixture["project_id"],
                    plan_sha256=fixture["plan_sha"],
                    actual_branch="main",
                    actual_head=fixture["current"],
                    status_text=" M owned.txt",
                )

    def test_recovery_renewal_rejects_ambiguous_sealed_records(self) -> None:
        fixture = self._sealed_recovery_fixture()
        duplicate = dict(fixture["record"])
        duplicate["recovery_id"] = "RUN-1-recovery-03"
        duplicate["record_hash"] = _sha({k: v for k, v in duplicate.items() if k != "record_hash"})
        (fixture["recovery_root"] / "RUN-1-recovery-03.json").write_bytes(_canonical(duplicate))
        request = GateApprovalIssuanceRequest.from_mapping(dict(
            self.raw, expected_head=fixture["baseline"],
        ))
        with self.assertRaisesRegex(
            GateApprovalIssuanceError, "RECOVERY_RENEWAL_EVIDENCE_AMBIGUOUS"
        ):
            self.issuer._verified_recovery_renewal(
                request,
                project_root=fixture["project"],
                project_id=fixture["project_id"],
                plan_sha256=fixture["plan_sha"],
                actual_branch="main",
                actual_head=fixture["current"],
                status_text=" M owned.txt",
            )

    def test_preflight_uses_recovery_binding_only_for_sealed_dirty_source(self) -> None:
        root = Path(self.temp.name)
        project = root / "PREVIEW"
        project.mkdir()
        plan_path = project / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n", encoding="utf-8")
        plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        mapping_root = root / "mappings"
        mapping_root.mkdir(exist_ok=True)
        self.issuer.mapping_root = mapping_root

        entry = {
            "project_id": "TEST-PROJECT",
            "project_root": str(project),
        }
        mapping = SimpleNamespace(
            canonical_sha256=plan_sha,
            canonical_source=plan_path,
            task_lv_projection_path=None,
        )
        plan = SimpleNamespace(
            project_id="TEST-PROJECT",
            canonical_plan_sha256=plan_sha,
            lvs=[SimpleNamespace(lv_id="TASK-006", owned_files=["owned.txt"])],
        )
        baseline = "a" * 40
        current = "c" * 40
        request = GateApprovalIssuanceRequest.from_mapping(dict(
            self.raw, expected_head=baseline,
        ))

        def git_clean(_root, *args):
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return baseline
            if args == ("status", "--porcelain=v1", "-uall"):
                return ""
            raise AssertionError(args)

        common = (
            patch.object(self.issuer, "_registered_alias", return_value=entry),
            patch("runtime.orchestrator.gate_approval_issuance.load_project_mapping", return_value=mapping),
            patch("runtime.orchestrator.gate_approval_issuance.validate_mapping_sources", return_value=[]),
            patch("runtime.orchestrator.gate_approval_issuance.load_gate_plan", return_value=plan),
            patch("runtime.orchestrator.gate_approval_issuance._validate_gate_requirement_artifacts"),
        )
        with common[0], common[1], common[2], common[3], common[4], \
                patch.object(self.issuer, "_git", side_effect=git_clean), \
                patch.object(
                    self.issuer, "_verified_recovery_renewal",
                    side_effect=AssertionError("clean source must not enter recovery renewal"),
                ):
            clean_binding, clean_digest = GateApprovalIssuer._preflight(self.issuer, request)
        self.assertNotIn("recovery_renewal", clean_binding)
        self.assertEqual(clean_digest, _sha(clean_binding))

        recovery = {
            "schema_version": "orchestration.gate-approval-recovery-renewal.v1",
            "recovery_id": "RUN-1-recovery-02",
            "recovery_record_hash": "1" * 64,
            "recovery_checkpoint_sha256": "2" * 64,
            "source_payload_sha256": "3" * 64,
            "source_file_sha256": "4" * 64,
            "current_head": current,
            "dirty_files": ["owned.txt"],
        }

        def git_recovery(_root, *args):
            if args == ("branch", "--show-current"):
                return "main"
            if args == ("rev-parse", "HEAD"):
                return current
            if args == ("status", "--porcelain=v1", "-uall"):
                return " M owned.txt"
            raise AssertionError(args)

        with patch.object(self.issuer, "_registered_alias", return_value=entry), \
                patch("runtime.orchestrator.gate_approval_issuance.load_project_mapping", return_value=mapping), \
                patch("runtime.orchestrator.gate_approval_issuance.validate_mapping_sources", return_value=[]), \
                patch("runtime.orchestrator.gate_approval_issuance.load_gate_plan", return_value=plan), \
                patch("runtime.orchestrator.gate_approval_issuance._validate_gate_requirement_artifacts"), \
                patch.object(self.issuer, "_git", side_effect=git_recovery), \
                patch.object(self.issuer, "_verified_recovery_renewal", return_value=recovery) as verify:
            recovery_binding, recovery_digest = GateApprovalIssuer._preflight(self.issuer, request)
        self.assertEqual(recovery_binding["recovery_renewal"], recovery)
        self.assertEqual(recovery_digest, _sha(recovery_binding))
        verify.assert_called_once()

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

    def test_exact_owner_approval_accepts_transport_crlf_without_mutating_raw_evidence(self) -> None:
        raw = dict(self.raw, mode="ISSUE", preflight_digest=self.digest,
                   owner_approval_comment_id=123)
        request = GateApprovalIssuanceRequest.from_mapping(raw)
        lf_body = "OCP_GATE_OWNER_APPROVAL_V1\n" + _canonical({
            "approval_ref": request.approval_ref, "preflight_digest": self.digest,
            "request_id": request.request_id,
        }).decode("utf-8")
        base = {"id": 123, "user": {"id": 235775273},
                   "created_at": "2026-09-29T00:00:00Z", "updated_at": "2026-09-29T00:00:00Z",
                   "performed_via_github_app": None}
        crlf_body = lf_body.replace("\n", "\r\n")
        cr_body = lf_body.replace("\n", "\r")

        for body in (lf_body, crlf_body, cr_body):
            comment = dict(base, body=body)
            GateApprovalIssuer._verify_owner_comment(request, self.digest, comment, "235775273")
            self.assertEqual(comment["body"], body)
        self.assertEqual(_canonicalize_newlines(lf_body), _canonicalize_newlines(crlf_body))
        self.assertEqual(_canonicalize_newlines(lf_body), _canonicalize_newlines(cr_body))

        invalid_comments = (
            dict(base, body=lf_body.replace("APPROVAL", "APPROVaL", 1)),
            dict(base, body=lf_body + " "),
            dict(base, body=lf_body.replace("\n", "\n ", 1)),
            dict(base, body=lf_body, user={"id": 999}),
            dict(base, body=lf_body, updated_at="2026-09-29T00:00:01Z"),
        )
        for comment in invalid_comments:
            with self.assertRaisesRegex(GateApprovalIssuanceError, "EXACT_OWNER_APPROVAL_REQUIRED"):
                GateApprovalIssuer._verify_owner_comment(request, self.digest, comment, "235775273")
        with self.assertRaisesRegex(GateApprovalIssuanceError, "EXACT_OWNER_APPROVAL_REQUIRED"):
            GateApprovalIssuer._verify_owner_comment(request, "f" * 64,
                                                     dict(base, body=lf_body), "235775273")


if __name__ == "__main__":
    unittest.main()

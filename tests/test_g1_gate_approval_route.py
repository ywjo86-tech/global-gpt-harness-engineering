from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from runtime.orchestrator.gate_approval_issuance import (
    GateApprovalIssuer,
    GateApprovalIssuanceError,
    GateApprovalIssuanceRequest,
    _canonical,
    _sha,
)
from runtime.orchestrator.g1_gate_approval_route import (
    G1_GATE_APPROVAL_PROFILE,
    G1GateApprovalIssuer,
    OwnerAuditAnchorError,
)
from runtime.orchestrator.task_contract_compat import resolve_task_project_requirement_contract


def _request(**changes):
    now = datetime.now(timezone.utc)
    issued = (now - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expires = (now + timedelta(minutes=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw = {
        "schema_version": "orchestration.gate-approval-issuance-request.v1",
        "request_id": "G1-REQ-20261023-001",
        "project_alias": G1_GATE_APPROVAL_PROFILE.project_alias,
        "gate_id": G1_GATE_APPROVAL_PROFILE.gate_id,
        "expected_branch": G1_GATE_APPROVAL_PROFILE.expected_branch,
        "expected_head": G1_GATE_APPROVAL_PROFILE.expected_head,
        "requirements_sha256": G1_GATE_APPROVAL_PROFILE.requirements_sha256,
        "approval_id": "G1-APPROVAL-20261023-001",
        "approval_ref": "G1-OWNER-APPROVAL-001",
        "issued_at": issued,
        "expires_at": expires,
        "mode": "DRY_RUN",
        "preflight_digest": None,
        "owner_approval_comment_id": None,
        "engine_requirement_evidence": None,
        "project_requirement_evidence_by_lv": [{
            "lv_id": G1_GATE_APPROVAL_PROFILE.project_requirement_lv_id,
            "path": G1_GATE_APPROVAL_PROFILE.project_requirement_evidence_path,
            "sha256": G1_GATE_APPROVAL_PROFILE.project_requirement_evidence_sha256,
        }],
    }
    raw.update(changes)
    return GateApprovalIssuanceRequest.from_mapping(raw)


def _valid_anchor_snapshot():
    profile = G1_GATE_APPROVAL_PROFILE
    return {
        "global_owner_head": {
            "schema_version": "orchestration.ai-office-owner-authority-anchor.v1",
            "generation": profile.global_owner_generation,
            "change_id": profile.global_owner_change_id,
            "event_sha256": profile.global_owner_event_sha256,
        },
        "project_owner_binding_head": {
            "schema_version": "orchestration.project-owner-binding-anchor.v2",
            "project_id": profile.project_id,
            "generation": profile.project_owner_generation,
            "change_id": profile.project_owner_change_id,
            "event_sha256": profile.project_owner_event_sha256,
        },
    }


class _AnchorReader:
    def __init__(self, value=None):
        self.value = value or _valid_anchor_snapshot()
        self.calls = []

    def read_owner_authority(self, project_id):
        self.calls.append(project_id)
        return self.value


class G1GateApprovalRouteTests(unittest.TestCase):
    def setUp(self):
        self.anchor_reader = _AnchorReader()
        self.issuer = object.__new__(G1GateApprovalIssuer)
        self.issuer.owner_anchor_reader = self.anchor_reader
        self.issuer.profile = G1_GATE_APPROVAL_PROFILE
        self.binding = {
            "project_alias": G1_GATE_APPROVAL_PROFILE.project_alias,
            "project_root": "/isolated/g1-source",
            "mapping_root": "/isolated/mappings",
            "source_head": G1_GATE_APPROVAL_PROFILE.expected_head,
            "approval_ref": "G1-OWNER-APPROVAL-001",
            "evidence": {
                "payload": {
                    "project_id": G1_GATE_APPROVAL_PROFILE.project_id,
                    "gate_id": G1_GATE_APPROVAL_PROFILE.gate_id,
                    "requirements_sha256": G1_GATE_APPROVAL_PROFILE.requirements_sha256,
                    "plan_sha256": G1_GATE_APPROVAL_PROFILE.plan_sha256,
                    "branch": G1_GATE_APPROVAL_PROFILE.expected_branch,
                    "head": G1_GATE_APPROVAL_PROFILE.expected_head,
                },
                "record_hash": "f" * 64,
            },
        }

    def test_g1_preflight_binds_exact_profile_and_owner_anchor_heads(self):
        request = _request()
        with patch.object(GateApprovalIssuer, "_preflight", return_value=(self.binding, _sha(self.binding))) as preflight:
            binding, digest = self.issuer._preflight(request)

        preflight.assert_called_once_with(request)
        self.assertEqual(binding["owner_authority_anchor"], _valid_anchor_snapshot())
        self.assertEqual(digest, _sha(binding))
        self.assertEqual(self.anchor_reader.calls, [G1_GATE_APPROVAL_PROFILE.project_id])

    def test_g1_preflight_rejects_alias_gate_branch_head_or_requirements_drift_before_registry_read(self):
        variants = (
            {"project_alias": "ocp-rdc-exec-canary-20260923-r2"},
            {"gate_id": "GATE-003"},
            {"expected_branch": "g3/revision-5-contract-20261022"},
            {"expected_head": "6" * 40},
            {"requirements_sha256": "e" * 64},
            {"project_requirement_evidence_by_lv": []},
            {"project_requirement_evidence_by_lv": [{
                "lv_id": "TASK-001",
                "path": "docs/another-requirements.json",
                "sha256": "0119f3527f3987eeb4337e7a8c459516d33fb7a077180f448ae49d4a9898b001",
            }]},
            {"project_requirement_evidence_by_lv": [{
                "lv_id": "TASK-001",
                "path": "docs/req-task-001.json",
                "sha256": "f" * 64,
            }]},
        )
        for change in variants:
            with self.subTest(change=change):
                self.anchor_reader.calls.clear()
                with patch.object(
                    GateApprovalIssuer,
                    "_preflight",
                    return_value=(self.binding, _sha(self.binding)),
                ) as preflight:
                    with self.assertRaisesRegex(GateApprovalIssuanceError, "G1_REQUEST_BINDING_MISMATCH"):
                        self.issuer._preflight(_request(**change))
                preflight.assert_not_called()
                self.assertEqual(self.anchor_reader.calls, [])

    def test_g1_preflight_rejects_plan_and_project_mismatch_from_registered_source(self):
        for key, value in (("plan_sha256", "d" * 64), ("project_id", "SOME-OTHER-PROJECT")):
            with self.subTest(key=key):
                binding = {
                    **self.binding,
                    "evidence": {
                        **self.binding["evidence"],
                        "payload": {**self.binding["evidence"]["payload"], key: value},
                    },
                }
                with patch.object(GateApprovalIssuer, "_preflight", return_value=(binding, _sha(binding))):
                    with self.assertRaisesRegex(GateApprovalIssuanceError, "G1_SOURCE_BINDING_MISMATCH"):
                        self.issuer._preflight(_request())

    def test_real_issuer_preflight_validates_the_pinned_committed_requirement_artifact(self):
        plan_text = """# OCP RDC-independent executable Full Plan canary R2

## TASK-001 — bounded source effect with sealed validation
Purpose: Prove RDC-independent governed execution by replacing only `canary.txt` with the exact approved value while preserving the sealed validation test unchanged.
Related Requirements: NFR-001
Dependencies: NONE
Change Targets: CT-001, CT-002
Required Capabilities: reasoning, filesystem_write, shell, test, git, implementation
Validation: TEST-001
Completion Condition: `canary.txt` contains exactly `rdc-independent-full-plan-canary-pass` followed by one newline, `tests/test_canary.py` remains byte-identical to the approved baseline, and no other file is modified.

## SOURCE Change Targets
| Target ID | Path / Module | Action | Related Task | Verification |
|---|---|---|---|---|
| CT-001 | `canary.txt` | MODIFY | TASK-001 | TEST-001 |
| CT-002 | `tests/test_canary.py` | VERIFY_ONLY | TASK-001 | TEST-001 |

## SOURCE Task Dependencies
| Task | Dependency Type | Depends On | Reason |
|---|---|---|---|
| TASK-001 | SEQUENTIAL | NONE | Entry |

## GATE-001 — executable canary R2
Required Tasks: TASK-001

| ID | Requirement | Acceptance | Priority |
|---|---|---|---|
| NFR-001 | Keep the live canary bounded and local. | Only `canary.txt` changes to the exact approved value; the validation test remains unchanged and external effects are forbidden. | MUST |
"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            docs = source / "docs"
            tests = source / "tests"
            docs.mkdir(parents=True)
            tests.mkdir()
            plan_path = source / "IMPLEMENTATION_PLAN.md"
            plan_path.write_text(plan_text, encoding="utf-8")
            (source / "canary.txt").write_text("initial\n", encoding="utf-8")
            (tests / "test_canary.py").write_text("# fixture\n", encoding="utf-8")

            plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            owned_files = ["canary.txt", "tests/test_canary.py"]
            contract = resolve_task_project_requirement_contract(
                plan_text,
                project_id=G1_GATE_APPROVAL_PROFILE.project_id,
                canonical_plan_sha256=plan_sha,
                gate_id=G1_GATE_APPROVAL_PROFILE.gate_id,
                task_id="TASK-001",
                owned_files=owned_files,
            )
            requirement_path = docs / "req-task-001.json"
            requirement_path.write_text(
                json.dumps(contract, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            requirement_sha = hashlib.sha256(requirement_path.read_bytes()).hexdigest()

            subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "approved fixture"],
                cwd=source,
                check=True,
                capture_output=True,
            )
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True,
            ).stdout.strip()
            profile = replace(
                G1_GATE_APPROVAL_PROFILE,
                expected_head=head,
                plan_sha256=plan_sha,
                project_requirement_evidence_sha256=requirement_sha,
            )

            authority = root / "authority"
            (authority / "aliases").mkdir(parents=True)
            mapping_root = authority / "mappings"
            mapping_root.mkdir()
            harness_root = root / "harness"
            harness_root.mkdir()
            issuer = G1GateApprovalIssuer(
                registry_root=authority,
                mapping_root=mapping_root,
                harness_state_root=harness_root,
                owner_anchor_reader=self.anchor_reader,
                profile=profile,
            )
            request = _request(
                expected_head=head,
                project_requirement_evidence_by_lv=[{
                    "lv_id": profile.project_requirement_lv_id,
                    "path": profile.project_requirement_evidence_path,
                    "sha256": profile.project_requirement_evidence_sha256,
                }],
            )
            mapping = SimpleNamespace(
                canonical_source=plan_path,
                canonical_sha256=plan_sha,
                task_lv_projection_path="docs/task-lv-projection.json",
            )
            plan = SimpleNamespace(
                project_id=profile.project_id,
                gate_id=profile.gate_id,
                canonical_plan_sha256=plan_sha,
                canonical_plan_path="IMPLEMENTATION_PLAN.md",
                lvs=(SimpleNamespace(lv_id="TASK-001", owned_files=owned_files),),
            )
            with (
                patch.object(
                    GateApprovalIssuer,
                    "_registered_alias",
                    return_value={"project_root": str(source), "project_id": profile.project_id},
                ),
                patch("runtime.orchestrator.gate_approval_issuance.load_project_mapping", return_value=mapping),
                patch("runtime.orchestrator.gate_approval_issuance.validate_mapping_sources", return_value=[]),
                patch("runtime.orchestrator.gate_approval_issuance.load_gate_plan", return_value=plan),
            ):
                binding, digest = issuer._preflight(request)

        self.assertEqual(binding["evidence"]["payload"]["head"], head)
        self.assertEqual(binding["evidence"]["payload"]["plan_sha256"], plan_sha)
        self.assertEqual(digest, _sha(binding))

    def test_g1_preflight_fails_closed_when_independent_owner_anchor_changes(self):
        snapshot = _valid_anchor_snapshot()
        snapshot["project_owner_binding_head"]["event_sha256"] = "a" * 64
        self.anchor_reader.value = snapshot
        with patch.object(GateApprovalIssuer, "_preflight") as preflight:
            with self.assertRaises(OwnerAuditAnchorError):
                self.issuer._preflight(_request())
        preflight.assert_not_called()

    def test_issue_requires_the_anchored_global_owner_actor(self):
        request = _request(mode="ISSUE", preflight_digest="a" * 64, owner_approval_comment_id=123)
        with patch.object(GateApprovalIssuer, "execute") as execute:
            with self.assertRaisesRegex(GateApprovalIssuanceError, "OWNER_AUTHORITY_MISMATCH"):
                self.issuer.execute(request, owner_actor_id="999", owner_approval_comment={})
        execute.assert_not_called()

    def test_exact_owner_comment_issues_request_scoped_g1_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            self.issuer.state_root = Path(td)
            dry_run_request = _request()
            with patch.object(
                GateApprovalIssuer,
                "_preflight",
                return_value=(self.binding, _sha(self.binding)),
            ):
                dry_run = self.issuer.execute(
                    dry_run_request,
                    owner_actor_id=G1_GATE_APPROVAL_PROFILE.owner_actor_id,
                )
                issue_raw = dry_run_request.to_dict()
                issue_raw.update({
                    "mode": "ISSUE",
                    "preflight_digest": dry_run["preflight_digest"],
                    "owner_approval_comment_id": 123,
                })
                issue_request = GateApprovalIssuanceRequest.from_mapping(issue_raw)
                body = "OCP_GATE_OWNER_APPROVAL_V1\n" + _canonical({
                    "approval_ref": issue_request.approval_ref,
                    "preflight_digest": dry_run["preflight_digest"],
                    "request_id": issue_request.request_id,
                }).decode("utf-8")
                comment = {
                    "id": 123,
                    "user": {"id": G1_GATE_APPROVAL_PROFILE.owner_actor_id},
                    "body": body,
                    "created_at": "2026-10-23T00:00:00Z",
                    "updated_at": "2026-10-23T00:00:00Z",
                    "performed_via_github_app": None,
                }
                issued = self.issuer.execute(
                    issue_request,
                    owner_approval_comment=comment,
                    owner_actor_id=G1_GATE_APPROVAL_PROFILE.owner_actor_id,
                )

            self.assertEqual(dry_run["status"], "PREFLIGHT_READY")
            self.assertFalse(dry_run["mutation_performed"])
            self.assertEqual(issued["status"], "ISSUED")
            self.assertEqual(issued["preflight_digest"], dry_run["preflight_digest"])
            self.assertEqual(issued["owner_authority_anchor"], _valid_anchor_snapshot())
            self.assertTrue(issued["mutation_performed"])
            approval = Path(td) / "_workspace" / "global-gate" / G1_GATE_APPROVAL_PROFILE.project_id / "approval" / f"{issue_request.request_id}.json"
            self.assertTrue(approval.is_file())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.tool_authorization import TOOL_AUTH_CONTRACT_VERSION, ToolAuthorizationContract
from runtime.full_mcp.contracts import (
    GIT_COMMIT_INTENT_SCHEMA_V1, GIT_PUBLICATION_AUTH_SCHEMA_V1, GIT_PUSH_INTENT_SCHEMA_V1,
    GIT_STAGE_INTENT_SCHEMA_V1, INVOCATION_CONTEXT_SCHEMA_V2,
    GitPublicationAuthorizationV1, InvocationContext, scope_digest,
)
from runtime.full_mcp.git_service import GitService, GitServiceError
from runtime.full_mcp.path_policy import WorkspacePathPolicy
from runtime.full_mcp.runtime import build_default_runtime, operation_definitions
from runtime.full_mcp.validation_profiles import default_validation_catalog

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _meta(context: InvocationContext, request_id: str) -> dict[str, str]:
    return {
        "gch/full-mcp/invocation_context_id": context.invocation_context_id,
        "gch/full-mcp/request_digest": context.request_digest,
        "gch/full-mcp/correlation_id": context.correlation_id,
        "gch/full-mcp/operation_request_id": request_id,
    }


class FullMCPPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.remote_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); self.remote = Path(self.remote_temp.name) / "remote.git"
        subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=self.root)
        subprocess.check_call(["git", "config", "user.email", "publication@example.invalid"], cwd=self.root)
        subprocess.check_call(["git", "config", "user.name", "Publication Test"], cwd=self.root)
        (self.root / "owned").mkdir(); (self.root / "owned/a.txt").write_text("base\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "owned/a.txt"], cwd=self.root)
        subprocess.check_call(["git", "commit", "-qm", "baseline"], cwd=self.root)
        subprocess.check_call(["git", "init", "--bare", "-q", str(self.remote)])
        subprocess.check_call(["git", "remote", "add", "origin", str(self.remote)], cwd=self.root)
        subprocess.check_call(["git", "push", "-q", "-u", "origin", "main"], cwd=self.root)
        self.baseline = _git(self.root, "rev-parse", "HEAD")
        self.path_policy = WorkspacePathPolicy(self.root.resolve(), read_scopes=(".",), mutable_scopes=("owned",))
        probe = GitService(self.root.resolve(), self.path_policy)
        self.authorization = GitPublicationAuthorizationV1(
            schema_version=GIT_PUBLICATION_AUTH_SCHEMA_V1,
            repository_identity_digest=probe.repository_identity_digest(), approved_branch="main", approved_remote="origin",
            remote_url_fingerprint=probe.remote_url_fingerprint("origin"),
            allowed_path_digest=scope_digest(("owned/a.txt",)), expected_remote_head=self.baseline,
            protected_branch_policy_ref="ALLOW-APPROVED-NONFORCE", approval_ref="APPROVAL-TASK005",
            issued_at="2026-09-17T00:00:00Z", expires_at="2026-09-18T00:00:00Z",
        )
        catalog = default_validation_catalog(); mutable = ("owned",); mutable_digest = scope_digest(mutable)
        contracts = []
        for operation in operation_definitions(include_publication=True):
            contracts.append(ToolAuthorizationContract(
                contract_id="TAC-" + operation.operation_class_id.upper().replace("_", "-"),
                contract_version=TOOL_AUTH_CONTRACT_VERSION, contract_status="ACTIVE", worker_task_id="TASK-005",
                requirement_refs=("REQ-006",), plan_task_refs=("TASK-005",), operation_class_id=operation.operation_class_id,
                capability_class=operation.capability_class, operation_intent=operation.operation_intent,
                requirement_binding="REQUIRED", scope_binding="IN_SCOPE", scope_authorization_source="USER_DECISION",
                authorization_decision_ref="DEC-TASK005", validity_scope="TASK_ONLY",
                security_obligation_profile="SECRET_SCAN_REQUIRED", approval_authority="USER_DECISION",
                project_id="PREPH5MPRF", gate_id="GATE-003", lv_id="TASK-005", run_id="publication-test",
                canonical_plan_sha256=SHA_A, requirement_digest=SHA_B, owned_scope_sha256=mutable_digest,
                package_binding_sha256=SHA_C,
            ).sealed())
        self.context = InvocationContext(
            schema_version=INVOCATION_CONTEXT_SCHEMA_V2, project_id="PREPH5MPRF", run_id="publication-test",
            gate_id="GATE-003", lv_id="TASK-005", attempt=1, request_digest=SHA_C, correlation_id="corr-publication",
            workspace_root=self.root.resolve().as_posix(), canonical_plan_sha256=SHA_A, dependency_lock_sha256=SHA_C,
            authorization_contract_digests=tuple(c.contract_digest for c in contracts), read_scopes=(".",),
            mutable_scopes=mutable, read_scope_sha256=scope_digest((".",)), mutable_scope_sha256=mutable_digest,
            validation_profile_digests=catalog.digests(), operation_policy_digests=(self.authorization.policy_digest,),
        ).sealed()
        self.contracts = tuple(contracts); self.catalog = catalog
        self.runtime = build_default_runtime(
            self.context, self.contracts, catalog=catalog, publication_authorizations=(self.authorization,)
        )

    def tearDown(self) -> None:
        self.temp.cleanup(); self.remote_temp.cleanup()

    def _stage(self):
        (self.root / "owned/a.txt").write_text("changed\n", encoding="utf-8")
        preview = self.runtime.services.git.publication_preview(["owned/a.txt"])
        result = self.runtime.call("git_stage", {
            "intent_schema_version": GIT_STAGE_INTENT_SCHEMA_V1, "paths": ["owned/a.txt"],
            "expected_worktree_digest": preview["worktree_digest"], "expected_head": preview["head_sha"],
            "candidate_diff_digest": preview["candidate_diff_digest"],
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-stage"))
        self.assertEqual(result["status"], "COMPLETED", result)
        return result

    def test_closed_catalog_adds_exact_three_publication_operations_only_for_v2_authority(self):
        names = {item["name"] for item in self.runtime.tool_specs()}
        self.assertEqual(len(operation_definitions()), 14)
        self.assertTrue({"git_stage", "git_commit", "git_push"}.issubset(names))
        self.assertEqual(len(names), 17)
        self.assertFalse({"git_force", "git_reset", "git_rebase", "git_delete_ref"}.intersection(names))

    def test_stage_commit_push_happy_path_is_exact_bound_and_effect_recorded(self):
        stage = self._stage(); stage_data = stage["data"]
        commit = self.runtime.call("git_commit", {
            "intent_schema_version": GIT_COMMIT_INTENT_SCHEMA_V1,
            "expected_staged_diff_digest": stage_data["staged_diff_digest"],
            "expected_index_digest": stage_data["index_digest_after"], "expected_head": self.baseline,
            "expected_parent": self.baseline, "subject": "bounded publication",
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-commit"))
        self.assertEqual(commit["status"], "COMPLETED", commit)
        commit_sha = commit["data"]["commit_sha"]
        push = self.runtime.call("git_push", {
            "intent_schema_version": GIT_PUSH_INTENT_SCHEMA_V1, "remote": "origin", "branch": "main",
            "local_commit_sha": commit_sha, "expected_remote_head": self.baseline,
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-push"))
        self.assertEqual(push["status"], "COMPLETED", push)
        self.assertEqual(push["data"]["reconciliation_state"], "CONFIRMED")
        self.assertEqual(_git(self.remote, "rev-parse", "refs/heads/main"), commit_sha)
        for result in (stage, commit, push):
            self.assertTrue(result["effect_id"])
            self.assertEqual(len(result["data"]["publication_evidence"]["evidence_digest"]), 64)

    def test_wrong_publication_policy_or_scope_fails_closed(self):
        (self.root / "owned/a.txt").write_text("changed\n", encoding="utf-8")
        preview = self.runtime.services.git.publication_preview(["owned/a.txt"])
        bad = self.runtime.call("git_stage", {
            "intent_schema_version": GIT_STAGE_INTENT_SCHEMA_V1, "paths": ["owned/a.txt"],
            "expected_worktree_digest": preview["worktree_digest"], "expected_head": preview["head_sha"],
            "candidate_diff_digest": preview["candidate_diff_digest"], "publication_policy_digest": "0" * 64,
        }, _meta(self.context, "pub-bad-policy"))
        self.assertEqual(bad["status"], "BLOCKED")
        self.assertEqual(bad["error"]["code"], "AUTHORIZATION_DENIED")

    def test_stale_remote_head_blocks_push_without_remote_change(self):
        stage = self._stage(); data = stage["data"]
        commit = self.runtime.call("git_commit", {
            "intent_schema_version": GIT_COMMIT_INTENT_SCHEMA_V1,
            "expected_staged_diff_digest": data["staged_diff_digest"], "expected_index_digest": data["index_digest_after"],
            "expected_head": self.baseline, "expected_parent": self.baseline, "subject": "bounded publication",
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-commit-stale"))
        before = _git(self.remote, "rev-parse", "refs/heads/main")
        result = self.runtime.call("git_push", {
            "intent_schema_version": GIT_PUSH_INTENT_SCHEMA_V1, "remote": "origin", "branch": "main",
            "local_commit_sha": commit["data"]["commit_sha"], "expected_remote_head": "f" * 40,
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-push-stale"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"]["code"], "GIT_REMOTE_STALE")
        self.assertEqual(_git(self.remote, "rev-parse", "refs/heads/main"), before)

    def test_security_candidate_digest_mismatch_blocks_before_index_mutation(self):
        (self.root / "owned/a.txt").write_text("changed\n", encoding="utf-8")
        preview = self.runtime.services.git.publication_preview(["owned/a.txt"])
        before = self.runtime.services.git.publication_index_digest()
        result = self.runtime.call("git_stage", {
            "intent_schema_version": GIT_STAGE_INTENT_SCHEMA_V1, "paths": ["owned/a.txt"],
            "expected_worktree_digest": preview["worktree_digest"], "expected_head": preview["head_sha"],
            "candidate_diff_digest": "0" * 64, "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-candidate-drift"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"]["code"], "GIT_CANDIDATE_DRIFT")
        self.assertEqual(self.runtime.services.git.publication_index_digest(), before)

    def test_security_preexisting_index_delta_blocks_stage(self):
        (self.root / "owned/a.txt").write_text("changed\n", encoding="utf-8")
        preview = self.runtime.services.git.publication_preview(["owned/a.txt"])
        subprocess.check_call(["git", "add", "owned/a.txt"], cwd=self.root)
        result = self.runtime.call("git_stage", {
            "intent_schema_version": GIT_STAGE_INTENT_SCHEMA_V1, "paths": ["owned/a.txt"],
            "expected_worktree_digest": preview["worktree_digest"], "expected_head": preview["head_sha"],
            "candidate_diff_digest": preview["candidate_diff_digest"],
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-index-dirty"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"]["code"], "GIT_INDEX_NOT_CLEAN")

    def test_security_protected_branch_policy_without_allow_prefix_blocks_before_mutation(self):
        blocked_auth = replace(self.authorization, protected_branch_policy_ref="BLOCK-PROTECTED")
        context = replace(
            self.context, operation_policy_digests=(blocked_auth.policy_digest,), invocation_context_id=""
        ).sealed()
        runtime = build_default_runtime(
            context, self.contracts, catalog=self.catalog, publication_authorizations=(blocked_auth,)
        )
        (self.root / "owned/a.txt").write_text("changed\n", encoding="utf-8")
        preview = runtime.services.git.publication_preview(["owned/a.txt"])
        result = runtime.call("git_stage", {
            "intent_schema_version": GIT_STAGE_INTENT_SCHEMA_V1, "paths": ["owned/a.txt"],
            "expected_worktree_digest": preview["worktree_digest"], "expected_head": preview["head_sha"],
            "candidate_diff_digest": preview["candidate_diff_digest"],
            "publication_policy_digest": blocked_auth.policy_digest,
        }, _meta(context, "pub-protected"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["error"]["code"], "AUTHORIZATION_DENIED")
        self.assertEqual(runtime.services.git.publication_staged_paths(), [])

    def test_safety_non_fast_forward_is_blocked_before_push(self):
        stage = self._stage(); data = stage["data"]
        commit = self.runtime.call("git_commit", {
            "intent_schema_version": GIT_COMMIT_INTENT_SCHEMA_V1,
            "expected_staged_diff_digest": data["staged_diff_digest"], "expected_index_digest": data["index_digest_after"],
            "expected_head": self.baseline, "expected_parent": self.baseline, "subject": "bounded publication",
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-commit-nff"))
        service = self.runtime.services.git; real_run = service._run; pushes = []
        def controlled_run(args, *, allow_nonzero=False):
            if args and args[0] == "merge-base":
                return subprocess.CompletedProcess(["git", *args], 1, "", "")
            if args and args[0] == "push": pushes.append(tuple(args))
            return real_run(args, allow_nonzero=allow_nonzero)
        with patch.object(service, "_run", side_effect=controlled_run):
            with self.assertRaises(GitServiceError) as caught:
                service.push_publication(remote="origin", branch="main", local_commit_sha=commit["data"]["commit_sha"], expected_remote_head=self.baseline)
        self.assertEqual(caught.exception.code, "GIT_NON_FAST_FORWARD")
        self.assertEqual(pushes, [])

    def test_safety_ambiguous_push_reconciles_once_and_never_auto_replays(self):
        stage = self._stage(); data = stage["data"]
        commit = self.runtime.call("git_commit", {
            "intent_schema_version": GIT_COMMIT_INTENT_SCHEMA_V1,
            "expected_staged_diff_digest": data["staged_diff_digest"], "expected_index_digest": data["index_digest_after"],
            "expected_head": self.baseline, "expected_parent": self.baseline, "subject": "bounded publication",
            "publication_policy_digest": self.authorization.policy_digest,
        }, _meta(self.context, "pub-commit-amb"))
        service = self.runtime.services.git; real_run = service._run; push_count = 0
        def controlled_run(args, *, allow_nonzero=False):
            nonlocal push_count
            if args and args[0] == "push":
                push_count += 1
                return subprocess.CompletedProcess(["git", *args], 1, "", "transport failure")
            return real_run(args, allow_nonzero=allow_nonzero)
        with patch.object(service, "_run", side_effect=controlled_run), patch.object(
            service, "remote_head", side_effect=[self.baseline, "f" * 40]
        ):
            with self.assertRaises(GitServiceError) as caught:
                service.push_publication(remote="origin", branch="main", local_commit_sha=commit["data"]["commit_sha"], expected_remote_head=self.baseline)
        self.assertEqual(caught.exception.code, "ACTION_SIDE_EFFECT_AMBIGUOUS")
        self.assertEqual(push_count, 1)


if __name__ == "__main__":
    unittest.main()

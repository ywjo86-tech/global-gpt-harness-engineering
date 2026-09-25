from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator import successor_release_staging as api


BASE_REQUEST = {
    "request_id": "stage-p2-fence-001",
    "schema_version": "orchestration.successor-release-stage-request.v1",
    "project_alias": "successor-p2",
    "expected_branch": "stable",
    "expected_head": "a" * 40,
    "target_ref": "refs/heads/release",
    "target_head": "b" * 40,
    "successor_profile": "lifecycle-v2-p2",
    "approval_policy_ref": "P2-SUCCESSOR-STAGE",
    "approval_policy_digest": "c" * 64,
    "mode": "DRY_RUN",
    "preflight_digest": None,
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


class FencingFullMcp:
    def __init__(self, *, branch: str, head: str, remote_head: str) -> None:
        self.current_branch = branch
        self.current_head = head
        self.remote_head = remote_head
        self.object_present = False
        self.ancestor = True
        self.calls: list[tuple] = []
        self.head_calls = 0
        self.status_calls = 0
        self.drift_head_after_call: int | None = None
        self.dirty_status_after_call: int | None = None

    def status(self, root: Path) -> str:
        self.calls.append(("status", root))
        self.status_calls += 1
        if (
            self.dirty_status_after_call is not None
            and self.status_calls >= self.dirty_status_after_call
        ):
            return " M payload.txt"
        return ""

    def branch(self, root: Path) -> str:
        self.calls.append(("branch", root))
        return self.current_branch

    def head(self, root: Path) -> str:
        self.calls.append(("head", root))
        self.head_calls += 1
        if (
            self.drift_head_after_call is not None
            and self.head_calls >= self.drift_head_after_call
        ):
            return "f" * 40
        return self.current_head

    def ls_remote(self, root: Path, target_ref: str) -> list[str]:
        self.calls.append(("ls_remote", root, target_ref))
        return [self.remote_head]

    def object_exists(self, root: Path, sha: str) -> bool:
        self.calls.append(("object_exists", root, sha))
        return self.object_present

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", root, ancestor, descendant))
        return self.ancestor

    def fetch_target(self, root: Path, target_ref: str, temporary_ref: str) -> str:
        self.calls.append(("fetch_target", root, target_ref, temporary_ref))
        self.object_present = True
        return self.remote_head

    def fast_forward_current(self, root: Path, target_head: str) -> str:
        self.calls.append(("fast_forward_current", root, target_head))
        self.current_head = target_head
        return target_head

    def delete_temporary_ref(self, root: Path, temporary_ref: str) -> None:
        self.calls.append(("delete_temporary_ref", root, temporary_ref))


class SuccessorReleaseStageFencingTests(unittest.TestCase):
    def _fixture(self, root: Path):
        remote = root / "remote.git"
        source = root / "source"
        target = root / "successor-project"
        registry_root = root / "registry" / "aliases"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        source.mkdir()
        git(source, "init", "-b", "stable")
        git(source, "config", "user.name", "Test")
        git(source, "config", "user.email", "test@example.invalid")
        (source / "IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
        (source / "payload.txt").write_text("v1\n", encoding="utf-8")
        git(source, "add", ".")
        git(source, "commit", "-m", "base")
        base = git(source, "rev-parse", "HEAD")
        git(source, "remote", "add", "origin", str(remote))
        git(source, "push", "origin", "stable")
        git(source, "checkout", "-b", "release")
        (source / "payload.txt").write_text("v2\n", encoding="utf-8")
        git(source, "commit", "-am", "release")
        release = git(source, "rev-parse", "HEAD")
        git(source, "push", "origin", "release")
        subprocess.run(
            ["git", "clone", "--branch", "stable", str(remote), str(target)],
            check=True,
            capture_output=True,
        )
        registry = OnboardingRegistry(registry_root)
        registry.register(target, "successor-p2")
        serving = root / "serving-runtime"
        serving.mkdir()
        return registry, target, base, release, serving

    def _request(self, base: str, release: str, **overrides):
        return api.SuccessorReleaseStageRequest.from_mapping(
            {
                **BASE_REQUEST,
                "expected_head": base,
                "target_head": release,
                **overrides,
            }
        )

    def _stage(self, dry, preflight):
        return api.SuccessorReleaseStageRequest.from_mapping(
            {
                **dry.to_dict(),
                "mode": "STAGE",
                "preflight_digest": preflight["preflight_digest"],
            }
        )

    def _stager(self, registry, serving, full_mcp, lock_root):
        return api.SuccessorReleaseStager(
            registry,
            full_mcp=full_mcp,
            lifecycle_identity_provider=lambda: api.SuccessorLifecycleIdentity(
                serving_root=serving,
                predecessor_root=None,
            ),
            lock_root=lock_root,
        )

    def test_existing_successor_lock_rejects_stage_before_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, serving = self._fixture(root)
            lock_root = root / "locks"
            lock_root.mkdir()
            full_mcp = FencingFullMcp(branch="stable", head=base, remote_head=release)
            stager = self._stager(registry, serving, full_mcp, lock_root)
            dry = self._request(base, release)
            preflight = stager.execute(dry)

            lock_key = hashlib.sha256(
                f"{project.resolve()}\0successor-p2".encode("utf-8")
            ).hexdigest()
            (lock_root / f"{lock_key}.lock").write_text("held\n", encoding="utf-8")

            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_BEFORE_MUTATION")
            self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertEqual(full_mcp.current_head, base)

    def test_post_lock_head_drift_rejects_before_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _project, base, release, serving = self._fixture(root)
            lock_root = root / "locks"
            full_mcp = FencingFullMcp(branch="stable", head=base, remote_head=release)
            stager = self._stager(registry, serving, full_mcp, lock_root)
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            # DRY_RUN head call=1, STAGE initial validation=2, post-lock fence=3.
            full_mcp.drift_head_after_call = 3

            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_BEFORE_MUTATION")
            self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertEqual(full_mcp.current_head, base)

    def test_post_fetch_worktree_drift_rejects_before_fast_forward(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _project, base, release, serving = self._fixture(root)
            lock_root = root / "locks"
            full_mcp = FencingFullMcp(branch="stable", head=base, remote_head=release)
            stager = self._stager(registry, serving, full_mcp, lock_root)
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            # DRY_RUN status=1, STAGE initial=2, post-lock=3, post-fetch=4.
            full_mcp.dirty_status_after_call = 4

            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_FETCH")
            self.assertIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])
            self.assertEqual(full_mcp.current_head, base)


if __name__ == "__main__":
    unittest.main()

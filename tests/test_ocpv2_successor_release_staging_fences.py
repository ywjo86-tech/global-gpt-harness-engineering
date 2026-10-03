from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator import successor_release_staging as api
from tests.test_ocpv2_successor_release_staging import RecordingFullMcp


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


class DriftAfterFetchFullMcp(RecordingFullMcp):
    def __init__(self, *args, drift_head: str | None = None, drift_branch: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.drift_head = drift_head
        self.drift_branch = drift_branch

    def fetch_target(self, root: Path, target_ref: str, temporary_ref: str) -> str:
        fetched = super().fetch_target(root, target_ref, temporary_ref)
        if self.drift_head is not None:
            self.current_head = self.drift_head
        if self.drift_branch is not None:
            self.current_branch = self.drift_branch
        return fetched


class SuccessorStageFenceTests(unittest.TestCase):
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
        lifecycle = lambda: api.SuccessorLifecycleIdentity(
            serving_root=serving,
            predecessor_root=None,
        )
        return registry, target, base, release, lifecycle

    def _dry(self, base: str, release: str, *, request_id: str = "stage-p2-fence-001"):
        return api.SuccessorReleaseStageRequest.from_mapping(
            {
                **BASE_REQUEST,
                "request_id": request_id,
                "expected_head": base,
                "target_head": release,
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

    def test_lock_contention_rejects_stage_before_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, lifecycle = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable", head=base, remote_heads=[release]
            )
            lock_root = root / "locks"
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=lifecycle,
                lock_root=lock_root,
            )
            dry = self._dry(base, release)
            preflight = stager.execute(dry)
            stage = self._stage(dry, preflight)
            with api.SuccessorStageLock(lock_root, "successor-p2", project.resolve()):
                with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                    stager.execute(stage)
            self.assertEqual(raised.exception.outcome, "FAILED_BEFORE_MUTATION")
            self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertEqual(full_mcp.current_head, base)

    def test_toctou_head_drift_after_fetch_blocks_fast_forward(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _, base, release, lifecycle = self._fixture(root)
            full_mcp = DriftAfterFetchFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head=release,
                drift_head="d" * 40,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=lifecycle,
                lock_root=root / "locks",
            )
            dry = self._dry(base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_FETCH")
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])
            self.assertEqual(full_mcp.current_head, "d" * 40)

    def test_toctou_branch_drift_after_fetch_blocks_fast_forward(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _, base, release, lifecycle = self._fixture(root)
            full_mcp = DriftAfterFetchFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head=release,
                drift_branch="other",
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=lifecycle,
                lock_root=root / "locks",
            )
            dry = self._dry(base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_FETCH")
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])

    def test_failed_after_git_advance_preserves_approved_target_and_never_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _, base, release, lifecycle = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head=release,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=lifecycle,
                lock_root=root / "locks",
            )
            dry = self._dry(base, release)
            preflight = stager.execute(dry)
            stage = self._stage(dry, preflight)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(stage)
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_GIT_ADVANCE")
            self.assertEqual(full_mcp.current_head, release)
            call_names = [call[0] for call in full_mcp.calls]
            self.assertNotIn("reset", call_names)
            self.assertNotIn("checkout", call_names)
            self.assertNotIn("rebase", call_names)

            fetch_count = call_names.count("fetch_target")
            with self.assertRaises(api.SuccessorReleaseStageError) as replayed:
                stager.execute(stage)
            self.assertEqual(replayed.exception.outcome, "FAILED_BEFORE_MUTATION")
            self.assertEqual(
                [call[0] for call in full_mcp.calls].count("fetch_target"),
                fetch_count,
            )
            self.assertEqual(full_mcp.current_head, release)

    def test_failed_after_advance_requires_new_admission_bound_to_current_head(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _, base, release, lifecycle = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head=release,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=lifecycle,
                lock_root=root / "locks",
            )
            dry = self._dry(base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(full_mcp.current_head, release)

            recovery = self._dry(
                release,
                release,
                request_id="stage-p2-fence-recovery-002",
            )
            recovery_preflight = stager.execute(recovery)
            self.assertEqual(recovery_preflight["status"], "STAGE_READY")
            self.assertEqual(recovery_preflight["ancestry_state"], "PROVEN_FAST_FORWARD")


if __name__ == "__main__":
    unittest.main()

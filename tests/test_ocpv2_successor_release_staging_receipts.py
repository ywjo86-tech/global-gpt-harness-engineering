from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator import successor_release_staging as api


BASE_REQUEST = {
    "request_id": "stage-p2-receipt-001",
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


class CountingFullMcp:
    def __init__(self, *, branch: str, head: str, remote_head: str) -> None:
        self.current_branch = branch
        self.current_head = head
        self.remote_head = remote_head
        self.object_present = False
        self.calls: list[tuple] = []

    def status(self, root: Path) -> str:
        self.calls.append(("status", root))
        return ""

    def branch(self, root: Path) -> str:
        self.calls.append(("branch", root))
        return self.current_branch

    def head(self, root: Path) -> str:
        self.calls.append(("head", root))
        return self.current_head

    def ls_remote(self, root: Path, target_ref: str) -> list[str]:
        self.calls.append(("ls_remote", root, target_ref))
        return [self.remote_head]

    def object_exists(self, root: Path, sha: str) -> bool:
        self.calls.append(("object_exists", root, sha))
        return self.object_present or sha == self.current_head

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", root, ancestor, descendant))
        return True

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


class InertProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def observe(self, profile: str):
        self.calls.append(profile)
        return {
            "service_active": False,
            "service_enabled": False,
            "timer_active": False,
            "timer_enabled": False,
            "polling_enabled": False,
        }


class SuccessorReleaseReceiptTests(unittest.TestCase):
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
        cfg = root / "config"
        units = root / "units"
        cfg.mkdir()
        units.mkdir()
        (cfg / "ocpv2.env").write_text("serving-env\n", encoding="utf-8")
        (units / "ocpv2.service").write_text("serving-service\n", encoding="utf-8")
        (units / "ocpv2.timer").write_text("serving-timer\n", encoding="utf-8")

        lifecycle = lambda: api.SuccessorLifecycleIdentity(
            serving_root=serving,
            predecessor_root=None,
        )
        return registry, target, base, release, lifecycle, cfg, units

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

    @staticmethod
    def _artifact_writer(repo_root: Path, profile: str, cfg: Path, units: Path):
        paths = {
            "env_path": cfg / f"ocpv2-{profile}.env",
            "service_path": units / f"ocpv2-{profile}.service",
            "timer_path": units / f"ocpv2-{profile}.timer",
        }
        for path in paths.values():
            path.write_text("disabled\n", encoding="utf-8")
        return {key: str(path) for key, path in paths.items()}

    def _stager(self, registry, lifecycle, cfg, units, full_mcp, receipt_root):
        store = api.SuccessorReleaseReceiptStore(receipt_root)
        probe = InertProbe()
        stager = api.SuccessorReleaseStager(
            registry,
            full_mcp=full_mcp,
            lifecycle_identity_provider=lifecycle,
            receipt_store=store,
            lock_root=receipt_root.parent / "locks",
            stage_callback=self._artifact_writer,
            service_state_probe=probe,
            user_config_root=cfg,
            user_unit_root=units,
        )
        return store, probe, stager

    def test_receipt_store_is_create_once_canonical_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = api.SuccessorReleaseReceiptStore(root / "receipts")
            receipt = {
                "schema_version": "orchestration.successor-release-stage-receipt.v1",
                "phase_request_digest": "d" * 64,
                "request_id": "receipt-only-001",
                "mode": "DRY_RUN",
                "stage_intent_digest": "e" * 64,
                "preflight_digest": "f" * 64,
                "outcome": "STAGE_READY",
            }
            stored = store.append(receipt)
            self.assertEqual(stored, receipt)
            self.assertEqual(store.read_phase("d" * 64), receipt)
            path = root / "receipts" / f"{'d' * 64}.json"
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), api._canonical(receipt))

    def test_successful_stage_receipt_contains_complete_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, lifecycle, cfg, units = self._fixture(root)
            full_mcp = CountingFullMcp(branch="stable", head=base, remote_head=release)
            store, probe, stager = self._stager(
                registry, lifecycle, cfg, units, full_mcp, root / "receipts"
            )
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            stage = self._stage(dry, preflight)
            receipt = stager.execute(stage)

            required = {
                "schema_version",
                "request_id",
                "mode",
                "stage_intent_digest",
                "phase_request_digest",
                "preflight_digest",
                "project_alias",
                "canonical_successor_root",
                "approval_policy_ref",
                "approval_policy_digest",
                "expected_branch",
                "expected_head",
                "pre_head",
                "target_ref",
                "target_head",
                "remote_target_head",
                "fetched_sha",
                "ancestor_result",
                "fast_forward_result",
                "fetch_result",
                "branch_result",
                "post_head",
                "successor_artifact_hashes",
                "serving_artifact_hashes_before",
                "serving_artifact_hashes_after",
                "serving_runtime_identity_before",
                "serving_runtime_identity_after",
                "service_active",
                "service_enabled",
                "timer_active",
                "timer_enabled",
                "polling_enabled",
                "guard_results",
                "mutation_performed",
                "service_manager_invoked",
                "outcome",
                "status",
            }
            self.assertTrue(required.issubset(receipt))
            self.assertEqual(receipt["schema_version"], "orchestration.successor-release-stage-receipt.v1")
            self.assertEqual(receipt["outcome"], "STAGED")
            self.assertEqual(receipt["pre_head"], base)
            self.assertEqual(receipt["post_head"], release)
            self.assertEqual(receipt["remote_target_head"], release)
            self.assertEqual(receipt["fetched_sha"], release)
            self.assertTrue(receipt["ancestor_result"])
            self.assertTrue(receipt["fast_forward_result"])
            self.assertFalse(receipt["service_active"])
            self.assertFalse(receipt["service_enabled"])
            self.assertFalse(receipt["timer_active"])
            self.assertFalse(receipt["timer_enabled"])
            self.assertFalse(receipt["polling_enabled"])
            self.assertEqual(git(project, "rev-parse", "HEAD"), release)
            self.assertEqual(store.read_phase(stage.phase_request_digest), receipt)
            self.assertEqual(probe.calls, ["lifecycle-v2-p2"])

    def test_identical_stage_phase_replay_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _project, base, release, lifecycle, cfg, units = self._fixture(root)
            full_mcp = CountingFullMcp(branch="stable", head=base, remote_head=release)
            store, probe, stager = self._stager(
                registry, lifecycle, cfg, units, full_mcp, root / "receipts"
            )
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            stage = self._stage(dry, preflight)
            first = stager.execute(stage)
            calls_after_first = list(full_mcp.calls)
            probe_calls_after_first = list(probe.calls)
            second = stager.execute(stage)
            self.assertEqual(second, first)
            self.assertEqual(full_mcp.calls, calls_after_first)
            self.assertEqual(probe.calls, probe_calls_after_first)
            self.assertEqual(store.read_phase(stage.phase_request_digest), first)

    def test_new_stager_instance_recovers_durable_dry_run_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, _project, base, release, lifecycle, cfg, units = self._fixture(root)
            receipt_root = root / "receipts"
            full_mcp = CountingFullMcp(branch="stable", head=base, remote_head=release)
            _store1, _probe1, first = self._stager(
                registry, lifecycle, cfg, units, full_mcp, receipt_root
            )
            dry = self._request(base, release)
            preflight = first.execute(dry)

            _store2, _probe2, resumed = self._stager(
                registry, lifecycle, cfg, units, full_mcp, receipt_root
            )
            stage = self._stage(dry, preflight)
            result = resumed.execute(stage)
            self.assertEqual(result["outcome"], "STAGED")
            self.assertEqual(result["preflight_digest"], preflight["preflight_digest"])


if __name__ == "__main__":
    unittest.main()

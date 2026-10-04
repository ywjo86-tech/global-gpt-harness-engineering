from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator import successor_release_staging as api


BASE_REQUEST = {
    "request_id": "stage-p2-artifact-001",
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


class Probe:
    def __init__(self, **state: bool) -> None:
        self.state = {
            "service_active": False,
            "service_enabled": False,
            "timer_active": False,
            "timer_enabled": False,
            "polling_enabled": False,
            **state,
        }
        self.calls: list[str] = []

    def observe(self, profile: str):
        self.calls.append(profile)
        return dict(self.state)


class SuccessorArtifactStagingTests(unittest.TestCase):
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
        config_root = root / "config"
        unit_root = root / "units"
        config_root.mkdir()
        unit_root.mkdir()
        serving_files = {
            config_root / "ocpv2.env": "serving-env\n",
            unit_root / "ocpv2.service": "serving-service\n",
            unit_root / "ocpv2.timer": "serving-timer\n",
        }
        for path, text in serving_files.items():
            path.write_text(text, encoding="utf-8")
        lifecycle = lambda: api.SuccessorLifecycleIdentity(
            serving_root=serving,
            predecessor_root=None,
        )
        return registry, target, base, release, lifecycle, config_root, unit_root, serving_files

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

    def _callback(self, *, mutate_serving: Path | None = None, omit: str | None = None, calls=None):
        def stage(repo_root: Path, profile: str, cfg: Path, units: Path):
            if calls is not None:
                calls.append((repo_root, profile))
            if mutate_serving is not None:
                mutate_serving.write_text("MUTATED\n", encoding="utf-8")
            paths = {
                "env_path": cfg / f"ocpv2-{profile}.env",
                "service_path": units / f"ocpv2-{profile}.service",
                "timer_path": units / f"ocpv2-{profile}.timer",
            }
            for key, path in paths.items():
                if key != omit:
                    path.write_text(f"{key}:disabled\n", encoding="utf-8")
            return {key: str(path) for key, path in paths.items()}
        return stage

    def _stager(self, registry, lifecycle, config_root, unit_root, callback, probe):
        return api.SuccessorReleaseStager(
            registry,
            lifecycle_identity_provider=lifecycle,
            lock_root=config_root.parent / "locks",
            stage_callback=callback,
            service_state_probe=probe,
            user_config_root=config_root,
            user_unit_root=unit_root,
        )

    def test_happy_path_stages_only_successor_artifacts_and_remains_inert(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, lifecycle, cfg, units, serving = self._fixture(root)
            calls = []
            probe = Probe()
            stager = self._stager(registry, lifecycle, cfg, units, self._callback(calls=calls), probe)
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            result = stager.execute(self._stage(dry, preflight))
            self.assertEqual(result["status"], "STAGED")
            self.assertTrue(result["mutation_performed"])
            self.assertFalse(result["service_manager_invoked"])
            self.assertFalse(result["polling_enabled"])
            self.assertEqual(git(project, "rev-parse", "HEAD"), release)
            self.assertEqual(calls, [(project.resolve(), "lifecycle-v2-p2")])
            self.assertEqual(probe.calls, ["lifecycle-v2-p2"])
            for path, text in serving.items():
                self.assertEqual(path.read_text(encoding="utf-8"), text)
            self.assertTrue((cfg / "ocpv2-lifecycle-v2-p2.env").is_file())
            self.assertTrue((units / "ocpv2-lifecycle-v2-p2.service").is_file())
            self.assertTrue((units / "ocpv2-lifecycle-v2-p2.timer").is_file())

    def test_serving_artifact_hash_drift_fails_after_git_advance_without_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, lifecycle, cfg, units, serving = self._fixture(root)
            calls = []
            stager = self._stager(
                registry,
                lifecycle,
                cfg,
                units,
                self._callback(mutate_serving=cfg / "ocpv2.env", calls=calls),
                Probe(),
            )
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_GIT_ADVANCE")
            self.assertEqual(git(project, "rev-parse", "HEAD"), release)
            self.assertEqual(len(calls), 1)
            self.assertNotEqual((cfg / "ocpv2.env").read_text(encoding="utf-8"), serving[cfg / "ocpv2.env"])

    def test_active_enabled_or_polling_successor_state_fails_closed(self):
        for unsafe in (
            {"service_active": True},
            {"service_enabled": True},
            {"timer_active": True},
            {"timer_enabled": True},
            {"polling_enabled": True},
        ):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                registry, project, base, release, lifecycle, cfg, units, _serving = self._fixture(root)
                probe = Probe(**unsafe)
                stager = self._stager(registry, lifecycle, cfg, units, self._callback(), probe)
                dry = self._request(base, release)
                preflight = stager.execute(dry)
                with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                    stager.execute(self._stage(dry, preflight))
                self.assertEqual(raised.exception.outcome, "FAILED_AFTER_GIT_ADVANCE")
                self.assertEqual(git(project, "rev-parse", "HEAD"), release)
                self.assertEqual(probe.calls, ["lifecycle-v2-p2"])

    def test_partial_successor_artifacts_fail_after_git_advance_without_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release, lifecycle, cfg, units, _serving = self._fixture(root)
            stager = self._stager(
                registry,
                lifecycle,
                cfg,
                units,
                self._callback(omit="timer_path"),
                Probe(),
            )
            dry = self._request(base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage(dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_GIT_ADVANCE")
            self.assertEqual(git(project, "rev-parse", "HEAD"), release)
            self.assertFalse((units / "ocpv2-lifecycle-v2-p2.timer").exists())

    def test_stager_exposes_no_service_activation_methods(self):
        forbidden = {"daemon_reload", "enable", "start", "restart", "activate", "systemctl"}
        public_names = {name for name in dir(api.SuccessorReleaseStager) if not name.startswith("_")}
        self.assertTrue(forbidden.isdisjoint(public_names))


if __name__ == "__main__":
    unittest.main()

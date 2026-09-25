from __future__ import annotations

import importlib
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry


BASE_REQUEST = {
    "request_id": "stage-p2-001",
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


def successor_api():
    module_name = "runtime.orchestrator.successor_release_staging"
    assert importlib.util.find_spec(module_name) is not None, (
        "successor_release_staging module is not implemented"
    )
    return importlib.import_module(module_name)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


class OCPv2SuccessorReleaseStagingTests(unittest.TestCase):
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
        return registry, target, base, release

    def test_request_requires_exact_two_phase_binding(self):
        api = successor_api()
        dry = api.SuccessorReleaseStageRequest.from_mapping(BASE_REQUEST)
        self.assertEqual(dry.mode, "DRY_RUN")
        with self.assertRaises(api.SuccessorReleaseStageError):
            api.SuccessorReleaseStageRequest.from_mapping({**dry.to_dict(), "mode": "STAGE"})
        with self.assertRaises(api.SuccessorReleaseStageError):
            api.SuccessorReleaseStageRequest.from_mapping({**dry.to_dict(), "successor_profile": "../serving"})

    def test_two_phase_lineage_has_stable_intent_and_distinct_phase_digest(self):
        api = successor_api()
        dry = api.SuccessorReleaseStageRequest.from_mapping(BASE_REQUEST)
        stage = api.SuccessorReleaseStageRequest.from_mapping(
            {**dry.to_dict(), "mode": "STAGE", "preflight_digest": "d" * 64}
        )
        self.assertEqual(dry.stage_intent_digest, stage.stage_intent_digest)
        self.assertNotEqual(dry.phase_request_digest, stage.phase_request_digest)

    def test_same_request_id_with_changed_intent_is_detectable(self):
        api = successor_api()
        original = api.SuccessorReleaseStageRequest.from_mapping(BASE_REQUEST)
        changed = api.SuccessorReleaseStageRequest.from_mapping(
            {**BASE_REQUEST, "target_head": "e" * 40}
        )
        self.assertEqual(original.request_id, changed.request_id)
        self.assertNotEqual(original.stage_intent_digest, changed.stage_intent_digest)

    def test_same_complete_phase_has_same_replay_identity(self):
        api = successor_api()
        first = api.SuccessorReleaseStageRequest.from_mapping(BASE_REQUEST)
        replay = api.SuccessorReleaseStageRequest.from_mapping(dict(BASE_REQUEST))
        self.assertEqual(first.phase_request_digest, replay.phase_request_digest)

    def test_dry_run_is_non_mutating_and_binds_remote_target(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            registry, project, base, release = self._fixture(Path(td))
            request = api.SuccessorReleaseStageRequest.from_mapping(
                {
                    **BASE_REQUEST,
                    "expected_head": base,
                    "target_head": release,
                }
            )
            stager = api.SuccessorReleaseStager(registry)
            result = stager.execute(request)
            self.assertEqual(result["status"], "STAGE_READY")
            self.assertFalse(result["mutation_performed"])
            self.assertEqual(git(project, "rev-parse", "HEAD"), base)
            self.assertEqual(git(project, "status", "--porcelain"), "")
            self.assertEqual(result["target_head"], release)
            self.assertRegex(result["preflight_digest"], r"^[0-9a-f]{64}$")

    def test_stage_fetches_fast_forwards_and_only_calls_successor_stage_callback(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            config_root = root / "config"
            unit_root = root / "units"
            config_root.mkdir()
            unit_root.mkdir()
            serving = {
                config_root / "ocpv2.env": "serving-env\n",
                unit_root / "ocpv2.service": "serving-service\n",
                unit_root / "ocpv2.timer": "serving-timer\n",
            }
            for path, value in serving.items():
                path.write_text(value, encoding="utf-8")
            calls = []

            def stage_callback(repo_root: Path, profile: str, cfg: Path, units: Path):
                calls.append((repo_root, profile))
                env = cfg / f"ocpv2-{profile}.env"
                service = units / f"ocpv2-{profile}.service"
                timer = units / f"ocpv2-{profile}.timer"
                env.write_text("disabled\n", encoding="utf-8")
                service.write_text("stage-only\n", encoding="utf-8")
                timer.write_text("inactive\n", encoding="utf-8")
                return {
                    "env_path": str(env),
                    "service_path": str(service),
                    "timer_path": str(timer),
                }

            stager = api.SuccessorReleaseStager(
                registry,
                stage_callback=stage_callback,
                user_config_root=config_root,
                user_unit_root=unit_root,
            )
            dry = api.SuccessorReleaseStageRequest.from_mapping(
                {
                    **BASE_REQUEST,
                    "expected_head": base,
                    "target_head": release,
                }
            )
            preflight = stager.execute(dry)
            stage = api.SuccessorReleaseStageRequest.from_mapping(
                {
                    **dry.to_dict(),
                    "mode": "STAGE",
                    "preflight_digest": preflight["preflight_digest"],
                }
            )
            result = stager.execute(stage)
            self.assertEqual(result["status"], "STAGED")
            self.assertTrue(result["mutation_performed"])
            self.assertFalse(result["service_manager_invoked"])
            self.assertFalse(result["polling_enabled"])
            self.assertEqual(git(project, "rev-parse", "HEAD"), release)
            self.assertEqual(calls, [(project.resolve(), "lifecycle-v2-p2")])
            for path, value in serving.items():
                self.assertEqual(path.read_text(encoding="utf-8"), value)
            self.assertTrue((unit_root / "ocpv2-lifecycle-v2-p2.service").is_file())
            self.assertTrue((unit_root / "ocpv2-lifecycle-v2-p2.timer").is_file())


if __name__ == "__main__":
    unittest.main()

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


class RecordingFullMcp:
    def __init__(
        self,
        *,
        branch: str,
        head: str,
        remote_heads: list[str],
        object_present: bool = False,
        ancestor: bool = True,
        fetched_head: str | None = None,
    ) -> None:
        self.current_branch = branch
        self.current_head = head
        self.remote_heads = list(remote_heads)
        self.object_present = object_present
        self.ancestor = ancestor
        self.fetched_head = fetched_head
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
        return list(self.remote_heads)

    def object_exists(self, root: Path, sha: str) -> bool:
        self.calls.append(("object_exists", root, sha))
        return self.object_present

    def is_ancestor(self, root: Path, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", root, ancestor, descendant))
        return self.ancestor

    def fetch_target(self, root: Path, target_ref: str, temporary_ref: str) -> str:
        self.calls.append(("fetch_target", root, target_ref, temporary_ref))
        self.object_present = True
        return self.fetched_head or self.remote_heads[0]

    def fast_forward_current(self, root: Path, target_head: str) -> str:
        self.calls.append(("fast_forward_current", root, target_head))
        self.current_head = target_head
        return target_head

    def delete_temporary_ref(self, root: Path, temporary_ref: str) -> None:
        self.calls.append(("delete_temporary_ref", root, temporary_ref))


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

    def _request(self, api, base: str, release: str, **overrides):
        return api.SuccessorReleaseStageRequest.from_mapping(
            {
                **BASE_REQUEST,
                "expected_head": base,
                "target_head": release,
                **overrides,
            }
        )

    def _safe_lifecycle(self, api, root: Path):
        serving = root / "serving-runtime"
        serving.mkdir(exist_ok=True)
        return lambda: api.SuccessorLifecycleIdentity(
            serving_root=serving,
            predecessor_root=None,
        )

    def _assert_no_stage_mutation(self, project: Path, expected_head: str):
        self.assertEqual(git(project, "rev-parse", "HEAD"), expected_head)
        self.assertFalse((project / ".git" / "refs" / "ocp").exists())

    def _stage_request(self, api, dry, preflight):
        return api.SuccessorReleaseStageRequest.from_mapping(
            {
                **dry.to_dict(),
                "mode": "STAGE",
                "preflight_digest": preflight["preflight_digest"],
            }
        )

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

    def test_dirty_successor_worktree_fails_before_mutation(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            (project / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, base, release))
            self._assert_no_stage_mutation(project, base)

    def test_expected_branch_drift_fails_before_mutation(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, base, release, expected_branch="other"))
            self._assert_no_stage_mutation(project, base)

    def test_expected_head_drift_fails_before_mutation(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, "f" * 40, release))
            self._assert_no_stage_mutation(project, base)

    def test_serving_root_cannot_be_successor_root(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=lambda: api.SuccessorLifecycleIdentity(
                    serving_root=project,
                    predecessor_root=None,
                ),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, base, release))
            self._assert_no_stage_mutation(project, base)

    def test_predecessor_root_cannot_be_successor_root(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            serving = root / "serving-runtime"
            serving.mkdir()
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=lambda: api.SuccessorLifecycleIdentity(
                    serving_root=serving,
                    predecessor_root=project,
                ),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, base, release))
            self._assert_no_stage_mutation(project, base)

    def test_canonical_identity_rejects_symlink_alias_to_serving_root(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            serving_alias = root / "serving-alias"
            serving_alias.symlink_to(project, target_is_directory=True)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=lambda: api.SuccessorLifecycleIdentity(
                    serving_root=serving_alias,
                    predecessor_root=None,
                ),
            )
            with self.assertRaises(api.SuccessorReleaseStageError):
                stager.execute(self._request(api, base, release))
            self._assert_no_stage_mutation(project, base)

    def test_dry_run_missing_target_object_never_fetches_and_defers_ancestry(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                object_present=False,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            result = stager.execute(self._request(api, base, release))
            self.assertEqual(result["ancestry_state"], "PENDING_FETCH_PROOF")
            self.assertFalse(result["mutation_performed"])
            self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])
            self._assert_no_stage_mutation(project, base)

    def test_dry_run_requires_exactly_one_remote_target_match(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            for remote_heads in ([], [release, release]):
                full_mcp = RecordingFullMcp(
                    branch="stable", head=base, remote_heads=remote_heads
                )
                stager = api.SuccessorReleaseStager(
                    registry,
                    full_mcp=full_mcp,
                    lifecycle_identity_provider=self._safe_lifecycle(api, root),
                )
                with self.assertRaises(api.SuccessorReleaseStageError):
                    stager.execute(self._request(api, base, release))
                self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])

    def test_stage_rejects_target_ref_drift_before_fetch(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable", head=base, remote_heads=[release]
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            dry = self._request(api, base, release)
            preflight = stager.execute(dry)
            full_mcp.remote_heads = ["f" * 40]
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage_request(api, dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_BEFORE_MUTATION")
            self.assertNotIn("fetch_target", [call[0] for call in full_mcp.calls])
            self._assert_no_stage_mutation(project, base)

    def test_stage_fetched_sha_mismatch_is_failed_after_fetch_without_fast_forward(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head="f" * 40,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            dry = self._request(api, base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage_request(api, dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_FETCH")
            self.assertIn("fetch_target", [call[0] for call in full_mcp.calls])
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])
            self._assert_no_stage_mutation(project, base)

    def test_stage_non_fast_forward_fails_after_fetch_without_branch_movement(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                fetched_head=release,
                ancestor=False,
            )
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
            dry = self._request(api, base, release)
            preflight = stager.execute(dry)
            with self.assertRaises(api.SuccessorReleaseStageError) as raised:
                stager.execute(self._stage_request(api, dry, preflight))
            self.assertEqual(raised.exception.outcome, "FAILED_AFTER_FETCH")
            self.assertNotIn("fast_forward_current", [call[0] for call in full_mcp.calls])
            self._assert_no_stage_mutation(project, base)

    def test_dry_run_is_non_mutating_and_binds_remote_target(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            request = self._request(api, base, release)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
            )
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

            lifecycle = self._safe_lifecycle(api, root)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=lifecycle,
                stage_callback=stage_callback,
                user_config_root=config_root,
                user_unit_root=unit_root,
            )
            dry = self._request(api, base, release)
            preflight = stager.execute(dry)
            stage = self._stage_request(api, dry, preflight)
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


    def test_receipt_store_replays_same_phase_without_side_effects(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            full_mcp = RecordingFullMcp(
                branch="stable",
                head=base,
                remote_heads=[release],
                object_present=False,
            )
            store = api.SuccessorReleaseReceiptStore(root / "receipts")
            stager = api.SuccessorReleaseStager(
                registry,
                full_mcp=full_mcp,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
                receipt_store=store,
            )
            request = self._request(api, base, release)
            first = stager.execute(request)
            full_mcp.calls.clear()
            replay = stager.execute(request)
            self.assertEqual(replay, first)
            self.assertEqual(full_mcp.calls, [])
            stored = store.read_phase(request.phase_request_digest)
            self.assertEqual(stored, first)

    def test_successful_stage_receipt_contains_normative_evidence(self):
        api = successor_api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry, project, base, release = self._fixture(root)
            config_root = root / "config"
            unit_root = root / "units"
            receipt_root = root / "receipts"
            config_root.mkdir()
            unit_root.mkdir()
            for path, value in {
                config_root / "ocpv2.env": "serving-env\n",
                unit_root / "ocpv2.service": "serving-service\n",
                unit_root / "ocpv2.timer": "serving-timer\n",
            }.items():
                path.write_text(value, encoding="utf-8")

            def stage_artifacts(repo_root: Path, profile: str, cfg: Path, units: Path):
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

            store = api.SuccessorReleaseReceiptStore(receipt_root)
            stager = api.SuccessorReleaseStager(
                registry,
                lifecycle_identity_provider=self._safe_lifecycle(api, root),
                receipt_store=store,
                stage_artifacts=stage_artifacts,
                user_config_root=config_root,
                user_unit_root=unit_root,
            )
            dry = self._request(api, base, release)
            preflight = stager.execute(dry)
            stage = self._stage_request(api, dry, preflight)
            result = stager.execute(stage)
            receipt = store.read_phase(stage.phase_request_digest)
            self.assertEqual(receipt, result)
            expected = {
                "receipt_schema",
                "request_id",
                "stage_intent_digest",
                "phase_request_digest",
                "project_alias",
                "canonical_root",
                "project_id",
                "approval_policy_ref",
                "approval_policy_digest",
                "expected_branch",
                "pre_head",
                "target_ref",
                "target_head",
                "remote_target_head",
                "fetched_sha",
                "ancestor_fast_forward",
                "branch_fast_forward",
                "preflight_digest",
                "post_head",
                "successor_artifact_hashes",
                "serving_artifact_hashes_before",
                "serving_artifact_hashes_after",
                "service_state",
                "guard_outcomes",
                "outcome",
                "status",
                "mutation_performed",
                "service_manager_invoked",
                "polling_enabled",
            }
            self.assertTrue(expected.issubset(receipt))
            self.assertEqual(receipt["receipt_schema"], "orchestration.successor-release-stage-receipt.v1")
            self.assertEqual(receipt["request_id"], stage.request_id)
            self.assertEqual(receipt["project_alias"], stage.project_alias)
            self.assertEqual(receipt["canonical_root"], str(project.resolve()))
            self.assertEqual(receipt["pre_head"], base)
            self.assertEqual(receipt["post_head"], release)
            self.assertEqual(receipt["outcome"], "STAGED")
            self.assertTrue(receipt["ancestor_fast_forward"])
            self.assertTrue(receipt["branch_fast_forward"])


if __name__ == "__main__":
    unittest.main()

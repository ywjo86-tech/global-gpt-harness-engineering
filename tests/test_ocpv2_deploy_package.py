from __future__ import annotations

import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "operator-control-plane-v2"
BOOTSTRAP_PATH = DEPLOY_ROOT / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ocpv2_bootstrap", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OCPv2DeployPackageTests(unittest.TestCase):
    def test_example_config_contains_no_secret_or_live_server_path(self):
        text = (DEPLOY_ROOT / "ocpv2.example.env").read_text(encoding="utf-8")
        self.assertIn("OCP_MODE=DISABLED", text)
        self.assertIn("OCP_GITHUB_CONTROL_REPOSITORY_ID=0", text)
        self.assertIn("OCP_GITHUB_CONTROL_PR_NUMBER=0", text)
        self.assertIn("OCP_GITHUB_ALLOWED_ACTOR_IDS=", text)
        self.assertIn("OCP_GITHUB_TOKEN_FILE=", text)
        self.assertIn("OCP_STATE_ROOT=", text)
        self.assertIn("OCP_REPO_ROOT=/path/to/global-gpt-harness-engineering", text)
        lowered = text.lower()
        self.assertNotIn("ghp_", lowered)
        self.assertNotIn("github_pat_", lowered)
        self.assertNotIn("bearer ", lowered)
        self.assertNotIn("/home/", text)
        self.assertNotIn("ywjo", lowered)

    def test_invalid_repo_or_pr_id_cannot_enter_control_mode(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            token = root / "token"
            token.write_text("not-a-real-token", encoding="utf-8")
            token.chmod(0o600)
            state = root / "state"
            for repo_id, pr_number in ((0, 7), (222, 0), (1254385549, 7)):
                with self.subTest(repo_id=repo_id, pr_number=pr_number):
                    cfg = bootstrap.BootstrapConfig(
                        mode="OBSERVE_ONLY",
                        repo_root=repo,
                        control_repository_id=repo_id,
                        control_pr_number=pr_number,
                        allowed_actor_ids=("235775273",),
                        token_file=token,
                        state_root=state,
                    )
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.check_config(cfg)

    def test_rendered_user_service_uses_exact_validated_repo_root(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            cfg = bootstrap.BootstrapConfig.disabled(repo_root=repo)
            output = root / "rendered"
            rendered = bootstrap.render_package(cfg, output_dir=output)
            service = rendered.service_path.read_text(encoding="utf-8")
            self.assertIn(f"WorkingDirectory={repo.resolve()}", service)
            self.assertIn(f"{repo.resolve()}/deploy/operator-control-plane-v2/bootstrap.py run-once", service)
            self.assertNotIn("@REPO_ROOT@", service)

    def test_timer_runs_one_shot_service_every_30_seconds(self):
        timer = (DEPLOY_ROOT / "ocpv2.user.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitActiveSec=30s", timer)
        self.assertIn("Unit=ocpv2.service", timer)
        self.assertNotIn("Persistent=true", timer)

    def test_bootstrap_check_is_non_mutating(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            sentinel = repo / "runtime-state.json"
            sentinel.write_text("canonical", encoding="utf-8")
            before = sorted((path.relative_to(root), path.read_bytes()) for path in root.rglob("*") if path.is_file())
            cfg = bootstrap.BootstrapConfig.disabled(repo_root=repo)
            checked = bootstrap.check_config(cfg)
            after = sorted((path.relative_to(root), path.read_bytes()) for path in root.rglob("*") if path.is_file())
            self.assertEqual(checked.mode, "DISABLED")
            self.assertEqual(before, after)

    def test_install_action_never_auto_enables_active_mode(self):
        bootstrap = load_bootstrap()
        for mode in ("CONTROL_MUTATION_CANARY", "ACTIVE"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(bootstrap.BootstrapError, "install mode"):
                    bootstrap.validate_install_mode(mode)
        self.assertEqual(bootstrap.validate_install_mode("OBSERVE_ONLY"), "OBSERVE_ONLY")

    def test_disable_leaves_canonical_harness_files_untouched(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            canonical = repo / "runtime" / "orchestrator" / "canonical.json"
            canonical.parent.mkdir(parents=True)
            canonical.write_text('{"state":"authoritative"}\n', encoding="utf-8")
            original = canonical.read_bytes()
            output = root / "review-only"
            bootstrap.render_package(bootstrap.BootstrapConfig.disabled(repo_root=repo), output_dir=output)
            self.assertEqual(canonical.read_bytes(), original)
            self.assertFalse((repo / ".config").exists())
            self.assertTrue((output / "ocpv2.service").is_file())
            self.assertTrue((output / "ocpv2.timer").is_file())

    def test_readme_preserves_separate_gate_b_activation_boundary(self):
        text = (DEPLOY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Gate B", text)
        self.assertIn("OBSERVE_ONLY", text)
        self.assertIn("DISABLED", text)
        self.assertIn("systemctl --user daemon-reload", text)
        self.assertIn("systemctl --user enable --now ocpv2.timer", text)
        self.assertIn("separate authorization", text.lower())
        self.assertNotIn("/home/ywjo/", text)

    def test_non_mutating_composition_constructs_durable_outbox(self):
        bootstrap = load_bootstrap()
        source = inspect.getsource(bootstrap._compose_non_mutating_service)
        self.assertIn("RemoteResultOutbox", source)
        self.assertIn("RemoteResultProjectionV1", source)
        self.assertIn("outbox", source)


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = REPO_ROOT / "deploy" / "operator-control-plane-v2" / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ocpv2_bootstrap_onboarding_defaults", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectOnboardingDeployDefaultsTests(unittest.TestCase):
    def test_rendered_environment_keeps_onboarding_disabled(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            token = root / "github.token"
            token.write_text("test-token-placeholder", encoding="utf-8")
            token.chmod(0o600)
            config = bootstrap.BootstrapConfig(
                mode="OBSERVE_ONLY",
                repo_root=repo,
                control_repository_id=1379497136,
                control_pr_number=1,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=root / "state",
            )
            rendered = bootstrap.render_package(config, output_dir=root / "rendered")
            env = rendered.env_path.read_text(encoding="utf-8")
            self.assertIn("OCP_PROJECT_ONBOARDING_ENABLED=0\n", env)
            self.assertIn("OCP_PROJECT_ONBOARDING_POLICY_REF=\n", env)

    def test_round_trip_accepts_disabled_onboarding_keys(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            token = root / "github.token"
            token.write_text("test-token-placeholder", encoding="utf-8")
            token.chmod(0o600)
            config = bootstrap.BootstrapConfig(
                mode="OBSERVE_ONLY",
                repo_root=repo,
                control_repository_id=1379497136,
                control_pr_number=1,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=root / "state",
            )
            rendered = bootstrap.render_package(config, output_dir=root / "rendered")
            restored = bootstrap.config_from_env_file(rendered.env_path)
            self.assertEqual(restored.mode, "OBSERVE_ONLY")


if __name__ == "__main__":
    unittest.main()

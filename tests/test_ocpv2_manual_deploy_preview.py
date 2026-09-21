from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = REPO_ROOT / "deploy" / "operator-control-plane-v2" / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ocpv2_bootstrap_manual_preview", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OCPv2ManualDeployPreviewTests(unittest.TestCase):
    def test_install_result_exposes_reviewable_manual_activation_and_rollback_only(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            token = root / "github.token"
            token.write_text("test-token-placeholder", encoding="utf-8")
            token.chmod(0o600)
            state = root / "ocpv2-state"
            cfg = bootstrap.BootstrapConfig(
                mode="OBSERVE_ONLY",
                repo_root=repo,
                control_repository_id=1379497136,
                control_pr_number=1,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=state,
            )
            rendered = bootstrap.install_user_service(
                cfg,
                user_config_root=root / "config",
                user_unit_root=root / "units",
            )
            preview = bootstrap.manual_activation_preview(rendered)

            self.assertFalse(preview["service_manager_invoked"])
            self.assertEqual(
                preview["activation_commands"],
                [
                    "systemctl --user daemon-reload",
                    "systemctl --user enable --now ocpv2.timer",
                ],
            )
            self.assertEqual(
                preview["rollback_commands"],
                [
                    "systemctl --user disable --now ocpv2.timer",
                    "systemctl --user stop ocpv2.service",
                ],
            )
            self.assertEqual(preview["generated_paths"]["env"], str(rendered.env_path))
            self.assertEqual(preview["generated_paths"]["service"], str(rendered.service_path))
            self.assertEqual(preview["generated_paths"]["timer"], str(rendered.timer_path))

    def test_preview_source_cannot_invoke_systemctl(self):
        bootstrap = load_bootstrap()
        source = bootstrap.manual_activation_preview.__code__.co_names
        self.assertNotIn("subprocess", source)
        self.assertNotIn("system", source)
        self.assertEqual(bootstrap.validate_install_mode("OBSERVE_ONLY"), "OBSERVE_ONLY")
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_install_mode("ACTIVE")


if __name__ == "__main__":
    unittest.main()

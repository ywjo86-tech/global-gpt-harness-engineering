from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = REPO_ROOT / "deploy" / "operator-control-plane-v2" / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ocpv2_bootstrap_p2", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OCPv2P2SuccessorStageProfileTests(unittest.TestCase):
    def test_successor_profile_stages_isolated_units_without_touching_serving_names(self):
        bootstrap = load_bootstrap()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            config_root = root / "config"
            unit_root = root / "units"
            profile = bootstrap.DeploymentProfile.successor("lifecycle-v2-p2")

            rendered = bootstrap.stage_user_service(
                bootstrap.BootstrapConfig.disabled(repo_root=repo),
                profile=profile,
                user_config_root=config_root,
                user_unit_root=unit_root,
            )

            self.assertEqual(rendered.env_path.name, "ocpv2-lifecycle-v2-p2.env")
            self.assertEqual(rendered.service_path.name, "ocpv2-lifecycle-v2-p2.service")
            self.assertEqual(rendered.timer_path.name, "ocpv2-lifecycle-v2-p2.timer")
            self.assertFalse((config_root / "ocpv2.env").exists())
            self.assertFalse((unit_root / "ocpv2.service").exists())
            self.assertFalse((unit_root / "ocpv2.timer").exists())

            service = rendered.service_path.read_text(encoding="utf-8")
            timer = rendered.timer_path.read_text(encoding="utf-8")
            expected_env = "%h/.config/gch/ocpv2-lifecycle-v2-p2.env"
            self.assertIn(f"EnvironmentFile={expected_env}", service)
            self.assertIn(f"--env-file {expected_env}", service)
            self.assertIn("Unit=ocpv2-lifecycle-v2-p2.service", timer)

    def test_successor_profile_rejects_path_or_serving_name_aliases(self):
        bootstrap = load_bootstrap()
        for value in ("", "ocpv2", "../successor", "successor/name", "."):
            with self.subTest(value=value):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.DeploymentProfile.successor(value)

    def test_stage_only_cli_contract_is_explicitly_non_activating(self):
        bootstrap = load_bootstrap()
        parser = bootstrap.build_parser()
        args = parser.parse_args(
            [
                "stage-user-service",
                "--repo-root",
                str(REPO_ROOT),
                "--mode",
                "DISABLED",
                "--control-repository-id",
                "0",
                "--control-pr-number",
                "0",
                "--successor-profile",
                "lifecycle-v2-p2",
            ]
        )
        self.assertEqual(args.command, "stage-user-service")
        self.assertEqual(args.successor_profile, "lifecycle-v2-p2")
        self.assertNotIn("enable", vars(args))
        self.assertNotIn("start", vars(args))


if __name__ == "__main__":
    unittest.main()

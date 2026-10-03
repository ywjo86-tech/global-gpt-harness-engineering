from __future__ import annotations

import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = REPO_ROOT / "deploy" / "operator-control-plane-v2" / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ocpv2_successor_bootstrap", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SuccessorStageBootstrapTests(unittest.TestCase):
    def test_stage_successor_artifacts_is_fixed_to_lifecycle_v2_p2_and_disabled(self):
        bootstrap = load_bootstrap()
        self.assertTrue(hasattr(bootstrap, "stage_successor_artifacts"))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            cfg = root / "config"
            units = root / "units"
            cfg.mkdir()
            units.mkdir()
            result = bootstrap.stage_successor_artifacts(
                repo,
                "lifecycle-v2-p2",
                cfg,
                units,
            )
            self.assertEqual(set(result), {"env_path", "service_path", "timer_path"})
            env = Path(result["env_path"])
            service = Path(result["service_path"])
            timer = Path(result["timer_path"])
            self.assertEqual(env.name, "ocpv2-lifecycle-v2-p2.env")
            self.assertEqual(service.name, "ocpv2-lifecycle-v2-p2.service")
            self.assertEqual(timer.name, "ocpv2-lifecycle-v2-p2.timer")
            self.assertIn("OCP_MODE=DISABLED", env.read_text(encoding="utf-8"))
            self.assertTrue(service.is_file())
            self.assertTrue(timer.is_file())

            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.stage_successor_artifacts(repo, "other-profile", cfg, units)

    def test_bootstrap_adapter_has_no_service_manager_mutation(self):
        bootstrap = load_bootstrap()
        self.assertTrue(hasattr(bootstrap, "stage_successor_artifacts"))
        source = inspect.getsource(bootstrap.stage_successor_artifacts)
        forbidden = ("systemctl", "daemon-reload", "enable", "--now", "restart", "start")
        self.assertTrue(all(word not in source for word in forbidden))


if __name__ == "__main__":
    unittest.main()

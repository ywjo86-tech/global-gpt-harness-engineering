from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_stage_control_runtime as runtime
from runtime.orchestrator.remote_operator_service import ControlMode


class StageControlRuntimeTests(unittest.TestCase):
    def _config(self, root: Path, **environment):
        return SimpleNamespace(
            mode=ControlMode.ACTIVE,
            repo_root=root / "predecessor",
            environment={"OCP_SUCCESSOR_RELEASE_STAGE_ENABLED": "1", **environment},
        )

    def test_requires_source_root_separate_from_serving_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            predecessor = root / "predecessor"
            predecessor.mkdir()
            with patch.object(runtime.Path, "cwd", return_value=predecessor):
                with self.assertRaisesRegex(runtime.StageControlRuntimeError, "SOURCE_MUST_BE_SEPARATE"):
                    runtime._validate_stage_control_config(self._config(root))

    def test_rejects_p3_or_full_plan_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "predecessor").mkdir()
            config = self._config(root, OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED="1")
            with patch.object(runtime.Path, "cwd", return_value=root / "successor"):
                with self.assertRaisesRegex(runtime.StageControlRuntimeError, "UNRELATED_CAPABILITY"):
                    runtime._validate_stage_control_config(config)

    def test_delegates_only_after_stage_boundary_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "predecessor").mkdir()
            config = self._config(root)
            with patch.object(runtime.Path, "cwd", return_value=root / "successor"), patch.object(
                runtime.successor, "run_once", return_value={"successor_release_staged": 0}
            ) as run_once:
                self.assertEqual(runtime.run_once(config), {"successor_release_staged": 0})
            run_once.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()

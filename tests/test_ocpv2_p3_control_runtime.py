from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_p3_control_runtime as runtime
from runtime.orchestrator.remote_operator_service import ControlMode


class P3ControlRuntimeTests(unittest.TestCase):
    def _config(self, root: Path, **environment):
        return SimpleNamespace(
            mode=ControlMode.ACTIVE,
            repo_root=root / "predecessor",
            environment={
                "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED": "1",
                **environment,
            },
        )

    def test_requires_source_root_separate_from_serving_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            predecessor = root / "predecessor"
            predecessor.mkdir()
            config = self._config(root)
            with patch.object(runtime.Path, "cwd", return_value=predecessor):
                with self.assertRaisesRegex(runtime.P3ControlRuntimeError, "SOURCE_MUST_BE_SEPARATE"):
                    runtime._validate_p3_control_config(config)

    def test_rejects_unrelated_or_multiple_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "predecessor").mkdir()
            config = self._config(root, OCP_FULL_PLAN_ACTIVATION_ENABLED="1")
            with patch.object(runtime.Path, "cwd", return_value=root / "successor"):
                with self.assertRaisesRegex(runtime.P3ControlRuntimeError, "UNRELATED_CAPABILITY"):
                    runtime._validate_p3_control_config(config)

            config = self._config(root, OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED="1")
            with patch.object(runtime.Path, "cwd", return_value=root / "successor"):
                with self.assertRaisesRegex(runtime.P3ControlRuntimeError, "EXACTLY_ONE"):
                    runtime._validate_p3_control_config(config)

    def test_delegates_only_after_p3_control_boundary_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "predecessor").mkdir()
            config = self._config(root)
            expected = {"p3_promotion_admitted": 0}
            with patch.object(runtime.Path, "cwd", return_value=root / "successor"), patch.object(
                runtime.successor, "run_once", return_value=expected
            ) as run_once:
                self.assertEqual(runtime.run_once(config), expected)
            run_once.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()

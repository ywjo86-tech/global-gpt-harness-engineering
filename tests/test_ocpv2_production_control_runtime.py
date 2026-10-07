import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_production_control_runtime as runtime
from runtime.orchestrator.remote_control_envelope import PRODUCTION_CONTROL_ACTION_KIND
from runtime.orchestrator.remote_operator_service import ControlMode


class _Transport:
    def __init__(self):
        self.calls = []

    def receive_request_kind(self, kind, *, limit=16):
        self.calls.append((kind, limit))
        return ()

    def acknowledge_delivery(self, message_id):
        pass

    def publish_projection(self, projection):
        pass


class OCPProductionControlRuntimeTests(unittest.TestCase):
    def _config(self, root: Path, **environment):
        base = {
            "OCP_PRODUCTION_CONTROL_ENABLED": "1",
            "OCP_PRODUCTION_CONTROL_POLICY_REF": "OCP-FULL-PLAN-TEST-1",
        }
        base.update(environment)
        return SimpleNamespace(
            mode=ControlMode.ACTIVE,
            repo_root=root / "serving",
            environment=base,
        )

    def test_requires_source_root_separate_from_serving_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            serving = root / "serving"
            serving.mkdir()
            with patch.object(runtime.Path, "cwd", return_value=serving):
                with self.assertRaisesRegex(
                    runtime.ProductionControlRuntimeError,
                    "SOURCE_MUST_BE_SEPARATE",
                ):
                    runtime._validate_config(self._config(root))

    def test_requires_active_mode_and_explicit_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "serving").mkdir()
            successor = root / "successor"
            successor.mkdir()
            config = self._config(root)
            config.mode = ControlMode.CONTROL_READ_ONLY
            with patch.object(runtime.Path, "cwd", return_value=successor):
                with self.assertRaisesRegex(
                    runtime.ProductionControlRuntimeError,
                    "ACTIVE_MODE_REQUIRED",
                ):
                    runtime._validate_config(config)

            config = self._config(root, OCP_PRODUCTION_CONTROL_ENABLED="0")
            with patch.object(runtime.Path, "cwd", return_value=successor):
                with self.assertRaisesRegex(
                    runtime.ProductionControlRuntimeError,
                    "GATE_REQUIRED",
                ):
                    runtime._validate_config(config)

    def test_rejects_any_unrelated_ocp_capability(self):
        forbidden = (
            "OCP_HOST_INSPECTION_ENABLED",
            "OCP_WORK_ACTIVATION_ENABLED",
            "OCP_FULL_PLAN_ACTIVATION_ENABLED",
            "OCP_SUCCESSOR_RELEASE_STAGE_ENABLED",
            "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED",
            "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "serving").mkdir()
            successor = root / "successor"
            successor.mkdir()
            for key in forbidden:
                with self.subTest(key=key):
                    config = self._config(root, **{key: "1"})
                    with patch.object(runtime.Path, "cwd", return_value=successor):
                        with self.assertRaisesRegex(
                            runtime.ProductionControlRuntimeError,
                            "UNRELATED_CAPABILITY",
                        ):
                            runtime._validate_config(config)

    def test_filtered_transport_accepts_only_production_control_kind(self):
        transport = _Transport()
        filtered = runtime._ProductionControlFilteredTransport(transport)
        self.assertEqual(filtered.receive(limit=3), ())
        self.assertEqual(transport.calls, [(PRODUCTION_CONTROL_ACTION_KIND, 3)])

    def test_missing_filtered_transport_capability_fails_closed(self):
        class Missing:
            def acknowledge_delivery(self, message_id):
                pass
            def publish_projection(self, projection):
                pass

        filtered = runtime._ProductionControlFilteredTransport(Missing())
        with self.assertRaisesRegex(
            runtime.ProductionControlRuntimeError,
            "TRANSPORT_FILTER_REQUIRED",
        ):
            filtered.receive()


if __name__ == "__main__":
    unittest.main()

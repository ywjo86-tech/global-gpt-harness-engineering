from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.orchestrator.omniroute_runtime import (
    OMNIROUTE_VERSION,
    OmniRouteReadiness,
    probe_omniroute_runtime,
)


class OmniRouteRuntimeLifecycleTests(unittest.TestCase):
    def test_readiness_rejects_non_loopback_listener(self) -> None:
        probe = probe_omniroute_runtime(
            package_version=OMNIROUTE_VERSION,
            executable_path="/home/user/.local/omniroute",
            listener_hosts=("0.0.0.0",),
            listener_port=20128,
            auth_enforced=True,
            doctor_status="PASS",
            data_dir="/home/user/.local/share/gch/omniroute",
            config_sha256="a" * 64,
            secret_file_path="/home/user/.config/gch/omniroute.env",
            secret_file_mode=0o600,
            api_key_present=True,
        )
        self.assertFalse(probe.ready)
        self.assertIn("non_loopback_listener", probe.reasons)

    def test_readiness_rejects_unauthenticated_v1(self) -> None:
        probe = probe_omniroute_runtime(
            package_version=OMNIROUTE_VERSION,
            executable_path="/home/user/.local/omniroute",
            listener_hosts=("127.0.0.1",),
            listener_port=20128,
            auth_enforced=False,
            doctor_status="PASS",
            data_dir="/home/user/.local/share/gch/omniroute",
            config_sha256="a" * 64,
            secret_file_path="/home/user/.config/gch/omniroute.env",
            secret_file_mode=0o600,
            api_key_present=True,
        )
        self.assertFalse(probe.ready)
        self.assertIn("api_key_not_enforced", probe.reasons)

    def test_readiness_passes_only_with_complete_secure_evidence(self) -> None:
        probe = probe_omniroute_runtime(
            package_version=OMNIROUTE_VERSION,
            executable_path="/home/user/.local/omniroute",
            listener_hosts=("127.0.0.1",), listener_port=20128,
            auth_enforced=True, doctor_status="PASS",
            data_dir="/home/user/.local/share/gch/omniroute",
            config_sha256="b" * 64,
            secret_file_path="/home/user/.config/gch/omniroute.env",
            secret_file_mode=0o600, api_key_present=True,
        )
        self.assertTrue(probe.ready)
        self.assertEqual(probe.reasons, ())

    def test_readiness_evidence_is_redacted(self) -> None:
        probe = probe_omniroute_runtime(
            package_version=OMNIROUTE_VERSION,
            executable_path="/home/user/.local/omniroute",
            listener_hosts=("127.0.0.1",), listener_port=20128,
            auth_enforced=True, doctor_status="PASS",
            data_dir="/home/user/.local/share/gch/omniroute",
            config_sha256="c" * 64,
            secret_file_path="/home/user/.config/gch/omniroute.env",
            secret_file_mode=0o600, api_key_present=True,
        )
        payload = json.dumps(probe.to_dict(), sort_keys=True)
        self.assertIn('"api_key_present": true', payload)
        self.assertNotIn("fixture-secret-value", payload)
        self.assertNotIn("OMNIROUTE_API_KEY=", payload)

    def test_launcher_contract_preserves_safe_flags_and_evidence(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts/run_omniroute_gateway.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("OMNIROUTE_SERVER_HOST=127.0.0.1", script)
        self.assertIn("REQUIRE_API_KEY=true", script)
        self.assertIn("OMNIROUTE_EMERGENCY_FALLBACK=false", script)
        self.assertIn("OMNIROUTE_ENABLE_LIVE_WS=false", script)
        self.assertIn("OMNIROUTE_DISABLE_BACKGROUND_SERVICES=true", script)
        self.assertIn("API_KEY_SECRET", script)
        self.assertIn("JWT_SECRET", script)
        self.assertIn("STORAGE_ENCRYPTION_KEY", script)
        self.assertIn("--no-recovery", script)
        self.assertIn("rollback", script)
        self.assertNotIn("rm -rf \"$EVIDENCE_DIR\"", script)


    def test_launcher_uses_spec_paths_and_isolated_home(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts/run_omniroute_gateway.sh").read_text(encoding="utf-8")
        self.assertIn('RUNTIME="$GCH_ROOT/runtime"', script)
        self.assertIn('DATA_DIR="$GCH_ROOT/data"', script)
        self.assertIn('ISOLATED_HOME="$GCH_ROOT/home"', script)
        self.assertIn('OMNIROUTE_CLI_SKIP_REPO_ENV=1', script)


    def test_doctor_is_bounded_and_does_not_spawn_login_shell(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts/run_omniroute_gateway.sh").read_text(encoding="utf-8")
        self.assertIn('timeout --kill-after=2s 15s env SHELL=/bin/false', script)


if __name__ == "__main__":
    unittest.main()

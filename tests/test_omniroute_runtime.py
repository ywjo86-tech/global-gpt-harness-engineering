from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.omniroute_runtime import (
    OMNIROUTE_NPM_INTEGRITY,
    OMNIROUTE_VERSION,
    OmniRouteRuntimeError,
    build_omniroute_env,
    validate_omniroute_preflight,
)


class OmniRouteRuntimeTests(unittest.TestCase):
    def test_secure_env_is_loopback_and_disables_hidden_routing(self) -> None:
        env = build_omniroute_env(Path("/tmp/data"), "secret-ref")
        self.assertEqual(env["OMNIROUTE_SERVER_HOST"], "127.0.0.1")
        self.assertEqual(env["PORT"], "20128")
        self.assertEqual(env["REQUIRE_API_KEY"], "true")
        self.assertEqual(env["OMNIROUTE_API_KEY"], "secret-ref")
        self.assertEqual(env["OMNIROUTE_EMERGENCY_FALLBACK"], "false")
        self.assertEqual(env["PROXY_AUTO_SELECT_ENABLED"], "false")
        self.assertEqual(env["OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK"], "false")
        self.assertEqual(env["OMNIROUTE_ENABLE_LIVE_WS"], "false")
        self.assertEqual(env["OMNIROUTE_DISABLE_BACKGROUND_SERVICES"], "true")

    def _valid_paths(self, root: Path) -> tuple[Path, Path, Path]:
        runtime_prefix = root / "runtime"
        data_dir = root / "data"
        secret_file = root / "omniroute.env"
        data_dir.mkdir()
        secret_file.write_text("OMNIROUTE_API_KEY=fixture\n", encoding="utf-8")
        secret_file.chmod(0o600)
        return runtime_prefix, data_dir, secret_file

    def test_valid_preflight_accepts_supported_runtime_and_pinned_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_prefix, data_dir, secret_file = self._valid_paths(Path(td))
            result = validate_omniroute_preflight(
                runtime_prefix=runtime_prefix,
                data_dir=data_dir,
                secret_file=secret_file,
                node_version="v22.23.2",
                port_in_use=False,
                package_version=OMNIROUTE_VERSION,
                package_integrity=OMNIROUTE_NPM_INTEGRITY,
            )
            self.assertEqual(result.runtime_prefix, runtime_prefix)
            self.assertEqual(result.secret_file, secret_file)
            self.assertEqual(result.port, 20128)

    def test_preflight_rejects_unsupported_node_or_occupied_port(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_prefix, data_dir, secret_file = self._valid_paths(Path(td))
            common = dict(
                runtime_prefix=runtime_prefix,
                data_dir=data_dir,
                secret_file=secret_file,
                package_version=OMNIROUTE_VERSION,
                package_integrity=OMNIROUTE_NPM_INTEGRITY,
            )
            with self.assertRaisesRegex(OmniRouteRuntimeError, "Node"):
                validate_omniroute_preflight(node_version="v22.22.1", port_in_use=False, **common)
            with self.assertRaisesRegex(OmniRouteRuntimeError, "port"):
                validate_omniroute_preflight(node_version="v22.23.2", port_in_use=True, **common)

    def test_preflight_rejects_secret_permissions_and_symlinked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_prefix, data_dir, secret_file = self._valid_paths(root)
            secret_file.chmod(0o644)
            with self.assertRaisesRegex(OmniRouteRuntimeError, "0600"):
                validate_omniroute_preflight(
                    runtime_prefix=runtime_prefix, data_dir=data_dir, secret_file=secret_file,
                    node_version="v22.23.2", port_in_use=False,
                    package_version=OMNIROUTE_VERSION, package_integrity=OMNIROUTE_NPM_INTEGRITY,
                )
            secret_file.chmod(0o600)
            real_runtime = root / "real-runtime"
            real_runtime.mkdir()
            runtime_prefix.symlink_to(real_runtime, target_is_directory=True)
            with self.assertRaisesRegex(OmniRouteRuntimeError, "symlink"):
                validate_omniroute_preflight(
                    runtime_prefix=runtime_prefix, data_dir=data_dir, secret_file=secret_file,
                    node_version="v22.23.2", port_in_use=False,
                    package_version=OMNIROUTE_VERSION, package_integrity=OMNIROUTE_NPM_INTEGRITY,
                )

    def test_preflight_rejects_package_version_or_integrity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_prefix, data_dir, secret_file = self._valid_paths(Path(td))
            common = dict(
                runtime_prefix=runtime_prefix, data_dir=data_dir, secret_file=secret_file,
                node_version="v22.23.2", port_in_use=False,
            )
            with self.assertRaisesRegex(OmniRouteRuntimeError, "version"):
                validate_omniroute_preflight(
                    package_version="3.8.49", package_integrity=OMNIROUTE_NPM_INTEGRITY, **common,
                )
            with self.assertRaisesRegex(OmniRouteRuntimeError, "integrity"):
                validate_omniroute_preflight(
                    package_version=OMNIROUTE_VERSION, package_integrity="sha512-wrong", **common,
                )

    def test_install_script_is_pinned_user_owned_and_installs_verified_tarball(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts/install_omniroute_gateway.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("VERSION=3.8.50", script)
        self.assertIn("npm pack \"omniroute@$VERSION\"", script)
        self.assertIn(OMNIROUTE_NPM_INTEGRITY, script)
        self.assertIn('npm install --prefix "$PREFIX.new"', script)
        self.assertIn('"$TARBALL"', script)
        self.assertIn("grep -Fx '3.8.50'", script)
        self.assertNotIn("sudo", script)
        self.assertNotIn("npm install -g", script)


if __name__ == "__main__":
    unittest.main()

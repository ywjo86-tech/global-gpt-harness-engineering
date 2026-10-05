from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operations_dashboard_publish_boot import (
    PUBLISH_SERVICE_UNIT,
    PUBLISH_TIMER_UNIT,
    OperationsDashboardPublishBootError,
    install_publish_units,
    render_publish_service,
    render_publish_timer,
)


class OperationsDashboardPublishBootTests(unittest.TestCase):
    def test_service_binds_runtime_state_and_head(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            state = root / "state"
            runtime.mkdir()
            state.mkdir()
            python = root / "python3"
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755)

            unit = render_publish_service(
                runtime_root=runtime,
                state_root=state,
                publisher_source_head="a" * 40,
                python_executable=python,
            )

            self.assertIn(
                f"WorkingDirectory={runtime.resolve()}",
                unit,
            )
            self.assertIn(
                "runtime.orchestrator.operations_dashboard_publish_cli",
                unit,
            )
            self.assertIn(
                f"--state-root {state.resolve()}",
                unit,
            )
            self.assertIn(
                "--publisher-source-head " + "a" * 40,
                unit,
            )

    def test_timer_defaults_to_one_minute(self):
        unit = render_publish_timer()
        self.assertIn("OnBootSec=20s", unit)
        self.assertIn("OnUnitActiveSec=60s", unit)
        self.assertIn(
            f"Unit={PUBLISH_SERVICE_UNIT}",
            unit,
        )

    def test_invalid_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            state = root / "state"
            runtime.mkdir()
            state.mkdir()
            python = root / "python3"
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755)
            with self.assertRaisesRegex(
                OperationsDashboardPublishBootError,
                "HEAD invalid",
            ):
                render_publish_service(
                    runtime_root=runtime,
                    state_root=state,
                    publisher_source_head="not-a-head",
                    python_executable=python,
                )

    def test_installer_enables_only_timer(self):
        calls = []

        def runner(argv):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(
                argv, 0, "", ""
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            state = root / "state"
            units = root / "units"
            runtime.mkdir()
            state.mkdir()
            python = root / "python3"
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755)

            service, timer = install_publish_units(
                runtime_root=runtime,
                state_root=state,
                publisher_source_head="a" * 40,
                python_executable=python,
                unit_dir=units,
                runner=runner,
                enable_now=True,
            )

            self.assertEqual(
                service.name, PUBLISH_SERVICE_UNIT
            )
            self.assertEqual(
                timer.name, PUBLISH_TIMER_UNIT
            )
            self.assertEqual(
                calls,
                [
                    (
                        "systemctl",
                        "--user",
                        "daemon-reload",
                    ),
                    (
                        "systemctl",
                        "--user",
                        "enable",
                        "--now",
                        PUBLISH_TIMER_UNIT,
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()

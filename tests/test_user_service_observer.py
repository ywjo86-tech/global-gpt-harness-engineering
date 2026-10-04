from __future__ import annotations

import subprocess
import unittest

from runtime.orchestrator.user_service_observer import UserServiceObserver, UserServiceObserverError


class UserServiceObserverTests(unittest.TestCase):
    def test_allowed_unit_uses_exact_fixed_systemctl_show_command(self) -> None:
        calls = []

        def runner(argv):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="ActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\n",
                stderr="",
            )

        observer = UserServiceObserver(
            allowed_units=frozenset({"ocpv2.service"}), runner=runner,
        )
        result = observer.read("ocpv2.service")
        self.assertEqual(result["ActiveState"], "active")
        self.assertEqual(result["ExecMainStatus"], "0")
        self.assertEqual(calls, [(
            "systemctl", "--user", "show", "ocpv2.service",
            "--property=ActiveState,SubState,Result,ExecMainStatus",
        )])

    def test_timer_unit_is_allowed_when_explicitly_allowlisted(self) -> None:
        calls = []

        def runner(argv):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="ActiveState=active\nSubState=waiting\nResult=success\nLastTriggerUSec=Sun 2026-10-04 11:57:50 KST\n",
                stderr="",
            )

        observer = UserServiceObserver(
            allowed_units=frozenset({"global-gpt-harness-full-plan-reconcile.timer"}), runner=runner,
        )
        result = observer.read("global-gpt-harness-full-plan-reconcile.timer")
        self.assertEqual(result["ActiveState"], "active")
        self.assertEqual(result["SubState"], "waiting")
        self.assertEqual(calls[0], (
            "systemctl", "--user", "show", "global-gpt-harness-full-plan-reconcile.timer",
            "--property=ActiveState,SubState,Result,LastTriggerUSec",
        ))
        self.assertNotIn("ExecMainStatus", result)

    def test_disallowed_or_malformed_unit_never_calls_runner(self) -> None:
        calls = []
        observer = UserServiceObserver(
            allowed_units=frozenset({"ocpv2.service"}),
            runner=lambda argv: calls.append(tuple(argv)),
        )
        for unit in ("ssh.service", "../ocpv2.service", "ocpv2.service --all", ""):
            with self.subTest(unit=unit):
                with self.assertRaisesRegex(UserServiceObserverError, "UNIT_NOT_ALLOWED"):
                    observer.read(unit)
        self.assertEqual(calls, [])

    def test_nonzero_or_malformed_output_fails_closed(self) -> None:
        failing = UserServiceObserver(
            allowed_units=frozenset({"ocpv2.service"}),
            runner=lambda argv: subprocess.CompletedProcess(argv, 1, stdout="", stderr="failed"),
        )
        with self.assertRaisesRegex(UserServiceObserverError, "SERVICE_QUERY_FAILED"):
            failing.read("ocpv2.service")

        malformed = UserServiceObserver(
            allowed_units=frozenset({"ocpv2.service"}),
            runner=lambda argv: subprocess.CompletedProcess(argv, 0, stdout="ActiveState=active\n", stderr=""),
        )
        with self.assertRaisesRegex(UserServiceObserverError, "SERVICE_RESULT_INVALID"):
            malformed.read("ocpv2.service")


if __name__ == "__main__":
    unittest.main()

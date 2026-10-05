from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.ocpv2_activation_window import (
    ACTIVATION_WINDOW_SCHEMA_V1,
    DEFAULT_OCP_TIMER,
    DEFAULT_RECONCILE_TIMER,
    OCPActivationWindowError,
    SystemdTransientRecoveryScheduler,
    activation_flag_value,
    activation_window_path,
    close_activation_window,
    load_activation_window,
    open_activation_window,
    poll_activation_window_once,
    recover_activation_window,
    run_controlled_activation_once,
)


class FakeController:
    def __init__(self, states=None, *, fail_start=(), fail_stop=()):
        self.states = dict(states or {})
        self.fail_start = set(fail_start)
        self.fail_stop = set(fail_stop)
        self.events = []

    def is_active(self, unit: str) -> bool:
        self.events.append(("is_active", unit))
        return bool(self.states.get(unit, False))

    def stop(self, unit: str) -> None:
        self.events.append(("stop", unit))
        if unit in self.fail_stop:
            raise RuntimeError(f"stop failed: {unit}")
        self.states[unit] = False

    def start(self, unit: str) -> None:
        self.events.append(("start", unit))
        if unit in self.fail_start:
            raise RuntimeError(f"start failed: {unit}")
        self.states[unit] = True


class FakeScheduler:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def schedule(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("watchdog schedule failed")
        return "test-recovery-watchdog"


def write_env(
    path: Path,
    *,
    flag: str = "0",
    mode: str = "ACTIVE",
    policy: str = "TEST-POLICY",
) -> None:
    path.write_text(
        "\n".join(
            [
                f"OCP_MODE={mode}",
                f"OCP_FULL_PLAN_ACTIVATION_ENABLED={flag}",
                f"OCP_FULL_PLAN_ACTIVATION_POLICY_REF={policy}",
                "OCP_REPO_ROOT=/tmp/repo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class OCPActivationWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.env = self.root / "ocpv2.env"
        write_env(self.env)

    def tearDown(self):
        self.temp.cleanup()

    def _controller(self):
        return FakeController(
            {
                DEFAULT_RECONCILE_TIMER: True,
                DEFAULT_OCP_TIMER: True,
            }
        )

    def _open(self, controller=None, scheduler=None, **kwargs):
        return open_activation_window(
            state_root=self.state,
            env_file=self.env,
            controller=controller or self._controller(),
            scheduler=scheduler or FakeScheduler(),
            max_seconds=60,
            window_id="TEST-WINDOW",
            **kwargs,
        )



    def test_run_once_is_bounded_transaction_and_restores_timers(self):
        controller = self._controller()
        scheduler = FakeScheduler()

        def runner(temp_env: Path):
            values = dict(
                line.split("=", 1)
                for line in temp_env.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
            self.assertEqual(values["OCP_FULL_PLAN_ACTIVATION_ENABLED"], "1")
            self.assertEqual(activation_flag_value(self.env), "0")
            self.assertFalse(controller.states[DEFAULT_RECONCILE_TIMER])
            self.assertFalse(controller.states[DEFAULT_OCP_TIMER])
            return 0, json.dumps({
                "status": "OK",
                "full_plan_activated": 1,
                "blocked": 0,
            })

        result = run_controlled_activation_once(
            state_root=self.state,
            env_file=self.env,
            controller=controller,
            scheduler=scheduler,
            max_seconds=60,
            window_id="RUN-ONCE-SUCCESS",
            runner=runner,
        )

        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["last_poll_full_plan_activated"], 1)
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        self.assertFalse(
            list((self.state / "operations-v2").glob(".ocpv2-activation-*.env"))
        )

    def test_run_once_poll_failure_closes_failed_and_restores_timers(self):
        controller = self._controller()
        scheduler = FakeScheduler()

        with self.assertRaisesRegex(
            OCPActivationWindowError, "OCP activation poll failed"
        ):
            run_controlled_activation_once(
                state_root=self.state,
                env_file=self.env,
                controller=controller,
                scheduler=scheduler,
                max_seconds=60,
                window_id="RUN-ONCE-FAIL",
                runner=lambda _env: (2, json.dumps({
                    "status": "BLOCKED",
                    "full_plan_activated": 0,
                    "blocked": 1,
                })),
            )

        record = load_activation_window(self.state)
        self.assertEqual(record["status"], "CLOSED_AFTER_FAILURE")
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        self.assertFalse(
            list((self.state / "operations-v2").glob(".ocpv2-activation-*.env"))
        )

    def test_explicit_open_poll_close_keeps_persistent_flag_off(self):
        controller = self._controller()
        scheduler = FakeScheduler()
        opened = self._open(controller=controller, scheduler=scheduler)

        self.assertEqual(opened["schema_version"], ACTIVATION_WINDOW_SCHEMA_V1)
        self.assertEqual(opened["status"], "ACTIVE")
        self.assertEqual(opened["watchdog_unit"], "test-recovery-watchdog")
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertFalse(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertFalse(controller.states[DEFAULT_OCP_TIMER])
        self.assertEqual(len(scheduler.calls), 1)

        def runner(temp_env: Path):
            values = dict(
                line.split("=", 1)
                for line in temp_env.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
            self.assertEqual(values["OCP_FULL_PLAN_ACTIVATION_ENABLED"], "1")
            self.assertEqual(activation_flag_value(self.env), "0")
            return 0, json.dumps(
                {
                    "status": "OK",
                    "full_plan_activated": 1,
                    "blocked": 0,
                }
            )

        polled = poll_activation_window_once(
            state_root=self.state,
            env_file=self.env,
            runner=runner,
        )
        self.assertEqual(polled["poll_count"], 1)
        self.assertEqual(polled["last_poll_status"], "OK")
        self.assertEqual(polled["last_poll_full_plan_activated"], 1)
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertFalse(list((self.state / "operations-v2").glob(".ocpv2-activation-*.env")))

        closed = close_activation_window(
            state_root=self.state,
            env_file=self.env,
            controller=controller,
        )
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["outcome"], "SUCCESS")
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])

    def test_poll_failure_never_changes_persistent_flag_and_close_restores_timers(self):
        controller = self._controller()
        self._open(controller=controller)

        def runner(_):
            return 2, json.dumps({"status": "BLOCKED", "blocked": 1})

        with self.assertRaisesRegex(OCPActivationWindowError, "poll failed"):
            poll_activation_window_once(
                state_root=self.state,
                env_file=self.env,
                runner=runner,
            )

        self.assertEqual(activation_flag_value(self.env), "0")
        failed = load_activation_window(self.state)
        self.assertEqual(failed["outcome"], "POLL_FAILED")
        self.assertEqual(failed["last_poll_exit_code"], 2)

        closed = close_activation_window(
            state_root=self.state,
            env_file=self.env,
            controller=controller,
            body_failed=True,
        )
        self.assertEqual(closed["status"], "CLOSED_AFTER_FAILURE")
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])

    def test_restore_failure_stays_recovery_required(self):
        controller = FakeController(
            {
                DEFAULT_RECONCILE_TIMER: True,
                DEFAULT_OCP_TIMER: True,
            },
            fail_start=(DEFAULT_RECONCILE_TIMER,),
        )
        self._open(controller=controller)

        with self.assertRaisesRegex(OCPActivationWindowError, "cleanup incomplete"):
            close_activation_window(
                state_root=self.state,
                env_file=self.env,
                controller=controller,
            )

        record = load_activation_window(self.state)
        self.assertEqual(record["status"], "RECOVERY_REQUIRED")
        self.assertFalse(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        self.assertEqual(activation_flag_value(self.env), "0")

    def test_stale_window_recovery_restores_prior_active_timers(self):
        controller = self._controller()
        opened_at = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
        self._open(controller=controller, now=opened_at)
        orphan = self.state / "operations-v2" / ".ocpv2-activation-orphan.env"
        orphan.write_text("OCP_FULL_PLAN_ACTIVATION_ENABLED=1\n", encoding="utf-8")
        orphan.chmod(0o600)

        recovered = recover_activation_window(
            state_root=self.state,
            env_file=self.env,
            controller=controller,
            now=opened_at + timedelta(seconds=61),
        )
        self.assertEqual(recovered["status"], "RECOVERED")
        self.assertEqual(recovered["outcome"], "STALE_WINDOW_RECOVERY")
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        self.assertEqual(activation_flag_value(self.env), "0")
        self.assertFalse(orphan.exists())

    def test_initially_inactive_timer_is_preserved(self):
        controller = FakeController(
            {
                DEFAULT_RECONCILE_TIMER: True,
                DEFAULT_OCP_TIMER: False,
            }
        )
        self._open(controller=controller)
        close_activation_window(
            state_root=self.state,
            env_file=self.env,
            controller=controller,
        )
        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertFalse(controller.states[DEFAULT_OCP_TIMER])
        self.assertNotIn(("start", DEFAULT_OCP_TIMER), controller.events)

    @patch("runtime.orchestrator.ocpv2_activation_window.subprocess.run")
    def test_systemd_watchdog_schedules_forced_recovery(self, run):
        scheduler = SystemdTransientRecoveryScheduler()
        unit = scheduler.schedule(
            window_id="TEST:WINDOW",
            delay_seconds=90,
            state_root=self.state,
            env_file=self.env,
        )

        self.assertTrue(unit.startswith("gch-ocpv2-activation-window-recovery-"))
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["systemd-run", "--user"])
        self.assertIn("--on-active=90s", command)
        self.assertIn("--collect", command)
        self.assertIn("runtime.orchestrator.ocpv2_activation_window", command)
        self.assertIn("recover", command)
        self.assertIn("--force", command)

    def test_watchdog_schedule_failure_rolls_back_without_pausing_timers(self):
        controller = self._controller()
        scheduler = FakeScheduler(fail=True)
        with self.assertRaises(RuntimeError):
            self._open(controller=controller, scheduler=scheduler)

        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        record = load_activation_window(self.state)
        self.assertEqual(record["status"], "CLOSED_AFTER_FAILURE")
        self.assertEqual(activation_flag_value(self.env), "0")

    def test_stop_failure_is_cleaned_up(self):
        controller = FakeController(
            {
                DEFAULT_RECONCILE_TIMER: True,
                DEFAULT_OCP_TIMER: True,
            },
            fail_stop=(DEFAULT_OCP_TIMER,),
        )
        with self.assertRaises(RuntimeError):
            self._open(controller=controller)

        self.assertTrue(controller.states[DEFAULT_RECONCILE_TIMER])
        self.assertTrue(controller.states[DEFAULT_OCP_TIMER])
        self.assertEqual(load_activation_window(self.state)["status"], "CLOSED_AFTER_FAILURE")

    def test_flag_must_remain_off_in_persistent_env(self):
        write_env(self.env, flag="1")
        with self.assertRaisesRegex(OCPActivationWindowError, "baseline must be 0"):
            self._open()

    def test_active_mode_and_policy_ref_are_required(self):
        write_env(self.env, mode="OBSERVE_ONLY")
        with self.assertRaisesRegex(OCPActivationWindowError, "OCP_MODE must be ACTIVE"):
            self._open()

        write_env(self.env, policy="")
        with self.assertRaisesRegex(OCPActivationWindowError, "policy ref required"):
            self._open()

    def test_unfinished_window_blocks_second_open(self):
        controller = self._controller()
        self._open(controller=controller)
        with self.assertRaisesRegex(OCPActivationWindowError, "requires recovery"):
            open_activation_window(
                state_root=self.state,
                env_file=self.env,
                controller=controller,
                scheduler=FakeScheduler(),
            )

    def test_tampered_marker_is_rejected(self):
        controller = self._controller()
        self._open(controller=controller)
        marker = activation_window_path(self.state)
        value = json.loads(marker.read_text(encoding="utf-8"))
        value["status"] = "CLOSED"
        marker.write_text(json.dumps(value), encoding="utf-8")

        with self.assertRaisesRegex(OCPActivationWindowError, "digest mismatch"):
            load_activation_window(self.state)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_successor_stage_runtime as runtime
from runtime.orchestrator.remote_control_envelope import (
    LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
)
from runtime.orchestrator.remote_operator_service import ControlMode


class _Transport:
    def __init__(self):
        self.filtered_calls = []

    def receive(self, *, limit=16):
        raise AssertionError("unfiltered receive must not be used for P3 canary")

    def receive_request_kind(self, request_kind, *, limit=16):
        self.filtered_calls.append((request_kind, limit))
        return ()

    def acknowledge_delivery(self, message_id):
        raise AssertionError("no delivery expected")

    def publish_projection(self, projection):
        raise AssertionError("no projection expected")


class _Service:
    def __init__(self, transport):
        self.transport = transport

    def poll_once(self, *, mode):
        self.transport.receive(limit=16)
        return SimpleNamespace(
            mode=ControlMode(mode).value,
            received=0,
            validated=0,
            executed=0,
            diagnosed=0,
            projected=0,
            acknowledged=0,
            blocked=0,
            inspected=0,
            activated=0,
            full_plan_activated=0,
            onboarded=0,
            successor_release_staged=0,
            p3_promotion_admitted=0,
            p3_canary_activated=0,
        )


class P3CanaryTransportFilterTests(unittest.TestCase):
    def test_run_once_prefilters_p3_canary_before_service_poll(self):
        transport = _Transport()
        service = _Service(transport)
        config = SimpleNamespace(mode=ControlMode.LIFECYCLE_V2_P3_CANARY)

        with patch.object(runtime, "compose_service", return_value=service):
            result = runtime.run_once(config)

        self.assertEqual(result["p3_canary_activated"], 0)
        self.assertEqual(
            transport.filtered_calls,
            [(LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND, 16)],
        )


if __name__ == "__main__":
    unittest.main()

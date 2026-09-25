from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    PROJECT_ONBOARDING_KIND,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


class FakeTransport:
    def __init__(self):
        self.items = (RawControlEnvelope(
            source_repository_id=None,
            source_channel_id="CTRL",
            source_actor_id="235775273",
            source_message_id="17",
            content=b"{}",
            received_at="2026-09-25T00:05:00+00:00",
        ),)
        self.projections: list[dict] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return self.items[:limit]

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(message_id)


def onboarding_envelope(*, mode: str, policy_ref: str = "OCP-PROJECT-ONBOARDING-R1"):
    payload = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": PROJECT_ONBOARDING_KIND,
        "message_id": f"ONBOARD-{mode}",
        "sequence": 4,
        "issued_at": "2026-09-25T00:00:00+00:00",
        "expires_at": "2026-09-25T01:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "TEST",
            "channel_id": "CTRL",
            "source_actor_id": "235775273",
            "source_message_id": "17",
        },
        "payload": {
            "schema_version": "orchestration.project-onboarding-request.v1",
            "alias": "ai-commerce-intelligence",
            "project_root": "/srv/ai-commerce-intelligence",
            "mapping_root": "/srv/harness/contract-mappings",
            "expected_branch": "m6-successor",
            "expected_head": "a" * 40,
            "mode": mode,
            "preflight_digest": None if mode == "DRY_RUN" else "b" * 64,
        },
        "payload_digest": "",
        "authorization": {"project_onboarding_policy_ref": policy_ref},
        "envelope_sha256": "",
    }
    return validate_remote_control_envelope(
        seal_remote_control_envelope(payload),
        now=datetime(2026, 9, 25, 0, 5, tzinfo=timezone.utc),
    )


class ProjectOnboardingServiceTests(unittest.TestCase):
    def service(self, envelope, *, enabled=True, policy_ref="OCP-PROJECT-ONBOARDING-R1"):
        transport = FakeTransport()
        calls = []

        def onboard(value):
            calls.append(value.payload.mode)
            return {
                "schema_version": "orchestration.remote-project-onboarding-status-projection.v1",
                "message_id": value.message_id,
                "alias": value.payload.alias,
                "request_digest": value.payload.request_digest,
                "mode": value.payload.mode,
                "result_class": "PROJECT_ONBOARDING_COMPLETED",
            }

        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(AssertionError("legacy ingress must not handle onboarding")),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(AssertionError("mutation executor must not handle onboarding")),
            onboard_authorized=onboard,
            project_onboarding_enabled=enabled,
            project_onboarding_policy_ref=policy_ref,
        )
        return service, transport, calls

    def test_dry_run_is_allowed_in_control_read_only(self):
        service, transport, calls = self.service(onboarding_envelope(mode="DRY_RUN"))
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, ["DRY_RUN"])
        self.assertEqual(result.onboarded, 1)
        self.assertEqual(result.blocked, 0)
        self.assertEqual(transport.projections[0]["result_class"], "PROJECT_ONBOARDING_COMPLETED")

    def test_bootstrap_requires_active_mode(self):
        service, transport, calls = self.service(onboarding_envelope(mode="BOOTSTRAP"))
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.onboarded, 0)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(transport.projections[0]["result_class"], "MODE_BLOCKED")

    def test_wrong_policy_fails_closed(self):
        service, transport, calls = self.service(
            onboarding_envelope(mode="DRY_RUN", policy_ref="WRONG-POLICY")
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "PROJECT_ONBOARDING_AUTHORIZATION_MISMATCH",
        )

    def test_disabled_fails_closed(self):
        service, transport, calls = self.service(
            onboarding_envelope(mode="DRY_RUN"), enabled=False
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(calls, [])
        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"], "PROJECT_ONBOARDING_DISABLED"
        )


if __name__ == "__main__":
    unittest.main()

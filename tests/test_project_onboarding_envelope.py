from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.remote_control_envelope import (
    PROJECT_ONBOARDING_KIND,
    RemoteControlEnvelopeError,
    RemoteProjectOnboardingAuthorization,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)


class ProjectOnboardingEnvelopeTests(unittest.TestCase):
    def _raw(self) -> dict:
        return {
            "schema_version": "orchestration.remote-control-envelope.v1",
            "request_kind": PROJECT_ONBOARDING_KIND,
            "message_id": "ONBOARD-MSG-001",
            "sequence": 1,
            "issued_at": "2026-09-25T00:00:00Z",
            "expires_at": "2026-09-25T01:00:00Z",
            "actor": "GPT_OPERATOR",
            "transport": {
                "adapter_id": "GITHUB_CONTROL_V1",
                "channel_id": "PR:1",
                "source_actor_id": "235775273",
                "source_message_id": "123456",
            },
            "payload": {
                "schema_version": "orchestration.project-onboarding-request.v1",
                "alias": "ai-commerce-intelligence",
                "project_root": "/srv/ai-commerce-intelligence",
                "mapping_root": "/srv/harness/contract-mappings",
                "expected_branch": "m6-successor",
                "expected_head": "a" * 40,
                "mode": "DRY_RUN",
                "preflight_digest": None,
            },
            "payload_digest": "0" * 64,
            "authorization": {"project_onboarding_policy_ref": "OCP-PROJECT-ONBOARDING-R1"},
            "envelope_sha256": "0" * 64,
        }

    def test_onboarding_has_dedicated_typed_authorization(self) -> None:
        sealed = seal_remote_control_envelope(self._raw())
        envelope = validate_remote_control_envelope(
            sealed, now=datetime(2026, 9, 25, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(envelope.request_kind, PROJECT_ONBOARDING_KIND)
        self.assertEqual(envelope.payload.mode, "DRY_RUN")
        self.assertIsInstance(envelope.authorization, RemoteProjectOnboardingAuthorization)
        self.assertEqual(
            envelope.authorization.project_onboarding_policy_ref,
            "OCP-PROJECT-ONBOARDING-R1",
        )

    def test_onboarding_rejects_host_inspection_authorization(self) -> None:
        raw = self._raw()
        raw["authorization"] = {"inspection_policy_ref": "RDC-INDEPENDENT-LIVE-20260923"}
        sealed = seal_remote_control_envelope(raw)
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "authorization"):
            validate_remote_control_envelope(
                sealed, now=datetime(2026, 9, 25, 0, 5, tzinfo=timezone.utc)
            )


if __name__ == "__main__":
    unittest.main()

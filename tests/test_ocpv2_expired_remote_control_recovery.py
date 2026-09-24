from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.ocpv2_runtime_service import RuntimeConfig, _compose_service
from runtime.orchestrator.remote_control_envelope import (
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    seal_remote_control_envelope,
)
from runtime.orchestrator.remote_operator_service import ControlMode
from runtime.orchestrator.remote_operator_transport import RawControlEnvelope


class _ExpiredControlAdapter:
    def __init__(self, raw: RawControlEnvelope) -> None:
        self.raw = raw
        self.projections: list[dict[str, object]] = []
        self.acks: list[str] = []

    def receive(self, *, limit=16):
        return (self.raw,)[:limit]

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(str(message_id))

    def has_durable_ack(self, *args, **kwargs):
        return False

    def prepare_recovery_delivery(self, **kwargs):
        return None


def _expired_inspection_raw() -> RawControlEnvelope:
    request = HostInspectionRequestV1.from_mapping({
        "schema_version": "orchestration.host-inspection-request.v1",
        "request_id": "REQ-EXPIRED-1",
        "correlation_id": "CORR-EXPIRED-1",
        "project_alias": "global-gpt-harness-engineering",
        "operation": "git.status",
        "arguments": {},
        "state_change_required": False,
    })
    sealed = seal_remote_control_envelope({
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": "HOST_INSPECTION",
        "message_id": "MSG-EXPIRED-1",
        "sequence": 900001,
        "issued_at": "2026-09-23T00:00:00+00:00",
        "expires_at": "2026-09-23T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:1",
            "source_actor_id": "235775273",
            "source_message_id": "900001",
        },
        "payload": request.to_dict(),
        "payload_digest": "",
        "authorization": {"inspection_policy_ref": "RDC-INDEPENDENT-LIVE-20260923"},
        "envelope_sha256": "",
    })
    return RawControlEnvelope(
        source_repository_id=987654,
        source_channel_id="PR:1",
        source_actor_id="235775273",
        source_message_id="900001",
        content=json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        received_at="2026-09-23T00:01:00+00:00",
    )


class OCPv2ExpiredRemoteControlRecoveryTests(unittest.TestCase):
    def test_expired_host_inspection_is_projected_and_acked_without_stalling_poll(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            state = root / "state"
            state.mkdir()
            token = root / "token"
            token.write_text("x\n", encoding="utf-8")
            token.chmod(0o600)

            adapter = _ExpiredControlAdapter(_expired_inspection_raw())
            config = RuntimeConfig(
                mode=ControlMode.ACTIVE,
                repo_root=repo,
                control_repository_id=987654,
                control_pr_number=1,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=state,
                environment={},
                host_inspection_enabled=True,
            )

            with patch("runtime.orchestrator.ocpv2_runtime_service.GitHubRESTClient", return_value=Mock()), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.GitHubControlAdapter", return_value=adapter), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.resolve_harness_state_root", return_value=repo), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.HostInspectionPort") as inspection_port:
                service = _compose_service(config)
                result = service.poll_once(mode=config.mode)

            self.assertEqual(result.received, 1)
            self.assertEqual(result.blocked, 1)
            self.assertEqual(result.projected, 1)
            self.assertEqual(result.acknowledged, 1)
            self.assertEqual(adapter.acks, ["MSG-EXPIRED-1"])
            self.assertEqual(len(adapter.projections), 1)
            self.assertEqual(adapter.projections[0]["result_class"], "HOST_INSPECTION_EXPIRED")
            inspection_port.return_value.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

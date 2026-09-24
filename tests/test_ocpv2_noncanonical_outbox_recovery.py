from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.orchestrator.ocpv2_runtime_service import RuntimeConfig, _compose_service
from runtime.orchestrator.remote_operator_outbox import (
    RemoteInspectionProjectionV1,
    RemoteResultOutbox,
)
from runtime.orchestrator.remote_operator_service import ControlMode


class _RecoveryAdapter:
    def __init__(self) -> None:
        self.projections: list[dict[str, object]] = []
        self.acks: list[str] = []
        self.recovery_deliveries: list[dict[str, str]] = []
        self.events: list[str] = []

    def publish_projection(self, projection):
        self.events.append("publish")
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.events.append("ack")
        self.acks.append(str(message_id))

    def has_durable_ack(self, *args, **kwargs):
        return False

    def prepare_recovery_delivery(self, **kwargs):
        self.events.append("prepare")
        self.recovery_deliveries.append({key: str(value) for key, value in kwargs.items()})


class OCPv2NoncanonicalOutboxRecoveryTests(unittest.TestCase):
    def test_pending_inspection_recovers_with_exact_transport_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            state = root / "state"
            state.mkdir()
            token = root / "token"
            token.write_text("x\n", encoding="utf-8")
            token.chmod(0o600)

            projection = RemoteInspectionProjectionV1(
                projection_id="INSP-recovery-test",
                message_id="MSG-INSP-RECOVERY-1",
                request_id="REQ-INSP-RECOVERY-1",
                correlation_id="CORR-INSP-RECOVERY-1",
                project_alias="global-gpt-harness-engineering",
                operation="user_service.properties",
                request_digest="a" * 64,
                status="OK",
                data={"unit_id": "ocpv2.service"},
            )
            persisted = RemoteResultOutbox(state / "outbox")
            persisted.enqueue_projection(projection)

            receipt_dir = state / "receipts" / "GITHUB_CONTROL_V1" / "PR:1"
            receipt_dir.mkdir(parents=True)
            (receipt_dir / f"{projection.message_id}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "orchestration.remote-operator-receipt.v1",
                        "message_id": projection.message_id,
                        "envelope_sha256": "b" * 64,
                        "directive_digest": "d" * 64,
                        "transport_adapter_id": "GITHUB_CONTROL_V1",
                        "transport_channel_id": "PR:1",
                        "source_actor_id": "235775273",
                        "source_message_id": "5800000001",
                        "control_content_sha256": "c" * 64,
                        "sequence": 1,
                        "received_at": "2026-09-24T00:00:00+00:00",
                        "validation_status": "RECEIVED",
                        "canonical_receipt_refs": [],
                        "terminal_projection_status": "PENDING",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

            adapter = _RecoveryAdapter()
            config = RuntimeConfig(
                mode=ControlMode.CONTROL_READ_ONLY,
                repo_root=repo,
                control_repository_id=987654,
                control_pr_number=1,
                allowed_actor_ids=("235775273",),
                token_file=token,
                state_root=state,
                environment={},
            )

            with patch("runtime.orchestrator.ocpv2_runtime_service.GitHubRESTClient", return_value=Mock()), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.GitHubControlAdapter", return_value=adapter), \
                 patch("runtime.orchestrator.ocpv2_runtime_service.resolve_harness_state_root", return_value=repo):
                _compose_service(config)

            self.assertEqual(
                adapter.recovery_deliveries,
                [{
                    "source_message_id": "5800000001",
                    "message_id": projection.message_id,
                    "content_sha256": "c" * 64,
                }],
            )
            self.assertEqual(adapter.events, ["prepare", "publish", "ack"])
            self.assertEqual([item["projection_id"] for item in adapter.projections], [projection.projection_id])
            self.assertEqual(adapter.acks, [projection.message_id])
            self.assertEqual(RemoteResultOutbox(state / "outbox").pending(), ())


if __name__ == "__main__":
    unittest.main()

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
    def __init__(self, *, durable_ack: bool = False) -> None:
        self.projections: list[dict[str, object]] = []
        self.acks: list[str] = []
        self.recovery_deliveries: list[dict[str, str]] = []
        self.durable_ack_checks: list[dict[str, str]] = []
        self.events: list[str] = []
        self.durable_ack = durable_ack

    def publish_projection(self, projection):
        self.events.append("publish")
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.events.append("ack")
        self.acks.append(str(message_id))

    def has_durable_ack(self, message_id, *, source_message_id="", content_sha256=""):
        self.durable_ack_checks.append({
            "message_id": str(message_id),
            "source_message_id": str(source_message_id),
            "content_sha256": str(content_sha256),
        })
        return self.durable_ack

    def prepare_recovery_delivery(self, **kwargs):
        self.events.append("prepare")
        self.recovery_deliveries.append({key: str(value) for key, value in kwargs.items()})


class OCPv2NoncanonicalOutboxRecoveryTests(unittest.TestCase):
    def _arrange_pending(self, root: Path):
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
        RemoteResultOutbox(state / "outbox").enqueue_projection(projection)

        delivery_root = state / "projection-deliveries"
        delivery_root.mkdir(parents=True)
        (delivery_root / f"{projection.message_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": "orchestration.remote-projection-delivery.v1",
                    "message_id": projection.message_id,
                    "source_message_id": "5800000001",
                    "control_content_sha256": "c" * 64,
                    "envelope_sha256": "b" * 64,
                    "request_kind": "HOST_INSPECTION",
                    "bound_at": "2026-09-24T00:00:00+00:00",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

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
        return repo, state, projection, config

    def _compose_with(self, repo: Path, config: RuntimeConfig, adapter: _RecoveryAdapter):
        with patch("runtime.orchestrator.ocpv2_runtime_service.GitHubRESTClient", return_value=Mock()), \
             patch("runtime.orchestrator.ocpv2_runtime_service.GitHubControlAdapter", return_value=adapter), \
             patch("runtime.orchestrator.ocpv2_runtime_service.resolve_harness_state_root", return_value=repo):
            _compose_service(config)

    def test_pending_inspection_recovers_with_exact_transport_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state, projection, config = self._arrange_pending(Path(td))
            adapter = _RecoveryAdapter()

            self._compose_with(repo, config, adapter)

            exact = {
                "source_message_id": "5800000001",
                "message_id": projection.message_id,
                "content_sha256": "c" * 64,
            }
            self.assertEqual(adapter.durable_ack_checks, [{
                "message_id": projection.message_id,
                "source_message_id": "5800000001",
                "content_sha256": "c" * 64,
            }])
            self.assertEqual(adapter.recovery_deliveries, [exact])
            self.assertEqual(adapter.events, ["prepare", "publish", "ack"])
            self.assertEqual([item["projection_id"] for item in adapter.projections], [projection.projection_id])
            self.assertEqual(adapter.acks, [projection.message_id])
            self.assertEqual(RemoteResultOutbox(state / "outbox").pending(), ())
            self.assertFalse((state / "projection-deliveries" / f"{projection.message_id}.json").exists())

    def test_durable_remote_ack_finishes_local_recovery_without_duplicate_publish(self):
        with tempfile.TemporaryDirectory() as td:
            repo, state, projection, config = self._arrange_pending(Path(td))
            adapter = _RecoveryAdapter(durable_ack=True)

            self._compose_with(repo, config, adapter)

            self.assertEqual(adapter.durable_ack_checks, [{
                "message_id": projection.message_id,
                "source_message_id": "5800000001",
                "content_sha256": "c" * 64,
            }])
            self.assertEqual(adapter.recovery_deliveries, [])
            self.assertEqual(adapter.events, [])
            self.assertEqual(adapter.projections, [])
            self.assertEqual(adapter.acks, [])
            self.assertEqual(RemoteResultOutbox(state / "outbox").pending(), ())
            self.assertFalse((state / "projection-deliveries" / f"{projection.message_id}.json").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

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

    def publish_projection(self, projection):
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(str(message_id))

    def has_durable_ack(self, *args, **kwargs):
        return False

    def prepare_recovery_delivery(self, **kwargs):
        raise AssertionError("noncanonical recovery must not require canonical execution binding")


class OCPv2NoncanonicalOutboxRecoveryTests(unittest.TestCase):
    def test_pending_inspection_recovers_without_canonical_execution_binding(self):
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

            self.assertEqual([item["projection_id"] for item in adapter.projections], [projection.projection_id])
            self.assertEqual(adapter.acks, [projection.message_id])
            self.assertEqual(RemoteResultOutbox(state / "outbox").pending(), ())


if __name__ == "__main__":
    unittest.main()

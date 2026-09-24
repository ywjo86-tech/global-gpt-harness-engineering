from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.operator_transport.github_control_adapter import GitHubControlAdapterError
from runtime.orchestrator.ocpv2_runtime_service import (
    RuntimeConfig,
    _compose_service,
    _projection_secret_findings,
)
from runtime.orchestrator.remote_operator_outbox import (
    RemoteInspectionProjectionV1,
    RemoteResultOutbox,
)
from runtime.orchestrator.remote_operator_service import ControlMode


class _SecretBlockingAdapter:
    def __init__(self) -> None:
        self.projections: list[dict[str, object]] = []
        self.acks: list[str] = []

    def publish_projection(self, projection):
        canonical = json.dumps(
            projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if _projection_secret_findings(canonical):
            raise GitHubControlAdapterError("SECRET_LIKE_PROJECTION")
        self.projections.append(dict(projection))

    def acknowledge_delivery(self, message_id):
        self.acks.append(str(message_id))

    def has_durable_ack(self, *args, **kwargs):
        return False

    def prepare_recovery_delivery(self, **kwargs):
        return None


class OCPv2SecretLikeProjectionRecoveryTests(unittest.TestCase):
    def test_pending_secret_like_inspection_is_quarantined_and_status_acknowledged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            state = root / "state"
            token = root / "token"
            token.write_text("x\n", encoding="utf-8")
            token.chmod(0o600)

            outbox = RemoteResultOutbox(state / "outbox")
            poison = RemoteInspectionProjectionV1(
                projection_id="INSP-POISON",
                message_id="MSG-POISON",
                request_id="REQ-POISON",
                correlation_id="CORR-POISON",
                project_alias="demo",
                operation="filesystem.read",
                request_digest="a" * 64,
                status="OK",
                data={"text": "authorization: bearer-value"},
            )
            outbox.enqueue_projection(poison)

            config = RuntimeConfig(
                mode=ControlMode.CONTROL_READ_ONLY,
                repo_root=repo,
                control_repository_id=987654,
                control_pr_number=7,
                allowed_actor_ids=("123",),
                token_file=token,
                state_root=state,
                environment={},
            )
            adapter = _SecretBlockingAdapter()

            with patch(
                "runtime.orchestrator.ocpv2_runtime_service.GitHubRESTClient",
                return_value=Mock(),
            ), patch(
                "runtime.orchestrator.ocpv2_runtime_service.GitHubControlAdapter",
                return_value=adapter,
            ), patch(
                "runtime.orchestrator.ocpv2_runtime_service.recover_pending_canonical_results",
                return_value=None,
            ), patch(
                "runtime.orchestrator.ocpv2_runtime_service.resolve_harness_state_root",
                return_value=repo,
            ):
                _compose_service(config)

            self.assertEqual(RemoteResultOutbox(state / "outbox").pending(), ())
            quarantine = state / "outbox" / "quarantined" / "INSP-POISON.json"
            self.assertTrue(quarantine.is_file())
            self.assertEqual(len(adapter.projections), 1)
            status = adapter.projections[0]
            self.assertEqual(
                status["schema_version"],
                "orchestration.remote-inspection-status-projection.v1",
            )
            self.assertEqual(status["result_class"], "HOST_INSPECTION_PROJECTION_BLOCKED")
            self.assertEqual(status["message_id"], "MSG-POISON")
            self.assertNotIn("bearer-value", repr(status))
            self.assertEqual(adapter.acks, ["MSG-POISON"])


if __name__ == "__main__":
    unittest.main()

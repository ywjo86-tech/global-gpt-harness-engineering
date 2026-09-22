from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from runtime.operator_transport.github_control_adapter import (
    GitHubControlAdapter,
    GitHubControlConfig,
)
from runtime.operator_transport.github_rest_client import (
    GitHubRESTClient,
    VerifiedRepository,
)
from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA
from runtime.orchestrator.remote_operator_envelope import (
    REMOTE_OPERATOR_ENVELOPE_SCHEMA,
    seal_remote_envelope,
    validate_remote_envelope,
)
from runtime.orchestrator.remote_operator_ingress import validate_ingress
from runtime.orchestrator import remote_operator_receipt as receipt_module
from runtime.orchestrator.remote_operator_receipt import (
    ReceiptStatus,
    RemoteOperatorReceiptError,
    RemoteOperatorReceiptStore,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PREFIX = "OCPV2_CONTROL_V2\n"


def _envelope(*, message_id="MSG-FA-1", sequence=1, source_message_id="701"):
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": message_id,
        "sequence": sequence,
        "issued_at": "2026-09-22T12:00:00+00:00",
        "expires_at": "2026-09-22T13:00:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-FA",
            "source_actor_id": "235775273",
            "source_message_id": source_message_id,
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": "T1",
        "task_execution_id": "E1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "T1",
            "task_execution_id": "E1",
            "current_stage": "ENTRY",
            "requested_next_stage": "PREPARE",
            "required_capabilities": ["reasoning"],
            "state_change_required": True,
            "input_artifact_digests": [],
            "gate_id": "G1",
            "directive_id": f"D-{message_id}",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "a" * 64,
            "continuation_owner_epoch": 1,
            "canonical_run_state_sha256": "a" * 64,
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "b" * 40,
            "runtime_release_digest": "c" * 64,
        },
        "authorization": {
            "risk_envelope_ref": "",
            "risk_envelope_digest": "",
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
    return validate_remote_envelope(
        seal_remote_envelope(payload),
        now=datetime(2026, 9, 22, 12, 5, tzinfo=timezone.utc),
    )


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        status, payload = self.responses.pop(0)
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode("utf-8")
        return status, payload


class FakeRESTClient:
    repository_id = 222
    control_pr_number = 7

    def __init__(self, comments):
        self.comments = tuple(comments)

    def verify_repository(self):
        return VerifiedRepository(
            repository_id=self.repository_id,
            full_name="owner/private-control",
            private=True,
        )

    def list_comments(self):
        self.verify_repository()
        return self.comments

    def publish_comment(self, body):
        return {"id": 999, "body": body}


def _token_file(root: Path) -> Path:
    path = root / "github.token"
    path.write_text("ghp_test_token\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _control_comment(*, comment_id: int, actor_id: int = 235775273):
    payload = {
        "schema_version": REMOTE_OPERATOR_ENVELOPE_SCHEMA,
        "message_id": f"MSG-{comment_id}",
    }
    return {
        "id": comment_id,
        "body": CONTROL_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "created_at": "2026-09-22T12:00:00Z",
        "user": {"id": actor_id},
    }


class FinalAcceptanceReleaseBlockerTests(unittest.TestCase):
    def test_ingress_persists_recovery_binding_before_receipt_commit(self):
        params = inspect.signature(validate_ingress).parameters
        self.assertIn("before_receipt_commit", params)

        with tempfile.TemporaryDirectory() as td:
            store = RemoteOperatorReceiptStore(Path(td))
            env = _envelope()
            events = []
            original_record = store.record_received

            def record_received(value):
                events.append("receipt")
                return original_record(value)

            store.record_received = record_received
            decision = validate_ingress(
                env,
                receipt_store=store,
                allowed_adapter_id="GITHUB_CONTROL_V1",
                allowed_channel_id="CTRL-FA",
                allowed_source_actor_ids=("235775273",),
                expected_risk_envelope_digest=None,
                before_receipt_commit=lambda envelope, directive: events.append("binding"),
            )
            self.assertTrue(decision.accepted)
            self.assertEqual(events, ["binding", "receipt"])

    def test_receipt_replay_repairs_missing_sequence_watermark(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = RemoteOperatorReceiptStore(root)
            env = _envelope()
            real_save = receipt_module.durable_json_save
            writes = 0

            def crash_between_receipt_and_watermark(path, value):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("synthetic crash before sequence watermark")
                return real_save(path, value)

            with patch.object(receipt_module, "durable_json_save", side_effect=crash_between_receipt_and_watermark):
                with self.assertRaises(RemoteOperatorReceiptError):
                    store.record_received(env)

            recovered = RemoteOperatorReceiptStore(root)
            self.assertEqual(recovered.classify_delivery(env), ReceiptStatus.IDEMPOTENT_REPLAY)
            recovered.record_received(env)
            same_sequence_other_message = _envelope(
                message_id="MSG-FA-OTHER",
                sequence=1,
                source_message_id="702",
            )
            self.assertEqual(
                recovered.classify_delivery(same_sequence_other_message),
                ReceiptStatus.REPLAY_REJECTED,
            )

    def test_github_comment_listing_paginates_beyond_first_100(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_page = [{"id": index, "body": "x"} for index in range(1, 101)]
            second_page = [{"id": 101, "body": "y"}]
            http = FakeHTTP([
                (200, {"id": 123, "private": True, "full_name": "owner/private-control"}),
                (200, first_page),
                (200, second_page),
            ])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=_token_file(root),
                http_transport=http,
            )
            comments = client.list_comments()
            self.assertEqual(len(comments), 101)
            self.assertEqual(comments[-1]["id"], 101)
            self.assertIn("page=1", http.calls[1][1])
            self.assertIn("page=2", http.calls[2][1])

    def test_rejected_control_comment_does_not_starve_later_valid_comment(self):
        config = GitHubControlConfig(
            allowed_repository_id=222,
            control_pr_number=7,
            allowed_actor_ids=frozenset({"235775273"}),
            max_comment_bytes=65536,
            poll_limit=16,
        )
        adapter = GitHubControlAdapter(
            config=config,
            rest_client=FakeRESTClient((
                _control_comment(comment_id=1, actor_id=999),
                _control_comment(comment_id=2),
            )),
            secret_scan=lambda payload: {},
        )
        try:
            messages = adapter.receive()
        except Exception as exc:
            self.fail(f"one rejected comment starved the poll: {exc}")
        self.assertEqual([item.source_message_id for item in messages], ["2"])

    def test_ocpv2_workflow_paths_cover_runner_and_dependency_lock(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ocpv2-r2-ci.yml").read_text(encoding="utf-8")
        self.assertIn('"scripts/ocpv2_full_regression.py"', text)
        self.assertIn('"requirements/full-mcp.txt"', text)


if __name__ == "__main__":
    unittest.main()

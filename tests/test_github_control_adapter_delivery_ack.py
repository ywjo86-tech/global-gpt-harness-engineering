from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.operator_transport.github_control_adapter import GitHubControlAdapter, GitHubControlConfig
from runtime.operator_transport.github_rest_client import GitHubRESTClientError, VerifiedRepository


CONTROL_PREFIX = "OCPV2_CONTROL_V2\n"


class FakeRESTClient:
    def __init__(self, comments, *, fail_publish=False):
        self.repository_id = 222
        self.control_pr_number = 7
        self.comments = tuple(comments)
        self.fail_publish = fail_publish
        self.publish_calls = []

    def verify_repository(self):
        return VerifiedRepository(repository_id=222, full_name="owner/private-control", private=True)

    def list_comments(self):
        return self.comments

    def publish_comment(self, body):
        self.publish_calls.append(body)
        if self.fail_publish:
            raise GitHubRESTClientError("offline")
        return {"id": 900}


def config():
    return GitHubControlConfig(
        allowed_repository_id=222,
        control_pr_number=7,
        allowed_actor_ids=frozenset({"235775273"}),
    )


def comment(*, marker="A"):
    payload = {
        "message_id": "M1",
        "schema_version": "orchestration.remote-operator-envelope.v2",
        "marker": marker,
    }
    return {
        "id": 444,
        "body": CONTROL_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "created_at": "2026-09-21T00:00:00Z",
        "user": {"id": 235775273},
    }


def adapter(path: Path, comments, *, fail_publish=False):
    return GitHubControlAdapter(
        config=config(),
        rest_client=FakeRESTClient(comments, fail_publish=fail_publish),
        secret_scan=lambda payload: {},
        delivery_ack_path=path,
    )


class DurableDeliveryAckTests(unittest.TestCase):
    def test_successful_publish_suppresses_exact_delivery_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "acks.json"
            first = adapter(path, (comment(),))
            self.assertEqual(len(first.receive()), 1)
            first.publish_projection({"schema_version": "x", "message_id": "M1"})
            first.acknowledge_delivery("M1")

            second = adapter(path, (comment(),))
            self.assertEqual(second.receive(), ())

    def test_edited_same_comment_is_not_hidden_by_durable_ack(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "acks.json"
            first = adapter(path, (comment(marker="A"),))
            self.assertEqual(len(first.receive()), 1)
            first.publish_projection({"schema_version": "x", "message_id": "M1"})
            first.acknowledge_delivery("M1")

            edited = adapter(path, (comment(marker="B"),))
            received = edited.receive()
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].source_message_id, "444")

    def test_publish_failure_does_not_create_durable_ack(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "acks.json"
            first = adapter(path, (comment(),), fail_publish=True)
            self.assertEqual(len(first.receive()), 1)
            with self.assertRaises(GitHubRESTClientError):
                first.publish_projection({"schema_version": "x", "message_id": "M1"})

            second = adapter(path, (comment(),))
            self.assertEqual(len(second.receive()), 1)

    def test_ack_without_successful_publish_is_not_durable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "acks.json"
            first = adapter(path, (comment(),))
            self.assertEqual(len(first.receive()), 1)
            first.acknowledge_delivery("M1")

            second = adapter(path, (comment(),))
            self.assertEqual(len(second.receive()), 1)


if __name__ == "__main__":
    unittest.main()

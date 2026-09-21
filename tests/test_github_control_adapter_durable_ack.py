from __future__ import annotations

import json
import unittest

from runtime.operator_transport.github_control_adapter import (
    GitHubControlAdapter,
    GitHubControlConfig,
)
from runtime.operator_transport.github_rest_client import VerifiedRepository


CONTROL_PREFIX = "OCPV2_CONTROL_V2\n"
RESULT_PREFIX = "OCPV2_RESULT_V1\n"


class FakeRESTClient:
    def __init__(self, comments):
        self.repository_id = 222
        self.control_pr_number = 7
        self.comments = tuple(comments)

    def verify_repository(self):
        return VerifiedRepository(
            repository_id=222,
            full_name="owner/private-control",
            private=True,
        )

    def list_comments(self):
        return self.comments

    def publish_comment(self, body):
        return {"id": 900, "body": body}


def config():
    return GitHubControlConfig(
        allowed_repository_id=222,
        control_pr_number=7,
        allowed_actor_ids=frozenset({"235775273"}),
    )


def issue_comment(comment_id, body, actor_id=235775273):
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-09-21T00:00:00Z",
        "user": {"id": actor_id},
    }


def control(comment_id=444, message_id="M1"):
    body = CONTROL_PREFIX + json.dumps(
        {
            "message_id": message_id,
            "schema_version": "orchestration.remote-operator-envelope.v2",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return issue_comment(comment_id, body)


def result(comment_id=445, message_id="M1", actor_id=235775273):
    body = RESULT_PREFIX + json.dumps(
        {
            "message_id": message_id,
            "result_class": "OBSERVED",
            "schema_version": "orchestration.remote-service-projection.v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return issue_comment(comment_id, body, actor_id=actor_id)


class GitHubControlAdapterDurableAckTests(unittest.TestCase):
    def adapter(self, comments):
        return GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(comments),
            secret_scan=lambda payload: {},
        )

    def test_prior_result_projection_suppresses_control_on_fresh_adapter(self):
        adapter = self.adapter((control(), result()))
        self.assertEqual(adapter.receive(), ())

    def test_result_for_different_message_does_not_suppress_control(self):
        adapter = self.adapter((control(message_id="M1"), result(message_id="M2")))
        received = adapter.receive()
        self.assertEqual([item.source_message_id for item in received], ["444"])

    def test_untrusted_result_projection_does_not_suppress_control(self):
        adapter = self.adapter((control(), result(actor_id=999)))
        received = adapter.receive()
        self.assertEqual([item.source_message_id for item in received], ["444"])


if __name__ == "__main__":
    unittest.main()

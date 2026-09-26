from __future__ import annotations

import inspect
import json
import unittest

from runtime.operator_transport import github_control_adapter
from runtime.operator_transport.github_control_adapter import (
    GitHubControlAdapter,
    GitHubControlAdapterError,
    GitHubControlConfig,
)
from runtime.operator_transport.github_rest_client import VerifiedRepository


class FakeRESTClient:
    def __init__(self, *, repository_id=222, control_pr_number=7, comments=()):
        self.repository_id = repository_id
        self.control_pr_number = control_pr_number
        self.comments = tuple(comments)
        self.publish_calls = []
        self.verify_calls = 0

    def verify_repository(self):
        self.verify_calls += 1
        return VerifiedRepository(
            repository_id=self.repository_id,
            full_name="owner/private-control",
            private=True,
        )

    def list_comments(self):
        self.verify_repository()
        return self.comments

    def publish_comment(self, body):
        self.verify_repository()
        self.publish_calls.append(body)
        return {"id": 900}


def config(**changes):
    values = {
        "allowed_repository_id": 222,
        "control_pr_number": 7,
        "allowed_actor_ids": frozenset({"235775273"}),
        "max_comment_bytes": 65536,
        "poll_limit": 16,
    }
    values.update(changes)
    return GitHubControlConfig(**values)


def comment(*, comment_id=101, actor_id=235775273, body=None):
    if body is None:
        body = "OCPV2_CONTROL_V2\n" + json.dumps(
            {"schema_version": "orchestration.remote-operator-envelope.v2"},
            sort_keys=True,
            separators=(",", ":"),
        )
    return {
        "id": comment_id,
        "body": body,
        "created_at": "2026-09-21T00:00:00Z",
        "user": {"id": actor_id},
    }


class GitHubControlAdapterTests(unittest.TestCase):
    def test_wrong_repository_numeric_id_is_source_not_allowed(self):
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(repository_id=333, comments=(comment(),)),
            secret_scan=lambda payload: {},
        )
        with self.assertRaisesRegex(GitHubControlAdapterError, "SOURCE_NOT_ALLOWED"):
            adapter.receive()

    def test_wrong_pr_channel_is_source_not_allowed(self):
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(control_pr_number=8, comments=(comment(),)),
            secret_scan=lambda payload: {},
        )
        with self.assertRaisesRegex(GitHubControlAdapterError, "SOURCE_NOT_ALLOWED"):
            adapter.receive()

    def test_wrong_actor_is_actor_not_allowed(self):
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(comments=(comment(actor_id=999),)),
            secret_scan=lambda payload: {},
        )
        with self.assertRaisesRegex(GitHubControlAdapterError, "ACTOR_NOT_ALLOWED"):
            adapter.receive()

    def test_stable_comment_id_becomes_stable_source_message_id(self):
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(comments=(comment(comment_id=444),)),
            secret_scan=lambda payload: {},
        )
        messages = adapter.receive()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].source_repository_id, 222)
        self.assertEqual(messages[0].source_channel_id, "PR:7")
        self.assertEqual(messages[0].source_actor_id, "235775273")
        self.assertEqual(messages[0].source_message_id, "444")

    def test_control_comment_body_is_parsed_but_not_executed_by_adapter(self):
        payload = {"message_id": "M1", "schema_version": "orchestration.remote-operator-envelope.v2"}
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(comments=(comment(body="OCPV2_CONTROL_V2\n" + json.dumps(payload)),)),
            secret_scan=lambda body: {},
        )
        raw = adapter.receive()[0]
        self.assertEqual(json.loads(raw.content.decode("utf-8")), payload)
        source = inspect.getsource(github_control_adapter)
        for forbidden in (
            "MigrationStore", "DurableFullPlanSupervisor", "ProductionToolTransport",
            "subprocess", "os.system", "git commit", "git push",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_result_prefix_is_ignored_on_receive(self):
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=FakeRESTClient(comments=(
                comment(comment_id=1, body="OCPV2_RESULT_V1\n{}"),
                comment(comment_id=2),
            )),
            secret_scan=lambda payload: {},
        )
        messages = adapter.receive()
        self.assertEqual([item.source_message_id for item in messages], ["2"])

    def test_request_kind_filter_applies_before_poll_limit(self):
        unrelated = [
            comment(
                comment_id=100 + index,
                body="OCPV2_CONTROL_V2\n" + json.dumps(
                    {"message_id": f"OTHER-{index}", "request_kind": "HOST_INSPECTION"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            for index in range(16)
        ]
        canary = comment(
            comment_id=999,
            body="OCPV2_CONTROL_V2\n" + json.dumps(
                {
                    "message_id": "P3-CANARY-1",
                    "request_kind": "LIFECYCLE_V2_P3_CANARY_ACTIVATION",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        adapter = GitHubControlAdapter(
            config=config(poll_limit=16),
            rest_client=FakeRESTClient(comments=tuple(unrelated + [canary])),
            secret_scan=lambda payload: {},
        )
        messages = adapter.receive_request_kind(
            "LIFECYCLE_V2_P3_CANARY_ACTIVATION",
            limit=16,
        )
        self.assertEqual([item.source_message_id for item in messages], ["999"])
        self.assertEqual(json.loads(messages[0].content.decode("utf-8"))["message_id"], "P3-CANARY-1")

    def test_source_code_repository_is_not_implicitly_accepted(self):
        with self.assertRaisesRegex(GitHubControlAdapterError, "public source repository"):
            config(allowed_repository_id=1254385549)

    def test_secret_like_projection_is_rejected_before_publish(self):
        client = FakeRESTClient()
        adapter = GitHubControlAdapter(
            config=config(),
            rest_client=client,
            secret_scan=lambda payload: {"token": 1},
        )
        with self.assertRaisesRegex(GitHubControlAdapterError, "SECRET_LIKE_PROJECTION"):
            adapter.publish_projection({"projection_id": "P1", "summary": "authorization: secret"})
        self.assertEqual(client.publish_calls, [])

    def test_publish_uses_bounded_result_prefix_and_canonical_json(self):
        client = FakeRESTClient()
        adapter = GitHubControlAdapter(
            config=config(max_comment_bytes=256),
            rest_client=client,
            secret_scan=lambda payload: {},
        )
        adapter.publish_projection({"z": 1, "a": "x"})
        self.assertEqual(client.publish_calls, ['OCPV2_RESULT_V1\n{"a":"x","z":1}'])


if __name__ == "__main__":
    unittest.main()

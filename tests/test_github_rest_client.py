from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.operator_transport.github_rest_client import (
    GitHubRESTClient,
    GitHubRESTClientError,
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


def token_file(root: Path, *, mode=0o600) -> Path:
    path = root / "github.token"
    path.write_text("ghp_test_token\n", encoding="utf-8")
    os.chmod(path, mode)
    return path


class GitHubRESTClientTests(unittest.TestCase):
    def test_repository_numeric_identity_must_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            http = FakeHTTP([(200, {"id": 999, "private": True, "full_name": "o/control"})])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=token_file(root),
                http_transport=http,
            )
            with self.assertRaisesRegex(GitHubRESTClientError, "repository numeric identity mismatch"):
                client.verify_repository()

    def test_public_source_repository_id_1254385549_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(GitHubRESTClientError, "public source repository"):
                GitHubRESTClient(
                    repository_id=1254385549,
                    control_pr_number=7,
                    token_file=token_file(root),
                    http_transport=FakeHTTP([]),
                )

    def test_repository_must_be_private(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            http = FakeHTTP([(200, {"id": 123, "private": False, "full_name": "o/control"})])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=token_file(root),
                http_transport=http,
            )
            with self.assertRaisesRegex(GitHubRESTClientError, "repository must be private"):
                client.verify_repository()

    def test_token_file_symlink_or_group_world_permissions_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad_mode = token_file(root, mode=0o640)
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=bad_mode,
                http_transport=FakeHTTP([]),
            )
            with self.assertRaisesRegex(GitHubRESTClientError, "token file permissions"):
                client.verify_repository()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "real.token"
            target.write_text("token", encoding="utf-8")
            os.chmod(target, 0o600)
            link = root / "github.token"
            link.symlink_to(target)
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=link,
                http_transport=FakeHTTP([]),
            )
            with self.assertRaisesRegex(GitHubRESTClientError, "token file"):
                client.verify_repository()

    def test_list_comments_uses_verified_repository_full_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            http = FakeHTTP([
                (200, {"id": 123, "private": True, "full_name": "owner/private-control"}),
                (200, [{"id": 1, "body": "hello"}]),
            ])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=token_file(root),
                http_transport=http,
            )
            comments = client.list_comments()
            self.assertEqual(comments[0]["id"], 1)
            self.assertEqual(http.calls[0][0], "GET")
            self.assertTrue(http.calls[0][1].endswith("/repositories/123"))
            self.assertEqual(http.calls[1][0], "GET")
            self.assertIn("/repos/owner/private-control/issues/7/comments", http.calls[1][1])
            self.assertIn("per_page=100", http.calls[1][1])
            self.assertIn("direction=asc", http.calls[1][1])

    def test_publish_only_posts_bounded_result_comment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            http = FakeHTTP([
                (200, {"id": 123, "private": True, "full_name": "owner/private-control"}),
                (201, {"id": 88}),
            ])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=token_file(root),
                max_comment_bytes=128,
                http_transport=http,
            )
            response = client.publish_comment("OCPV2_RESULT_V1\n{}")
            self.assertEqual(response["id"], 88)
            self.assertEqual(http.calls[1][0], "POST")
            sent = json.loads(http.calls[1][3].decode("utf-8"))
            self.assertEqual(sent, {"body": "OCPV2_RESULT_V1\n{}"})
            with self.assertRaisesRegex(GitHubRESTClientError, "comment exceeds"):
                client.publish_comment("x" * 129)
            self.assertEqual(len(http.calls), 2)


if __name__ == "__main__":
    unittest.main()

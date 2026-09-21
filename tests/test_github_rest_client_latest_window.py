from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.operator_transport.github_rest_client import GitHubRESTClient


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        status, payload = self.responses.pop(0)
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode("utf-8")
        return status, payload


class GitHubRESTClientLatestWindowTests(unittest.TestCase):
    def test_list_comments_reads_latest_bounded_window(self):
        with tempfile.TemporaryDirectory() as td:
            token = Path(td) / "github.token"
            token.write_text("ghp_test_token\n", encoding="utf-8")
            os.chmod(token, 0o600)
            http = FakeHTTP([
                (200, {"id": 123, "private": True, "full_name": "owner/private-control"}),
                (200, [{"id": 201, "body": "newest"}, {"id": 200, "body": "older"}]),
            ])
            client = GitHubRESTClient(
                repository_id=123,
                control_pr_number=7,
                token_file=token,
                http_transport=http,
            )
            comments = client.list_comments()
            self.assertEqual([item["id"] for item in comments], [201, 200])
            self.assertIn("per_page=100", http.calls[1][1])
            self.assertIn("sort=created", http.calls[1][1])
            self.assertIn("direction=desc", http.calls[1][1])


if __name__ == "__main__":
    unittest.main()

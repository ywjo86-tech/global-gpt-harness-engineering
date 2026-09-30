"""Issuer status endpoint refuses unauthenticated requests and forwards exact scope."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.full_plan_approval_status_app import create_status_app


class Issuer:
    def __init__(self):
        self.calls = []

    def status(self, **kwargs):
        self.calls.append(kwargs)
        return {"payload": {"active": True}, "signature": "test"}


class StatusAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = Path(self.tmp.name) / "status-token"
        token.write_text("a" * 48)
        token.chmod(0o600)
        self.issuer = Issuer()
        self.app = create_status_app(issuer=self.issuer, token_file=token)

    def request(self, *, auth="", body=b"", path="/status", method="POST", content_type="application/json"):
        result = []
        environ = {
            "PATH_INFO": path, "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": content_type,
            "HTTP_AUTHORIZATION": auth, "wsgi.input": io.BytesIO(body),
        }
        data = b"".join(self.app(environ, lambda code, headers: result.append((code, headers))))
        return result[0][0], json.loads(data)

    def test_unauthenticated_and_malformed_do_not_touch_issuer(self):
        body = json.dumps({"decision_id": "d1", "activation_id": "a1", "challenge": "c" * 32}).encode()
        self.assertEqual(self.request(body=body)[0], "401 Unauthorized")
        self.assertEqual(self.request(auth="Bearer " + "a" * 48, body=b"{}")[0], "400 Bad Request")
        self.assertEqual(self.issuer.calls, [])

    def test_authenticated_status_has_exact_binding(self):
        body = json.dumps({"decision_id": "d1", "activation_id": "a1", "challenge": "c" * 32}).encode()
        code, answer = self.request(auth="Bearer " + "a" * 48, body=body)
        self.assertEqual(code, "200 OK")
        self.assertEqual(answer["payload"]["active"], True)
        self.assertEqual(len(self.issuer.calls), 1)
        self.assertEqual(self.issuer.calls[0]["activation_id"], "a1")
        self.assertEqual(self.issuer.calls[0]["challenge"], "c" * 32)


if __name__ == "__main__":
    unittest.main()

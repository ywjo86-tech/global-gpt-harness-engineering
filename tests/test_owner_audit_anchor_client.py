from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.owner_audit_anchor_client import (
    OwnerAuditAnchorClient,
    OwnerAuditAnchorError,
)


class OwnerAuditAnchorClientTests(unittest.TestCase):
    @staticmethod
    def _simulated_client_uid(socket_path: str) -> int:
        """Use a caller identity distinct from the temporary fixture owner."""
        fixture_owner_uid = Path(socket_path).parent.stat().st_uid
        return 0 if fixture_owner_uid != 0 else 1

    def test_client_uses_only_read_operations_for_global_and_project_owner_heads(self):
        with tempfile.TemporaryDirectory() as td:
            socket_path = str(Path(td) / "anchor.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            os.chmod(socket_path, 0o660)
            server.listen(2)
            observed = []
            global_head = {
                "schema_version": "orchestration.ai-office-owner-authority-anchor.v1",
                "generation": 1,
                "change_id": "GLOBAL-OWNER-1",
                "event_sha256": "a" * 64,
            }
            project_head = {
                "schema_version": "orchestration.project-owner-binding-anchor.v2",
                "project_id": "PROJECT-1",
                "generation": 2,
                "change_id": "PROJECT-OWNER-2",
                "event_sha256": "b" * 64,
            }

            def serve():
                for anchor in (global_head, project_head):
                    conn, _ = server.accept()
                    raw = b""
                    while chunk := conn.recv(2048):
                        raw += chunk
                    observed.append(json.loads(raw))
                    response = {
                        "schema_version": "orchestration.ai-office-owner-audit-anchor-response.v1",
                        "status": "OK",
                        "anchor": anchor,
                    }
                    conn.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                    conn.close()
                server.close()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            client_uid = self._simulated_client_uid(socket_path)
            with patch("runtime.orchestrator.owner_audit_anchor_client.os.geteuid", return_value=client_uid):
                result = OwnerAuditAnchorClient(socket_path).read_owner_authority("PROJECT-1")
            thread.join(timeout=2)

        self.assertEqual(result, {
            "global_owner_head": global_head,
            "project_owner_binding_head": project_head,
        })
        self.assertEqual([item["operation"] for item in observed], [
            "READ_GLOBAL_OWNER_HEAD",
            "READ_PROJECT_OWNER_BINDING_HEAD",
        ])
        self.assertEqual(observed[1]["project_id"], "PROJECT-1")

    def test_unavailable_or_malformed_anchor_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            socket_path = str(Path(td) / "anchor.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            os.chmod(socket_path, 0o660)
            server.listen(1)

            def serve_unavailable():
                conn, _ = server.accept()
                while conn.recv(1024):
                    pass
                conn.sendall(json.dumps({
                    "schema_version": "orchestration.ai-office-owner-audit-anchor-response.v1",
                    "status": "UNAVAILABLE",
                    "anchor": None,
                }).encode() + b"\n")
                conn.close()
                server.close()

            thread = threading.Thread(target=serve_unavailable, daemon=True)
            thread.start()
            client_uid = self._simulated_client_uid(socket_path)
            with patch("runtime.orchestrator.owner_audit_anchor_client.os.geteuid", return_value=client_uid):
                with self.assertRaises(OwnerAuditAnchorError):
                    OwnerAuditAnchorClient(socket_path).read_owner_authority("PROJECT-1")
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

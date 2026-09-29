from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.host_inspection_contract import HostInspectionRequestV1
from runtime.orchestrator.host_inspection_port import HostInspectionPort
from runtime.orchestrator.project_onboarding import OnboardingRegistry
from runtime.orchestrator.remote_operator_outbox import (
    RemoteInspectionProjectionV1,
    RemoteResultOutbox,
)


class OCPv2HostInspectionSecretRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "demo"
        self.project.mkdir()
        (self.project / "IMPLEMENTATION_PLAN.md").write_text(
            "# approved plan\n", encoding="utf-8"
        )
        (self.project / "secret-like.txt").write_text(
            "token=abc123\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=self.project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@localhost",
                "add",
                ".",
            ],
            cwd=self.project,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@localhost",
                "commit",
                "-m",
                "baseline",
            ],
            cwd=self.project,
            check=True,
            capture_output=True,
        )
        self.mapping_root = self.base / "mapping"
        report = OnboardingRegistry(self.mapping_root / "aliases").register(
            self.project, "demo"
        )
        self.assertEqual(report["status"], "REGISTERED")
        self.port = HostInspectionPort(
            registry_root=self.mapping_root,
            read_scopes=(".",),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_filesystem_read_redacts_secret_like_text_before_shared_outbox(self) -> None:
        request = HostInspectionRequestV1.from_mapping(
            {
                "schema_version": "orchestration.host-inspection-request.v1",
                "request_id": "INSP-SECRET-1",
                "correlation_id": "CORR-SECRET-1",
                "project_alias": "demo",
                "operation": "filesystem.read",
                "arguments": {"path": "secret-like.txt", "max_bytes": 64},
                "state_change_required": False,
            }
        )

        result = self.port.inspect(request)

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["text"], "token=[REDACTED]\n")

        projection = RemoteInspectionProjectionV1.from_result(
            result, message_id="MSG-SECRET-1"
        )
        outbox = RemoteResultOutbox(self.base / "outbox")
        outbox.enqueue_projection(projection)
        self.assertEqual(len(outbox.pending()), 1)


if __name__ == "__main__":
    unittest.main()

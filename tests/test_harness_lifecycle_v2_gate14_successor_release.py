from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.runtime_release import build_runtime_release, verify_runtime_release


class HarnessLifecycleV2Gate14SuccessorReleaseTest(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, encoding="utf-8"
        ).strip()

    def test_exact_checked_out_head_builds_verified_v2_runtime_release(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        actual_head = self._git(repo, "rev-parse", "HEAD")
        expected_head = str(os.environ.get("HARNESS_G14_EXPECTED_HEAD") or actual_head).strip()
        self.assertEqual(actual_head, expected_head)
        self.assertEqual(self._git(repo, "status", "--porcelain=v1", "-uall"), "")

        expected_tree = self._git(repo, "rev-parse", f"{expected_head}^{{tree}}")
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_runtime_release(repo, Path(directory) / "releases", source_ref=expected_head)
            self.assertEqual(manifest.schema_version, "gch.runtime-release.v2")
            self.assertEqual(manifest.source_head, expected_head)
            self.assertEqual(manifest.publication_head, expected_head)
            self.assertEqual(manifest.source_tree, expected_tree)

            release = Path(manifest.release_path)
            self.assertFalse(release.is_symlink())
            self.assertEqual(verify_runtime_release(release, expected_head), manifest)

            payload = json.loads((release / "RUNTIME_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["source_head"], expected_head)
            self.assertEqual(payload["publication_head"], expected_head)
            self.assertEqual(payload["source_tree"], expected_tree)
            self.assertEqual(payload["manifest_sha256"], manifest.manifest_sha256)


if __name__ == "__main__":
    unittest.main()

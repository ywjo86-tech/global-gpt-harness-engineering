from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator import successor_release_staging as staging


class SuccessorReleaseStagingMissingObjectRegressionTests(unittest.TestCase):
    def test_missing_commit_object_is_reported_absent_instead_of_transport_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )

            full_mcp = staging._BoundedGitFullMcp()

            self.assertFalse(
                full_mcp.object_exists(
                    root,
                    "1" * 40,
                )
            )


if __name__ == "__main__":
    unittest.main()

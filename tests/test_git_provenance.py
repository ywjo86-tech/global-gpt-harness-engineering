from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.git_provenance import touched_paths_between


class GitProvenanceTests(unittest.TestCase):
    def test_historical_touch_survives_later_revert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            (root / "core.py").write_text("SAFE = True\n")
            (root / "owned.py").write_text("VALUE = 0\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            baseline = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            (root / "core.py").write_text("SAFE = False\n")
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "touch core"], check=True)
            (root / "core.py").write_text("SAFE = True\n")
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "revert core"], check=True)
            (root / "owned.py").write_text("VALUE = 1\n")
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "owned change"], check=True)
            current = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(subprocess.check_output(["git", "-C", str(root), "diff", "--name-only", baseline, current], text=True).strip(), "owned.py")
            self.assertEqual(set(touched_paths_between(root, baseline, current)), {"core.py", "owned.py"})


if __name__ == "__main__":
    unittest.main()

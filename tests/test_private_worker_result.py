import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.gate_orchestrator import _private_worker_result_ok


class PrivateWorkerResultTests(unittest.TestCase):
    def test_only_current_owner_regular_0600_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"result.json"; path.write_text("{}"); path.chmod(0o600)
            self.assertTrue(_private_worker_result_ok(path))
            for mode in (0o644,0o640,0o660,0o400):
                path.chmod(mode); self.assertFalse(_private_worker_result_ok(path),oct(mode))
            path.chmod(0o600)
            real=path.lstat()
            with patch.object(Path,"lstat",return_value=os.stat_result((real.st_mode,real.st_ino,real.st_dev,real.st_nlink,real.st_uid+1,real.st_gid,real.st_size,real.st_atime,real.st_mtime,real.st_ctime))):
                self.assertFalse(_private_worker_result_ok(path))

    def test_symlink_directory_and_missing_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/"target"; target.write_text("{}"); target.chmod(0o600)
            link=root/"link"; link.symlink_to(target)
            self.assertFalse(_private_worker_result_ok(link)); self.assertFalse(_private_worker_result_ok(root))
            self.assertFalse(_private_worker_result_ok(root/"missing"))

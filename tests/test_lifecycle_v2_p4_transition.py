from __future__ import annotations
import unittest
from unittest.mock import patch
from runtime.orchestrator.lifecycle_v2_p4_transition import P4TransitionError, execute_p4_cutover

class P4TransitionTests(unittest.TestCase):
    def test_cutover_rejects_missing_admission(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(P4TransitionError,"required receipt"):
                execute_p4_cutover(state_root=tmp,runtime_link=Path(tmp)/"current",source_release=tmp,target_release=tmp,target_head="a"*40,admission_digest="b"*64,cutover_admission_digest="c"*64,job_search_root=tmp)

    def test_no_public_shutdown_or_migration_operation(self):
        import runtime.orchestrator.lifecycle_v2_p4_transition as module
        self.assertFalse(hasattr(module,"shutdown_predecessor"))
        self.assertFalse(hasattr(module,"migrate_existing_runs"))

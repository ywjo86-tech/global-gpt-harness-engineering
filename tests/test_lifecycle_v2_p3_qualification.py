from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.lifecycle_v2_p3_qualification import (
    LifecycleV2P3QualificationError, enter_p4_read_only, execute_p3_canary_and_qualify,
)


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


class LifecycleV2P3QualificationTests(unittest.TestCase):
    def fixture(self, root: Path):
        state, project = root / "state", root / "project"
        state.mkdir(); project.mkdir()
        admission = "a" * 64
        unsigned = {"schema_version":"orchestration.lifecycle-v2-p3-canary-validate-registration.v1","project_alias":"p3-project","candidate_run_id":"p3-candidate","admission_digest":admission,"binding_digest":"b"*64,"evidence_digest":"c"*64,"status":"P3_CANARY_VALIDATE_REGISTERED","runtime_current_switch_authorized":False,"predecessor_shutdown_authorized":False,"existing_run_migration_authorized":False,"successor_polling_authorized":False,"execution_authorized":False}
        registration = {**unsigned, "registration_digest": hashlib.sha256(canonical(unsigned)).hexdigest()}
        path = state / "p3-canary-validate-registrations" / f"{admission}.json"
        path.parent.mkdir(); path.write_bytes(canonical(registration))
        (project / "docs/harness").mkdir(parents=True)
        source = Path(__file__).parents[1]
        for name in ("P3_CANARY_VALIDATE_FULL_PLAN.md", "P3_CANARY_VALIDATE_SPEC.md", "P3_CANARY_EXECUTE_SPEC.md", "P4_READ_ONLY_ENTRY_SPEC.md"):
            (project / "docs/harness" / name).write_bytes((source / "docs/harness" / name).read_bytes())
        return state, project, admission

    def test_bounded_canary_qualifies_and_enters_read_only_p4(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, project, admission = self.fixture(Path(tmp))
            git = [subprocess.CompletedProcess([],0,"p3/test\n",""), subprocess.CompletedProcess([],0,"d"*40+"\n","")]
            runner = lambda *a, **k: subprocess.CompletedProcess([],0,"","" )
            with patch("runtime.orchestrator.lifecycle_v2_p3_qualification.subprocess.run", side_effect=git):
                qualification = execute_p3_canary_and_qualify(state_root=state, project_root=project, project_alias="p3-project", candidate_run_id="p3-candidate", admission_digest=admission, expected_branch="p3/test", expected_head="d"*40, approval_ref="P3-CANARY-EXECUTE", runner=runner)
            self.assertEqual(qualification["status"], "P3_FINAL_QUALIFIED")
            entry = enter_p4_read_only(state_root=state, admission_digest=admission, qualification_digest=qualification["qualification_digest"], approval_ref="P4-READ-ONLY")
            self.assertEqual(entry["status"], "P4_READ_ONLY_ENTERED")
            self.assertFalse(entry["runtime_current_switch_authorized"])

    def test_widened_registration_and_failed_canary_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, project, admission = self.fixture(Path(tmp))
            path = state / "p3-canary-validate-registrations" / f"{admission}.json"
            value = json.loads(path.read_text()); value["execution_authorized"] = True; path.write_bytes(canonical(value))
            with self.assertRaisesRegex(LifecycleV2P3QualificationError, "authority widened"):
                execute_p3_canary_and_qualify(state_root=state, project_root=project, project_alias="p3-project", candidate_run_id="p3-candidate", admission_digest=admission, expected_branch="p3/test", expected_head="d"*40, approval_ref="P3-CANARY-EXECUTE")

    def test_p4_rejects_unknown_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp); admission = "a" * 64
            with self.assertRaisesRegex(LifecycleV2P3QualificationError, "qualification required"):
                enter_p4_read_only(state_root=state, admission_digest=admission, qualification_digest="b"*64, approval_ref="P4-READ-ONLY")

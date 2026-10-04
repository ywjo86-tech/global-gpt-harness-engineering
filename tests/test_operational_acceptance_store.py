from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operational_acceptance import (
    OperationalAcceptanceStore,
    build_operational_acceptance_record,
)


def record(runtime_ref: str, created_at: str):
    return build_operational_acceptance_record(
        project_id="P",
        run_id="R",
        full_plan_terminal_state={
            "state":"COMPLETED",
            "state_sha256":"a"*64,
            "authority_core_sha256":"b"*64,
            "terminal_reason":"ALL_GATES_COMPLETED",
        },
        post_change_gate={
            "status":"PASS",
            "failures":[],
            "gate_evidence_sha256":("c" if runtime_ref=="runtime:old" else "d")*64,
        },
        monitor_health_receipt_refs=("attention.json","timer.json"),
        process_lifecycle_diagnostic_refs=("process.json",),
        runtime_release_identity_refs=(runtime_ref,),
        created_at=created_at,
    )


class OperationalAcceptanceStoreTests(unittest.TestCase):
    def test_new_runtime_acceptance_appends_history_and_advances_latest(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            store=OperationalAcceptanceStore(root)
            first=record("runtime:old","2026-10-04T07:00:00+00:00")
            second=record("runtime:new","2026-10-04T08:00:00+00:00")
            store.save_observation(first)
            store.save_observation(second)
            latest=store.load_latest("P","R")
            self.assertEqual(latest.record_sha256,second.record_sha256)
            self.assertEqual(latest.runtime_release_identity_refs,("runtime:new",))
            history=root/"_workspace"/"operational-acceptance"/"P"/"R"
            self.assertTrue((history/f"{first.record_sha256}.json").is_file())
            self.assertTrue((history/f"{second.record_sha256}.json").is_file())
            self.assertEqual(len(list(history.glob("*.json"))),3)


if __name__=="__main__":
    unittest.main()

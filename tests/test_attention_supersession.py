from __future__ import annotations
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.orchestrator.production_attention import AttentionOutbox
from runtime.orchestrator.production_attention_watch import discover_pending_attention


class AttentionSupersessionTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.run_supersession import (
                RunSupersessionRecord, RunSupersessionStore, evaluate_supersession,
            )
        except ModuleNotFoundError as exc:
            self.fail(f"run supersession module missing: {exc}")
        return RunSupersessionRecord,RunSupersessionStore,evaluate_supersession

    def record(self):
        Record,_,_=self.api()
        return Record.create(
            project_id="P",predecessor_run_id="R1",predecessor_authority_sha256="a"*64,
            successor_run_id="R2",successor_authority_sha256="b"*64,
            reason="MIGRATED_TO_SUCCESSOR",evidence_refs=("migration:M1","successor-state:"+"c"*64))

    def test_timestamp_alone_never_supersedes(self):
        _,_,evaluate=self.api()
        old={"project_id":"P","run_id":"R1","event_id":"e"*64,"created_at":"2026-09-18T00:00:00+00:00"}
        newer={"project_id":"P","run_id":"R2","authority_core_sha256":"b"*64,"created_at":"2026-09-19T00:00:00+00:00","semantic_progress_verified":True}
        assessment=evaluate(old,newer,record=None)
        self.assertFalse(assessment.archived)
        self.assertEqual(assessment.reason,"NO_BOUND_SUPERSESSION_RECORD")

    def test_bound_successor_record_archives_but_does_not_delete_event(self):
        _,_,evaluate=self.api(); record=self.record()
        event={"project_id":"P","run_id":"R1","event_id":"e"*64,"authority_core_sha256":"a"*64}
        successor={"project_id":"P","run_id":"R2","authority_core_sha256":"b"*64,"semantic_progress_verified":True}
        result=evaluate(event,successor,record=record)
        self.assertTrue(result.archived)
        self.assertEqual(result.disposition,"ARCHIVED_SUPERSEDED")
        self.assertEqual(event["event_id"],"e"*64)

    def test_unrelated_newer_run_cannot_suppress(self):
        _,_,evaluate=self.api(); record=self.record()
        event={"project_id":"P","run_id":"R1","event_id":"e"*64,"authority_core_sha256":"a"*64}
        unrelated={"project_id":"P","run_id":"R3","authority_core_sha256":"d"*64,"semantic_progress_verified":True}
        self.assertFalse(evaluate(event,unrelated,record=record).archived)

    def test_store_round_trip_preserves_auditable_record(self):
        _,Store,_=self.api(); record=self.record()
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)); store.save(record)
            loaded=store.find(project_id="P",predecessor_run_id="R1")
            self.assertEqual(len(loaded),1)
            self.assertEqual(loaded[0].record_sha256,record.record_sha256)

    def test_attention_watch_excludes_explicitly_superseded_historical_event(self):
        _,Store,_=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); state_root=root/"state"; state_root.mkdir()
            jobs=state_root/"_workspace/production-full-plan-jobs/P"; jobs.mkdir(parents=True)
            legacy=root/"legacy"; legacy.mkdir()
            old_job={"schema_version":"orchestration.production-full-plan-job.v1","project_id":"P","run_id":"R1","harness_root":str(legacy),"harness_state_root":str(state_root),"authority_core_sha256":"a"*64}
            new_job={"schema_version":"orchestration.production-full-plan-job.v1","project_id":"P","run_id":"R2","harness_root":str(legacy),"harness_state_root":str(state_root),"authority_core_sha256":"b"*64}
            (jobs/"R1.job.json").write_text(json.dumps(old_job)); (jobs/"R2.job.json").write_text(json.dumps(new_job))
            old_base=state_root/"_workspace/production-full-plan/P/R1"; old_base.mkdir(parents=True)
            old_state={"state":"BLOCKED","current_gate":"G1","state_sha256":"c"*64,"progress_sequence":4,"last_semantic_progress_at":"2026-09-18T00:00:00+00:00"}
            (old_base/"state.json").write_text(json.dumps(old_state))
            event=AttentionOutbox(old_base,project_id="P",run_id="R1").publish(kind="BLOCKED",state="BLOCKED",reason="old failure",gate_id="G1",delivery_class="DEFERRED_INCIDENT")
            new_base=state_root/"_workspace/production-full-plan/P/R2"; new_base.mkdir(parents=True)
            new_state={"state":"READY","current_gate":"G1","state_sha256":"d"*64,"progress_sequence":5,"last_semantic_progress_at":"2026-09-19T00:00:00+00:00"}
            (new_base/"state.json").write_text(json.dumps(new_state))
            Store(state_root).save(self.record())
            created=datetime.fromisoformat(event["created_at"])
            rows=discover_pending_attention(state_root,now=created+timedelta(seconds=600))
            self.assertFalse(any(row["run_id"]=="R1" and row["event_id"]==event["event_id"] for row in rows))
            self.assertTrue((old_base/"attention/pending"/f"{event['event_id']}.json").is_file())


if __name__=="__main__": unittest.main()

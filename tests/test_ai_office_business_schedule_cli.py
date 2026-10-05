from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from runtime.ai_office.business_schedule import AIOfficeBusinessScheduleError, AIOfficeBusinessScheduleStore
from runtime.ai_office.business_schedule_cli import main


class BusinessScheduleCliTests(unittest.TestCase):
    def _init(self, root, registry_ref="schedule-registry:test"):
        return [
            "--state-root",root,"init",
            "--office-id","global-ai-office",
            "--registry-ref",registry_ref,
        ]

    def _put(self, root, *, revision=0, status="SCHEDULED"):
        return [
            "--state-root",root,"put",
            "--item-id","daily-review",
            "--title","Daily review",
            "--start-at","2026-10-05T09:00:00+09:00",
            "--status",status,
            "--source-ref","schedule:operator",
            "--revision",str(revision),
        ]

    def test_init_empty_schedule_is_canonical_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            output=StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(self._init(td)),0)
                self.assertEqual(main(self._init(td)),0)
            store=AIOfficeBusinessScheduleStore(td)
            self.assertEqual(store.load_items(),())
            self.assertEqual(store.load_registry().office_id,"global-ai-office")

    def test_init_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError,"different content"):
                main(self._init(td,"schedule-registry:other"))

    def test_put_is_idempotent_for_same_content(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
                self.assertEqual(main(self._put(td)),0)
                self.assertEqual(main(self._put(td)),0)
            self.assertEqual(len(AIOfficeBusinessScheduleStore(td).load_items()),1)

    def test_put_allows_exact_next_revision(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
                main(self._put(td))
                main(self._put(td, revision=1, status="COMPLETED"))
            item=AIOfficeBusinessScheduleStore(td).load_items()[0]
            self.assertEqual(item.revision,1)
            self.assertEqual(item.status,"COMPLETED")

    def test_put_rejects_revision_gap(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
                main(self._put(td))
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError,"advance by one"):
                main(self._put(td, revision=2, status="COMPLETED"))

    def test_validate_prints_bounded_summary_only(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
                main(self._put(td))
            output=StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--state-root",td,"validate"]),0)
            value=json.loads(output.getvalue())
            self.assertEqual(value["status"],"PASS")
            self.assertEqual(value["item_count"],1)
            self.assertEqual(value["scheduled_count"],1)
            self.assertEqual(value["timezone_name"],"Asia/Seoul")
            self.assertNotIn("state_root",value)
            self.assertNotIn("items",value)


if __name__=="__main__":
    unittest.main()

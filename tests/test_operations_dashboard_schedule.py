from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone

from runtime.ai_office.business_schedule import (
    BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
    AIOfficeBusinessScheduleError,
    AIOfficeBusinessScheduleStore,
    BusinessScheduleItemV1,
)
from runtime.orchestrator.operations_dashboard_schedule import read_operations_dashboard_today_schedule
from runtime.orchestrator.operations_dashboard_source import build_live_operations_dashboard_projection


class DashboardScheduleAdapterTests(unittest.TestCase):
    def _item(self, item_id, title, start_at, status="SCHEDULED"):
        return BusinessScheduleItemV1(
            BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
            item_id, title, start_at, status, f"schedule:{item_id}", 0,
        )

    def test_missing_schedule_store_preserves_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(read_operations_dashboard_today_schedule(td))

    def test_today_kst_filters_sorts_and_projects_bounded_fields(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_item(self._item("later", "Later", "2026-10-05T16:30:00+09:00"))
            store.publish_item(self._item("early", "Early", "2026-10-05T09:00:00+09:00", "IN_PROGRESS"))
            store.publish_item(self._item("tomorrow", "Tomorrow", "2026-10-06T09:00:00+09:00"))
            value=read_operations_dashboard_today_schedule(
                td, now=datetime(2026,10,5,6,tzinfo=timezone.utc)
            )
            self.assertEqual(value["source_state"], "CANONICAL_BUSINESS_SCHEDULE_V1")
            self.assertEqual(value["items"], [
                {"time":"09:00","title":"Early","status":"IN_PROGRESS"},
                {"time":"16:30","title":"Later","status":"SCHEDULED"},
            ])

    def test_live_projection_consumes_canonical_schedule(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_item(self._item("daily", "Daily", "2026-10-05T10:00:00+09:00"))
            projection=build_live_operations_dashboard_projection(
                td, now=datetime(2026,10,5,3,tzinfo=timezone.utc)
            )
            self.assertEqual(projection["today_schedule"]["source_state"], "CANONICAL_BUSINESS_SCHEDULE_V1")
            self.assertEqual(projection["today_schedule"]["items"][0]["time"], "10:00")

    def test_corrupt_schedule_blocks_live_projection(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            path=store.publish_item(self._item("daily", "Daily", "2026-10-05T10:00:00+09:00"))
            value=json.loads(path.read_text())
            value["status"]="COMPLETED"
            path.write_text(json.dumps(value))
            with self.assertRaises(AIOfficeBusinessScheduleError):
                build_live_operations_dashboard_projection(
                    td, now=datetime(2026,10,5,3,tzinfo=timezone.utc)
                )


if __name__ == "__main__":
    unittest.main()

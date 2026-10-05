from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.ai_office.business_schedule import (
    BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
    BUSINESS_SCHEDULE_REGISTRY_SCHEMA_V1,
    AIOfficeBusinessScheduleError,
    AIOfficeBusinessScheduleStore,
    BusinessScheduleItemV1,
    BusinessScheduleRegistryV1,
)


class BusinessScheduleStoreTests(unittest.TestCase):
    def _registry(self):
        return BusinessScheduleRegistryV1(
            BUSINESS_SCHEDULE_REGISTRY_SCHEMA_V1,
            "global-ai-office",
            "Asia/Seoul",
            "schedule-registry:test",
        )

    def _item(self, *, revision=0, status="SCHEDULED", title="Daily review"):
        return BusinessScheduleItemV1(
            BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
            "daily-review",
            title,
            "2026-10-05T09:00:00+09:00",
            status,
            "schedule:test",
            revision,
        )

    def test_registry_round_trip_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            path=store.publish_registry(self._registry())
            self.assertEqual(store.publish_registry(self._registry()),path)
            self.assertEqual(store.load_registry().timezone_name,"Asia/Seoul")

    def test_conflicting_registry_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_registry(self._registry())
            other=BusinessScheduleRegistryV1(
                BUSINESS_SCHEDULE_REGISTRY_SCHEMA_V1,"global-ai-office","Asia/Seoul","schedule-registry:other"
            )
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError,"different content"):
                store.publish_registry(other)

    def test_round_trip_normalizes_time_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_registry(self._registry())
            path=store.publish_item(self._item())
            self.assertEqual(store.publish_item(self._item()), path)
            item=store.load_items()[0]
            self.assertEqual(item.start_at, "2026-10-05T00:00:00+00:00")
            self.assertEqual(item.status, "SCHEDULED")

    def test_item_requires_registry(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError,"registry missing"):
                store.publish_item(self._item())

    def test_revision_must_advance_exactly_one(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_registry(self._registry())
            store.publish_item(self._item())
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError, "advance by one"):
                store.publish_item(self._item(revision=2, status="COMPLETED"))
            store.publish_item(self._item(revision=1, status="COMPLETED"))
            self.assertEqual(store.load_items()[0].status, "COMPLETED")

    def test_initial_revision_must_be_zero(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_registry(self._registry())
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError, "initial schedule revision"):
                store.publish_item(self._item(revision=1))

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(AIOfficeBusinessScheduleError, "timezone-aware"):
            BusinessScheduleItemV1(
                BUSINESS_SCHEDULE_ITEM_SCHEMA_V1,
                "x", "Title", "2026-10-05T09:00:00", "SCHEDULED", "schedule:test", 0,
            )

    def test_digest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeBusinessScheduleStore(td)
            store.publish_registry(self._registry())
            path=store.publish_item(self._item())
            value=json.loads(path.read_text())
            value["title"]="tampered"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError, "digest mismatch"):
                store.load_items()

    def test_schedule_root_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            workspace=root/"_workspace"
            workspace.mkdir()
            target=root/"redirect"
            target.mkdir()
            (workspace/"ai-office-business-schedule").symlink_to(target, target_is_directory=True)
            store=AIOfficeBusinessScheduleStore(root)
            with self.assertRaisesRegex(AIOfficeBusinessScheduleError, "unsafe schedule root"):
                store.publish_registry(self._registry())


if __name__ == "__main__":
    unittest.main()

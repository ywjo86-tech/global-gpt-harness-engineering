from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

from runtime.ai_office.report_index import (
    OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
    AIOfficeReportIndexStore,
    OfficeReportIndexRegistryV1,
)
from runtime.orchestrator.operations_dashboard_reports import read_operations_dashboard_recent_reports
from runtime.orchestrator.operations_dashboard_source import build_live_operations_dashboard_projection
from tests.test_ai_office_report_index import report


class DashboardReportAdapterTests(unittest.TestCase):
    def _store(self, root):
        store=AIOfficeReportIndexStore(root)
        store.publish_registry(OfficeReportIndexRegistryV1(
            OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
            "global-ai-office","report-index:test",
        ))
        return store

    def test_missing_registry_preserves_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(read_operations_dashboard_recent_reports(td))

    def test_empty_registry_is_canonical_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self._store(td)
            value=read_operations_dashboard_recent_reports(td)
            self.assertEqual(value["source_state"],"CANONICAL_OFFICE_REPORT_INDEX_V1")
            self.assertEqual(value["items"],[])

    def test_reports_sort_newest_first_and_project_bounded_fields(self):
        with tempfile.TemporaryDirectory() as td:
            store=self._store(td)
            store.publish_report(
                report_id="old",title="Old Report",
                published_at="2026-10-04T09:00:00+09:00",
                report=report("p-old","r-old"),report_ref="office-report:old",
            )
            store.publish_report(
                report_id="new",title="New Report",
                published_at="2026-10-05T16:00:00+09:00",
                report=report("p-new","r-new"),report_ref="office-report:new",
            )
            value=read_operations_dashboard_recent_reports(td)
            self.assertEqual(value["items"],[
                {"title":"New Report","date":"2026-10-05"},
                {"title":"Old Report","date":"2026-10-04"},
            ])

    def test_live_projection_consumes_report_index(self):
        with tempfile.TemporaryDirectory() as td:
            store=self._store(td)
            store.publish_report(
                report_id="one",title="Operations Daily",
                published_at="2026-10-05T10:00:00+09:00",
                report=report(),report_ref="office-report:one",
            )
            projection=build_live_operations_dashboard_projection(
                td,now=datetime(2026,10,5,3,tzinfo=timezone.utc)
            )
            self.assertEqual(projection["recent_reports"]["source_state"],"CANONICAL_OFFICE_REPORT_INDEX_V1")
            self.assertEqual(projection["recent_reports"]["items"],[
                {"title":"Operations Daily","date":"2026-10-05"}
            ])


if __name__=="__main__":
    unittest.main()

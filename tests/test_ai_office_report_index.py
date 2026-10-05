from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.ai_office.report_index import (
    OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
    AIOfficeReportIndexError,
    AIOfficeReportIndexStore,
    OfficeReportIndexRegistryV1,
    office_report_from_mapping,
)
from runtime.ai_office.reporting import (
    OFFICE_KPI_SCHEMA_V1,
    OFFICE_REPORT_SCHEMA_V1,
    OFFICE_STATUS_SCHEMA_V1,
    OfficeKPIProjectionV1,
    OfficeReportV1,
    OfficeStatusProjectionV1,
)


def report(project="project-a", run="run-a", state="RUNNING") -> OfficeReportV1:
    return OfficeReportV1(
        OFFICE_REPORT_SCHEMA_V1,
        OfficeStatusProjectionV1(
            OFFICE_STATUS_SCHEMA_V1, project, run, state, 3, "", ""
        ),
        OfficeKPIProjectionV1(OFFICE_KPI_SCHEMA_V1, 2, 1, False, False),
        "assignment:test", "", "", ("observation:1","observation:2"), ("recovery:1",),
    )


class ReportIndexStoreTests(unittest.TestCase):
    def _registry(self, ref="report-index:test"):
        return OfficeReportIndexRegistryV1(
            OFFICE_REPORT_INDEX_REGISTRY_SCHEMA_V1,
            "global-ai-office",
            ref,
        )

    def test_registry_round_trip_and_empty_index(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            path=store.publish_registry(self._registry())
            self.assertEqual(store.publish_registry(self._registry()),path)
            self.assertEqual(store.load_entries(),())
            self.assertEqual(store.load_registry().office_id,"global-ai-office")

    def test_registry_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            with self.assertRaisesRegex(AIOfficeReportIndexError,"different content"):
                store.publish_registry(self._registry("report-index:other"))

    def test_publish_report_round_trip_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            value=report()
            first=store.publish_report(
                report_id="report-001", title="Daily Operations",
                published_at="2026-10-05T15:00:00+09:00",
                report=value, report_ref="office-report:report-001",
            )
            second=store.publish_report(
                report_id="report-001", title="Daily Operations",
                published_at="2026-10-05T15:00:00+09:00",
                report=value, report_ref="office-report:report-001",
            )
            self.assertEqual(first,second)
            entry=store.load_entries()[0]
            self.assertEqual(entry.project_id,"project-a")
            self.assertEqual(entry.report_digest,value.report_digest)
            self.assertEqual(store.load_report("report-001"),value)

    def test_report_id_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            store.publish_report(
                report_id="report-001", title="Daily Operations",
                published_at="2026-10-05T15:00:00+09:00",
                report=report(), report_ref="office-report:report-001",
            )
            with self.assertRaisesRegex(AIOfficeReportIndexError,"different content"):
                store.publish_report(
                    report_id="report-001", title="Different",
                    published_at="2026-10-05T15:00:00+09:00",
                    report=report(), report_ref="office-report:report-001",
                )

    def test_report_digest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            store.publish_report(
                report_id="report-001", title="Daily Operations",
                published_at="2026-10-05T15:00:00+09:00",
                report=report(), report_ref="office-report:report-001",
            )
            path=store.reports_root/"report-001.json"
            value=json.loads(path.read_text())
            value["status"]["workflow_state"]="FAILED"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(AIOfficeReportIndexError,"digest mismatch"):
                store.load_entries()

    def test_entry_binding_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            store.publish_report(
                report_id="report-001", title="Daily Operations",
                published_at="2026-10-05T15:00:00+09:00",
                report=report(), report_ref="office-report:report-001",
            )
            path=store.entries_root/"report-001.json"
            value=json.loads(path.read_text())
            value["project_id"]="other"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(AIOfficeReportIndexError,"entry digest mismatch"):
                store.load_entries()

    def test_wrong_report_shape_rejected(self):
        with self.assertRaisesRegex(AIOfficeReportIndexError,"shape mismatch"):
            office_report_from_mapping({"schema_version":"reviewer.report.v1"})

    def test_naive_published_at_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store=AIOfficeReportIndexStore(td)
            store.publish_registry(self._registry())
            with self.assertRaisesRegex(AIOfficeReportIndexError,"timezone-aware"):
                store.publish_report(
                    report_id="report-001", title="Daily",
                    published_at="2026-10-05T15:00:00",
                    report=report(), report_ref="office-report:report-001",
                )

    def test_root_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            workspace=root/"_workspace"; workspace.mkdir()
            target=root/"redirect"; target.mkdir()
            (workspace/"ai-office-report-index").symlink_to(target,target_is_directory=True)
            with self.assertRaisesRegex(AIOfficeReportIndexError,"unsafe report index root"):
                AIOfficeReportIndexStore(root).publish_registry(self._registry())


if __name__=="__main__":
    unittest.main()

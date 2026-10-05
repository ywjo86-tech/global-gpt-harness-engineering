from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from runtime.ai_office.report_index import AIOfficeReportIndexError, AIOfficeReportIndexStore
from runtime.ai_office.report_index_cli import main
from tests.test_ai_office_report_index import report


class ReportIndexCliTests(unittest.TestCase):
    def _init(self, root):
        return ["--state-root",root,"init","--office-id","global-ai-office","--registry-ref","report-index:test"]

    def _write_report(self, root, name="source.json"):
        path=Path(root)/name
        path.write_text(json.dumps(report().to_dict()))
        return path

    def test_init_empty_index_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                self.assertEqual(main(self._init(td)),0)
                self.assertEqual(main(self._init(td)),0)
            self.assertEqual(AIOfficeReportIndexStore(td).load_entries(),())

    def test_add_verified_office_report_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            source=self._write_report(td)
            args=[
                "--state-root",td,"add",
                "--report-id","report-001",
                "--title","Daily Operations",
                "--published-at","2026-10-05T15:00:00+09:00",
                "--report-file",str(source),
                "--report-ref","office-report:report-001",
            ]
            with redirect_stdout(StringIO()):
                main(self._init(td))
                self.assertEqual(main(args),0)
                self.assertEqual(main(args),0)
            self.assertEqual(len(AIOfficeReportIndexStore(td).load_entries()),1)

    def test_add_reviewer_report_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"reviewer.report.json"
            source.write_text(json.dumps({"schema_version":"reviewer.report.v1","result":"PASS"}))
            with redirect_stdout(StringIO()):
                main(self._init(td))
            with self.assertRaisesRegex(AIOfficeReportIndexError,"shape mismatch"):
                main([
                    "--state-root",td,"add","--report-id","bad","--title","Bad",
                    "--published-at","2026-10-05T15:00:00+09:00",
                    "--report-file",str(source),"--report-ref","reviewer:bad",
                ])

    def test_add_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            real=self._write_report(td)
            link=Path(td)/"link.json"; link.symlink_to(real)
            with redirect_stdout(StringIO()):
                main(self._init(td))
            with self.assertRaisesRegex(AIOfficeReportIndexError,"unsafe"):
                main([
                    "--state-root",td,"add","--report-id","bad","--title","Bad",
                    "--published-at","2026-10-05T15:00:00+09:00",
                    "--report-file",str(link),"--report-ref","office-report:bad",
                ])

    def test_validate_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                main(self._init(td))
            output=StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--state-root",td,"validate"]),0)
            value=json.loads(output.getvalue())
            self.assertEqual(value["status"],"PASS")
            self.assertEqual(value["report_count"],0)
            self.assertNotIn("entries",value)
            self.assertNotIn("state_root",value)


if __name__=="__main__":
    unittest.main()

import unittest

from runtime.ai_office.work_records import build_report_data


class WorkRecordTests(unittest.TestCase):
    def test_verified_result_is_preserved(self):
        report = build_report_data(
            verified_result={
                "target": "AI Office", "date": "2026-09-27",
                "purpose": "AI Office implementation status is recorded for review.",
                "status": "in_progress", "progress": 72,
                "progress_source": "gate-count:5/7",
                "summary": ("One.", "Two.", "Three.", "Four.", "Five."),
                "completed": ("Track A",), "in_progress": ("Track C",),
                "issues": (), "impact": "none", "user_action": "none",
                "next_actions": ("qualify",), "final_state": "in progress",
                "technical_references": ("TASK-C",), "execution_status": "SUCCESS",
            },
            verification={"status": "PASS", "evidence_ref": "verification:C"},
            report_type="implementation_progress", evidence_refs=("evidence:C",),
        )
        self.assertEqual(report.progress, 72)
        self.assertEqual(report.progress_source, "gate-count:5/7")
        self.assertEqual(report.verification_status, "PASS")

    def test_completion_requires_pass(self):
        with self.assertRaisesRegex(ValueError, "PASS"):
            build_report_data({}, {"status": "FAIL"}, "completion_report", ())

    def test_evidence_generator_is_materialized_once(self):
        evidence=(item for item in ("evidence:A", "evidence:B"))
        report = build_report_data(
            verified_result={
                "target": "AI Office", "date": "2026-09-27",
                "purpose": "AI Office evidence is recorded for review.",
                "status": "in_progress", "progress": 50,
                "progress_source": "gate-count:1/2",
                "summary": ("One.", "Two.", "Three.", "Four.", "Five."),
                "completed": (), "in_progress": ("Track",),
                "issues": (), "impact": "none", "user_action": "none",
                "next_actions": ("qualify",), "final_state": "in progress",
                "technical_references": ("TASK",), "execution_status": "SUCCESS",
            },
            verification={"status": "PASS", "evidence_ref": "verification:A"},
            report_type="implementation_progress", evidence_refs=evidence,
        )
        self.assertEqual(report.evidence_refs, ("evidence:A", "evidence:B"))



if __name__ == "__main__":
    unittest.main()

from runtime.ai_office.work_records import build_report_data


def sample_report():
    return build_report_data(
        verified_result={
            "target": "AI Office", "date": "2026-09-27",
            "purpose": "AI Office implementation status is recorded for review.",
            "status": "in_progress", "progress": 72, "progress_source": "gate-count:5/7",
            "summary": ("One.", "Two.", "Three.", "Four.", "Five."),
            "completed": ("Track A",), "in_progress": ("Track C",),
            "issues": ("Reporting pending",), "impact": "P4 waits for reports",
            "user_action": "No action", "next_actions": ("Qualify Track C",),
            "final_state": "In progress", "technical_references": ("TASK-C",),
            "execution_status": "SUCCESS",
        },
        verification={"status": "PASS", "evidence_ref": "verification:C"},
        report_type="implementation_progress", evidence_refs=("evidence:C",),
    )

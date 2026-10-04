from datetime import datetime, timezone
import unittest

from runtime.ai_office.reporting import (
    OFFICE_KPI_SCHEMA_V1,
    OFFICE_REPORT_SCHEMA_V1,
    OFFICE_STATUS_SCHEMA_V1,
    OfficeKPIProjectionV1,
    OfficeReportV1,
    OfficeStatusProjectionV1,
)
from runtime.orchestrator.operator_console_projection import OperatorConsoleProjectionV1
from runtime.orchestrator.operations_read_model import (
    OPERATIONS_READ_MODEL_SCHEMA_V1,
    SourceIdentityV1,
    build_operations_read_model,
    normalize_operations_state,
    normalize_progress,
    resolve_freshness,
)
from runtime.orchestrator.operational_acceptance import build_operational_acceptance_record


def make_console() -> OperatorConsoleProjectionV1:
    return OperatorConsoleProjectionV1(
        project_id="P1",
        run_id="R1",
        task_id="T1",
        gate_id="G1",
        stage="RUNNING",
        execution_readiness="READY",
        operator_authority_label="GPT_OPERATOR",
        transport_state="OBSERVE_ONLY",
        checkpoint_refs=("checkpoint:R1",),
        evidence_refs=("evidence:E1",),
        migration_phase="",
        migration_transaction_sha256="",
        status_flags=(),
    )


def make_office_report() -> OfficeReportV1:
    status = OfficeStatusProjectionV1(
        OFFICE_STATUS_SCHEMA_V1, "P1", "R1", "RUNNING", 3, "", ""
    )
    kpi = OfficeKPIProjectionV1(OFFICE_KPI_SCHEMA_V1, 1, 0, False, False)
    return OfficeReportV1(
        OFFICE_REPORT_SCHEMA_V1,
        status,
        kpi,
        "",
        "",
        "",
        ("observation:E1",),
        (),
    )


class OperationsReadModelContractTests(unittest.TestCase):
    def test_operations_read_model_is_closed_and_source_tagged(self):
        model = build_operations_read_model(
            make_console(),
            make_office_report(),
            source_identities=(
                SourceIdentityV1(
                    "HARNESS", "c591b01", "c591b01", "2026-09-24T00:00:00+00:00"
                ),
                SourceIdentityV1(
                    "OCP", "996a8d1", "996a8d1", "2026-09-24T00:00:01+00:00"
                ),
            ),
            now=datetime(2026, 9, 24, 0, 0, 5, tzinfo=timezone.utc),
        )
        payload = model.to_dict()
        self.assertEqual(payload["schema_version"], OPERATIONS_READ_MODEL_SCHEMA_V1)
        self.assertEqual(
            {row["source_component"] for row in payload["sources"]}, {"HARNESS", "OCP"}
        )
        serialized = repr(payload).lower()
        for forbidden in ("credential", "token", "raw_effect_payload", "final_assignee"):
            self.assertNotIn(forbidden, serialized)

    def test_state_normalization_and_progress_do_not_invent_percent(self):
        normalized, human = normalize_operations_state("WAITING_APPROVAL")
        self.assertEqual(normalized, "WAITING_APPROVAL")
        self.assertEqual(human, "사용자 승인 대기")
        self.assertEqual(normalize_progress(None, ""), (None, ""))

    def test_all_ai_office_workflow_states_map_to_bounded_operations_states(self):
        expected = {
            "NEW": "QUEUED",
            "INTAKE_READY": "PLANNING",
            "INTAKE_BLOCKED": "STALLED",
            "CONTEXT_READY": "PLANNING",
            "SOURCE_BINDING_BLOCKED": "STALLED",
            "PLAN_COORDINATED": "PLANNING",
            "PLAN_HANDOFF_BLOCKED": "STALLED",
            "EXECUTION_PENDING": "QUEUED",
            "WAITING_STATE_CHANGE_AUTHORITY": "WAITING_DEPENDENCY",
            "EXECUTION_IN_PROGRESS": "RUNNING",
            "REVIEW_PENDING": "RUNNING",
            "RECOVERY_COORDINATION": "RECOVERING",
            "COMPLETE": "COMPLETED",
        }
        for workflow_state, operations_state in expected.items():
            with self.subTest(workflow_state=workflow_state):
                normalized, _ = normalize_operations_state(workflow_state)
                self.assertEqual(normalized, operations_state)

    def test_old_source_is_stale(self):
        source = SourceIdentityV1(
            "HARNESS", "v1", "a" * 40, "2026-09-23T23:00:00+00:00"
        )
        self.assertEqual(
            resolve_freshness(
                (source,),
                datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc),
                300,
            ),
            "STALE",
        )

    def test_execution_complete_with_blocked_operational_acceptance_is_not_false_green(self):
        gate = {
            "schema_version": "ai-office.operational-post-change-gate.v1",
            "status": "BLOCKED",
            "failures": ["ATTENTION_WATCH_DISABLED"],
            "gate_evidence_sha256": "b" * 64,
        }
        acceptance = build_operational_acceptance_record(
            project_id="P1",
            run_id="R1",
            full_plan_terminal_state={
                "state": "COMPLETED",
                "state_sha256": "a" * 64,
                "authority_core_sha256": "c" * 64,
                "terminal_reason": "ALL_GATES_COMPLETED",
            },
            post_change_gate=gate,
        )
        status = OfficeStatusProjectionV1(
            OFFICE_STATUS_SCHEMA_V1, "P1", "R1", "COMPLETE", 3, "", ""
        )
        report = OfficeReportV1(
            OFFICE_REPORT_SCHEMA_V1,
            status,
            make_office_report().kpi,
            "",
            "",
            "",
            ("observation:E1",),
            (),
        )
        model = build_operations_read_model(
            make_console(),
            report,
            source_identities=(SourceIdentityV1("HARNESS", "v1", "a" * 40, "2026-09-24T00:00:00+00:00"),),
            now=datetime(2026, 9, 24, 0, 0, 5, tzinfo=timezone.utc),
            operational_acceptance=acceptance,
        ).to_dict()
        self.assertEqual(model["normalized_state"], "COMPLETED")
        self.assertEqual(model["operational_acceptance"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

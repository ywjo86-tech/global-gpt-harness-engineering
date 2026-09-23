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
)


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


if __name__ == "__main__":
    unittest.main()

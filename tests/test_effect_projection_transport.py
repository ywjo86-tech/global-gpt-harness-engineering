from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.codex_dynamic_transport import ToolRequestEnvelope
from runtime.orchestrator.effect_evidence_bridge import (
    collect_governed_write_effect_evidence,
)
from runtime.orchestrator.production_tool_transport import ProductionToolTransport
from runtime.orchestrator.tool_authorization import (
    activate_contract,
    build_dec007_approved_contracts,
)

PACKAGE = "a" * 64
PLAN = "b" * 64


def active_contracts():
    approved = build_dec007_approved_contracts(
        project_id="PROJECT_1",
        gate_id="GATE_1",
        lv_id="LV_1",
        run_id="RUN_1",
        canonical_plan_sha256=PLAN,
        owned_files=("owned.txt",),
    )
    return tuple(
        activate_contract(
            item,
            package_binding_sha256=PACKAGE,
            authorized_decisions={"DEC-007": "USER_DECISION"},
        )
        for item in approved
    )


def request():
    return {
        "project_id": "PROJECT_1",
        "run_id": "RUN_1",
        "gate_id": "GATE_1",
        "lv_id": "LV_1",
        "canonical_plan_sha256": PLAN,
        "owned_files": ["owned.txt"],
        "active_tool_authorization_contracts": [
            item.to_dict() for item in active_contracts()
        ],
    }


class EffectProjectionTransportTests(unittest.TestCase):
    def test_transport_exposes_bounded_write_evidence_without_raw_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = ProductionToolTransport(
                request=request(),
                workspace_root=root,
                journal_root=root / "journal",
                security_scan=lambda _: True,
            )
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "private-change"},
                    "CALL_WRITE",
                )
            )
            projected = transport.governed_effect_evidence()
            self.assertEqual(len(projected), 1)
            self.assertEqual(projected[0].scope_ref, "owned.txt")
            self.assertTrue(projected[0].mutation_performed)
            self.assertNotIn(
                "private-change",
                json.dumps(projected[0].canonical_projection(), sort_keys=True),
            )

    def test_shared_journal_ignores_unrelated_run_legacy_write_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / "journal"
            journal.mkdir()
            legacy = {
                "schema_version": "orchestration.tool-effect-intent.v1",
                "effect_id": "TE-LEGACY-OTHER-RUN",
                "identity": {
                    "operation_class_id": "PROJECT_OWNED_FILE_WRITE",
                    "worker_task_id": "TASK-4A-08",
                    "project_id": "PROJECT_1",
                    "gate_id": "GATE_1",
                    "lv_id": "LV_1",
                    "run_id": "RUN_OLD",
                },
                "authorization_status": "AUTHORIZED",
            }
            (journal / "TE-LEGACY-OTHER-RUN.intent.json").write_text(
                json.dumps(legacy, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            write = next(
                item for item in active_contracts()
                if item.operation_class_id == "PROJECT_OWNED_FILE_WRITE"
            )
            evidence = collect_governed_write_effect_evidence(
                journal,
                active_write_contract=write,
                expected_owned_scope=("owned.txt",),
            )
            self.assertEqual(evidence, ())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.operator_control import (
    CONTINUATION_SCHEMA, OPERATOR_DIRECTIVE_SCHEMA,
    ContinuationState, OperatorContinuationStore, OperatorControlError, OperatorDirectiveV1,
)


def _payload(**changes):
    payload = {
        "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
        "project_id": "P1", "run_id": "R1", "task_id": "T1", "task_execution_id": "E1",
        "current_stage": "ENTRY", "requested_next_stage": "PREPARE",
        "required_capabilities": ["reasoning", "read_only"], "state_change_required": False,
        "input_artifact_digests": [], "gate_id": "GATE-001", "directive_id": "D1",
    }
    payload.update(changes)
    return payload


class OperatorControlTest(unittest.TestCase):
    def test_provider_and_model_fields_are_rejected(self) -> None:
        for field in ("provider", "model", "provider_ref", "model_ref"):
            with self.subTest(field=field):
                with self.assertRaises(OperatorControlError):
                    OperatorDirectiveV1.from_mapping({**_payload(), field: "forbidden"})

    def test_action_requires_prepared_artifact_lineage(self) -> None:
        with self.assertRaises(OperatorControlError):
            OperatorDirectiveV1.from_mapping(_payload(
                current_stage="PREPARE", requested_next_stage="ACTION",
                state_change_required=True, input_artifact_digests=[],
            ))
        directive = OperatorDirectiveV1.from_mapping(_payload(
            current_stage="PREPARE", requested_next_stage="ACTION",
            state_change_required=True, input_artifact_digests=["a" * 64],
        ))
        self.assertEqual(directive.requested_next_stage, "ACTION")
        self.assertEqual(len(directive.directive_digest), 64)

    def test_state_changing_prepare_cannot_skip_action(self) -> None:
        with self.assertRaises(OperatorControlError):
            OperatorDirectiveV1.from_mapping(_payload(
                current_stage="PREPARE", requested_next_stage="VERIFY",
                state_change_required=True, input_artifact_digests=["a" * 64],
            ))

    def test_continuation_checkpoint_survives_process_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = ContinuationState(
                schema_version=CONTINUATION_SCHEMA, project_id="P1", run_id="R1", task_id="T1",
                task_execution_id="E1", gate_id="GATE-001", current_stage="ACTION",
                execution_state="ACTION_PROVIDER_BLOCKED", next_action="GPT_OPERATOR_REVIEW_REQUIRED",
                last_directive_digest="a" * 64,
            )
            OperatorContinuationStore(root).save(state)
            loaded = OperatorContinuationStore(root).load("R1", "T1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.execution_state, "ACTION_PROVIDER_BLOCKED")
            self.assertEqual(loaded.next_action, "GPT_OPERATOR_REVIEW_REQUIRED")
            self.assertTrue((root / "runtime" / "operator_control" / "R1" / "T1.json").is_file())


if __name__ == "__main__":
    unittest.main()

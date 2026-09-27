from __future__ import annotations

import dataclasses
import unittest

from runtime.orchestrator.operational_capability import (
    OperationalCapabilityResult,
    RuntimeSelection,
)


class CapabilityLifecycleLineageTests(unittest.TestCase):

    def _base_kwargs(self) -> dict[str, object]:
        return {
            "asset_id": "installed-skill:sha256:" + "a" * 64,
            "skill_id": "ui-design",
            "installed_target": ".agents/skills/ui-design",
            "artifact_digest": "b" * 64,
            "attestation_evidence_reference": "sha256:" + "c" * 64,
            "use_authorization_evidence_reference": "sha256:" + "d" * 64,
            "capability_requirement": "ui_design",
            "project_id": "P1",
            "gate_id": "G1",
            "lv_id": "LV1",
            "canonical_plan_sha256": "e" * 64,
            "source": "project-installed",
        }

    def _lineage_selection(self) -> RuntimeSelection:
        return RuntimeSelection(
            **self._base_kwargs(),
            capability_contract_id="cap:ui-design:1",
            capability_contract_version="1.0.0",
            endpoint_version="rev-001",
            activation_epoch=1,
        )

    def test_runtime_selection_can_carry_contract_lineage_without_assignment_authority(self):
        selection = self._lineage_selection()
        payload = dataclasses.asdict(selection)

        self.assertEqual(
            payload["capability_contract_id"],
            "cap:ui-design:1",
        )
        self.assertEqual(
            payload["capability_contract_version"],
            "1.0.0",
        )
        self.assertEqual(
            payload["endpoint_version"],
            "rev-001",
        )
        self.assertEqual(
            payload["activation_epoch"],
            1,
        )

        self.assertNotIn("final_assignee", payload)
        self.assertNotIn("provider_ref", payload)
        self.assertNotIn("model_ref", payload)

    def test_runtime_selection_legacy_construction_defaults_lineage_to_empty(self):
        selection = RuntimeSelection(**self._base_kwargs())
        payload = dataclasses.asdict(selection)

        self.assertEqual(payload["capability_contract_id"], "")
        self.assertEqual(payload["capability_contract_version"], "")
        self.assertEqual(payload["endpoint_version"], "")
        self.assertEqual(payload["activation_epoch"], 0)

    def test_ledger_projection_emits_lineage_only_for_bound_contract(self):
        result = OperationalCapabilityResult(
            status="READY_FOR_WORKER",
            route="EXISTING",
            worker_prerequisites_satisfied=True,
            runtime_selection=self._lineage_selection(),
            stage_records={},
        )

        projection = result.ledger_projection()

        self.assertEqual(
            projection["capability_contract_lineage"],
            {
                "capability_contract_id": "cap:ui-design:1",
                "capability_contract_version": "1.0.0",
                "endpoint_version": "rev-001",
                "activation_epoch": 1,
            },
        )

        self.assertNotIn(
            "final_assignee",
            projection["capability_contract_lineage"],
        )
        self.assertNotIn(
            "provider_ref",
            projection["capability_contract_lineage"],
        )
        self.assertNotIn(
            "model_ref",
            projection["capability_contract_lineage"],
        )

    def test_legacy_ledger_projection_emits_no_lineage(self):
        result = OperationalCapabilityResult(
            status="READY_FOR_WORKER",
            route="EXISTING",
            worker_prerequisites_satisfied=True,
            runtime_selection=RuntimeSelection(**self._base_kwargs()),
            stage_records={},
        )

        projection = result.ledger_projection()

        self.assertNotIn(
            "capability_contract_lineage",
            projection,
        )


if __name__ == "__main__":
    unittest.main()

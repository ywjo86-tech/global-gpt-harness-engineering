from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.approval_gate import DANGEROUS
from runtime.orchestrator.capability_inventory import (
    CapabilityInventoryError,
    inventory_capabilities,
    run_lazy_discovery,
)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.project_isolation import AssetManifest
from runtime.orchestrator.schemas import CapabilityRequirement, DiscoveryStatus
from runtime.orchestrator.skill_discovery import (
    DISCOVERY_INTENT,
    LEGACY_HTTP_TRANSPORT,
    DiscoveryApproval,
    DiscoveryRequest,
    HTTPDiscoveryResponse,
)


class CapabilityInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project-one"
        self.root.mkdir()
        self.plan_sha = "a" * 64
        self.gate_lvs = {"GATE-1": ["LV-1"]}
        self.requirement = CapabilityRequirement(
            "python-testing", "GATE-1", "LV-1", ("execute",), ("app/model.py",),
        )
        self.calls: list[dict[str, object]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def manifest(asset_id: str, scope: str = "project") -> AssetManifest:
        return AssetManifest(asset_id, scope, frozenset({"python-testing"}),
                             frozenset({"execute"}), ("app/",))

    def approval(self, approved: bool = True, transport=LEGACY_HTTP_TRANSPORT) -> DiscoveryApproval:
        payload = {
            "schema_version": "orchestration.skill-discovery.approval.v1",
            "intent": DISCOVERY_INTENT, "classification": DANGEROUS, "status": "ACTIVE",
            "project_id": "project-one", "gate_id": "GATE-1", "lv_id": "LV-1",
            "canonical_plan_sha256": self.plan_sha,
            "discovery_contract_sha256": transport.contract_sha256,
        }
        envelope = {"payload": payload, "record_hash": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
        path = self.root / "approval.json"
        path.write_bytes(canonical_json_bytes(envelope))
        return DiscoveryApproval(
            DISCOVERY_INTENT, DANGEROUS, approved, "project-one", "GATE-1", "LV-1",
            "approval.json", hashlib.sha256(path.read_bytes()).hexdigest(), self.plan_sha,
            transport.contract_sha256,
        )

    def request(self, *, approved: bool = True, transport=LEGACY_HTTP_TRANSPORT) -> DiscoveryRequest:
        return DiscoveryRequest(
            "python testing", self.requirement, str(self.root), "project-one", "GATE-1", "LV-1",
            self.approval(approved, transport), 5, None, "2026-09-01T00:00:00Z", self.plan_sha,
            transport,
        )

    def executor(self, **kwargs: object) -> HTTPDiscoveryResponse:
        self.calls.append(dict(kwargs))
        body = {
            "query": "python testing", "searchType": "semantic", "searchVersion": "mutable",
            "skills": [{"id": "owner/repo/skill", "name": "skill", "skillId": "skill",
                        "installs": 1, "source": "owner/repo"}],
            "count": 1, "duration_ms": 1,
        }
        return HTTPDiscoveryResponse(200, "application/json", json.dumps(body).encode())

    def inventory(self, **kwargs: object):
        values = dict(
            project_id="project-one", canonical_plan_sha256=self.plan_sha,
            gate_lvs=self.gate_lvs, requirements=(self.requirement,),
        )
        values.update(kwargs)
        return inventory_capabilities(**values)

    def lazy(self, request: DiscoveryRequest | None = None, **kwargs: object):
        values = dict(
            request=request or self.request(), project_id="project-one",
            canonical_plan_sha256=self.plan_sha, gate_lvs=self.gate_lvs,
            authorized_permissions=("execute",), authorized_owned_files=("app/model.py",),
            http_executor=self.executor,
        )
        values.update(kwargs)
        return run_lazy_discovery(**values)

    def test_gate0_inventory_never_has_network_execution(self) -> None:
        result = self.inventory()
        self.assertFalse(result.evidence["network_attempted"])
        self.assertEqual(self.calls, [])

    def test_gate0_project_existing_precedes_global_and_agent(self) -> None:
        result = self.inventory(
            project_assets=(self.manifest("project-skill"),),
            global_assets=(self.manifest("global-skill", "global"),),
            agent_registry={"python-testing": object()},
        )
        self.assertEqual(next(iter(result.existing_assets.values())), "project-skill")
        self.assertFalse(result.discovery_required)

    def test_gate0_forecasts_verified_gap_without_authorizing_execution(self) -> None:
        result = self.inventory()
        self.assertTrue(result.discovery_required)
        self.assertFalse(result.evidence["execution_authorized"])
        self.assertFalse(result.authoritative)

    def test_gate_time_existing_never_calls_discovery_executor(self) -> None:
        result = self.lazy(project_assets=(self.manifest("project-skill"),), prior_used_assets=("prior",))
        self.assertEqual(result.decision, "EXISTING")
        self.assertEqual(result.used_assets, ("prior",))
        self.assertEqual(self.calls, [])

    def test_gap_without_dangerous_approval_blocks_before_executor(self) -> None:
        result = self.lazy(self.request(approved=False))
        self.assertEqual(result.decision, "BLOCKED")
        self.assertFalse(result.discovery.execution_attempted)  # type: ignore[union-attr]
        self.assertEqual(self.calls, [])

    def test_approved_gap_runs_fake_http_and_records_raw_candidate_only(self) -> None:
        result = self.lazy(prior_used_assets=("existing-used",))
        projection = result.ledger_projection()
        self.assertEqual(result.decision, "PENDING_EVALUATION")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(projection["discovered_candidates"], ["owner/repo/skill"])
        self.assertEqual(projection["evaluated_candidates"], [])
        self.assertEqual(projection["selected_candidate"], "")
        self.assertFalse(projection["candidate_use_authorized"])
        self.assertEqual(projection["used_assets"], ["existing-used"])
        self.assertNotIn("selection_rationale", projection)

    def test_success_does_not_promote_gate_or_capability(self) -> None:
        result = self.lazy()
        self.assertNotEqual(result.decision, "PASS")
        self.assertTrue(result.inventory.discovery_required)
        self.assertTrue(result.gate_state_preserved)

    def test_discovery_failure_preserves_prior_selection_and_gate_state(self) -> None:
        def failed(**kwargs: object) -> HTTPDiscoveryResponse:
            self.calls.append(dict(kwargs))
            raise RuntimeError("fixture failure")
        result = self.lazy(http_executor=failed, prior_used_assets=("prior",))
        self.assertEqual(result.decision, "BLOCKED")
        self.assertEqual(result.used_assets, ("prior",))
        self.assertTrue(result.gate_state_preserved)
        self.assertEqual(result.ledger_projection()["used_assets"], ["prior"])

    def test_contract_drift_fails_closed_without_fallback(self) -> None:
        drifted = replace(LEGACY_HTTP_TRANSPORT, enabled=False)
        result = self.lazy(self.request(transport=drifted))
        self.assertEqual(result.decision, "BLOCKED")
        self.assertEqual(self.calls, [])

    def test_mutable_upstream_provenance_is_preserved(self) -> None:
        result = self.lazy()
        transport = result.discovery.evidence["transport_resolution"]  # type: ignore[union-attr]
        self.assertEqual(transport["provenance_status"], "MUTABLE_UPSTREAM")

    def test_gate0_gap_is_stale_when_gate_time_project_asset_exists(self) -> None:
        self.assertTrue(self.inventory().discovery_required)
        current = self.lazy(project_assets=(self.manifest("arrived"),))
        self.assertEqual(current.decision, "EXISTING")
        self.assertEqual(self.calls, [])

    def test_gate0_existing_is_stale_when_asset_removed(self) -> None:
        self.assertFalse(self.inventory(project_assets=(self.manifest("removed"),)).discovery_required)
        current = self.lazy()
        self.assertEqual(current.decision, "PENDING_EVALUATION")
        self.assertEqual(len(self.calls), 1)

    def test_permission_and_owned_file_mismatch_block_before_discovery(self) -> None:
        for values in ({"authorized_permissions": ()}, {"authorized_owned_files": ()}):
            with self.subTest(values=values), self.assertRaises(CapabilityInventoryError):
                self.lazy(**values)
        self.assertEqual(self.calls, [])

    def test_full_plan_inventory_rejects_missing_lv_requirement(self) -> None:
        with self.assertRaises(CapabilityInventoryError):
            self.inventory(gate_lvs={"GATE-1": ["LV-1", "LV-2"]})

    def test_full_plan_approval_does_not_replace_discovery_approval(self) -> None:
        result = self.lazy(self.request(approved=False))
        self.assertEqual(result.discovery.status, DiscoveryStatus.BLOCKED)  # type: ignore[union-attr]
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

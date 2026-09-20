from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.provider_candidate_inventory import load_canonical_candidate_inventory
from runtime.orchestrator.provider_runtime_binding import collect_production_provider_eligibility
from runtime.orchestrator.production_worker_executor import _production_provider_runner_registry_for_root
from runtime.orchestrator.provider_router import ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1


def write_active_inventory(root: Path) -> Path:
    path = root / "docs/harness/provider-candidate-inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "gch.provider-candidate-inventory.v1",
        "records": [{
            "schema_version": "gch.provider-candidate.v1",
            "provider_id": "groq",
            "protocol_class": "omniroute-openai-v1",
            "state": "ACTIVE",
            "model_refs": ["openai/gpt-oss-120b"],
            "credential_required": True,
            "cost_class": "free",
            "capability_refs": ["reasoning", "read_only", "patch_generation", "implementation_generation", "test_design", "integration"],
            "readiness_evidence_refs": ["groq-live-read-pass"],
            "action_evidence_ref": "groq-action-no-effect-pass",
            "reroute_evidence_ref": "groq-router-reroute-pass",
            "activation_approval_ref": "USER-GROQ-FREE-API-KEY-20260920",
            "cost_risk_approval_ref": "",
            "connection_id": "conn-groq",
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ProviderCandidateRuntimeIntegrationTests(unittest.TestCase):
    def test_canonical_active_inventory_is_loaded_and_projected_without_callsite_argument(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_active_inventory(root)
            inv = load_canonical_candidate_inventory(root)
            self.assertEqual(inv.records[0].provider_id, "groq")
            base = ProviderEligibilitySnapshotV1(
                ELIGIBILITY_SCHEMA_V1, "base", {"nvidia": True}, {"nvidia": "nvidia/model"},
                ("base-evidence",), provider_capabilities={"nvidia": ("reasoning", "read_only")},
            )
            with patch("runtime.orchestrator.provider_runtime_binding.runtime_policy.collect_static_provider_eligibility", return_value=base):
                snapshot = collect_production_provider_eligibility(root, "run-1")
            self.assertTrue(snapshot.provider_eligible["groq"])
            self.assertEqual(snapshot.model_refs["groq"], "openai/gpt-oss-120b")

    def test_worker_default_registry_loads_same_active_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_active_inventory(root)
            registry = _production_provider_runner_registry_for_root(root)
            self.assertIsNotNone(registry.resolve_read("groq"))
            self.assertIsNotNone(registry.resolve_action("groq"))
            self.assertIsNotNone(registry.resolve_read("nvidia"))

    def test_malformed_or_symlink_inventory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "docs/harness/provider-candidate-inventory.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(Exception):
                load_canonical_candidate_inventory(root)
            path.unlink()
            target = root / "inventory.json"
            target.write_text(json.dumps({"schema_version":"gch.provider-candidate-inventory.v1","records":[]}), encoding="utf-8")
            path.symlink_to(target)
            with self.assertRaises(Exception):
                load_canonical_candidate_inventory(root)


if __name__ == "__main__":
    unittest.main()

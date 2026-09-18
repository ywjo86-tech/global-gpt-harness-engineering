from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_runner import _failure_class
from runtime.orchestrator.provider_router import (
    GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2, RouterRequestV2, route_request,
)
from runtime.orchestrator.provider_runtime_binding import (
    ProviderRuntimeBindingError, collect_production_provider_eligibility,
)


class ProductionMPRFBindingTests(unittest.TestCase):
    def _activate_mprf(self, root: Path, *, valid: bool = True) -> Path:
        path = root / "docs/history/upgrades/PREPH5MPRF/TASK-016/MULTI_PROVIDER_FOUNDATION_BASELINE_FINAL_APPROVAL_20260918.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "gch.multi-provider-foundation.baseline-final-approval.v1",
            "baseline_id": "MULTI_PROVIDER_FOUNDATION_BASELINE",
            "final_record_status": "APPROVED_SEALED" if valid else "DRAFT",
            "normalized_decision": "FINAL_APPROVED",
            "gate010_independent_review": "PASS",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _provider_config(self, root: Path, *, secret_mode: int = 0o600, secret_exists: bool = True) -> Path:
        secret = root / "nvidia.env"
        if secret_exists:
            secret.write_text("export NVIDIA_API_KEY=fixture-secret\nexport NVIDIA_MODEL=legacy-fixture\n", encoding="utf-8")
            secret.chmod(secret_mode)
        pool = root / "nvidia-model-pool.json"
        pool.write_text(json.dumps({
            "schema_version": "gch.nvidia.model-pool.v1",
            "default_role": "primary_heavy",
            "models": {"primary_heavy": {
                "model": "nvidia/fixture-primary", "status": "ACTIVE",
                "fallback_models": ["nvidia/fixture-fallback"],
                "capabilities": ["reasoning", "read_only"],
            }},
            "policy": {
                "automatic_provider_fallback": False, "state_changing_execution": False,
                "automatic_model_failover": True, "secret_source": str(secret),
            },
        }), encoding="utf-8")
        pool.chmod(0o600)
        return pool

    def _collect(self, root: Path, pool: Path):
        env = {"GCH_NVIDIA_MODEL_POOL": str(pool)}
        with patch.dict(os.environ, env, clear=True):
            snapshot = collect_production_provider_eligibility(
                root, "binding-run", required_capabilities=("reasoning", "read_only", "review"),
                codex_ready_override=False, extra_evidence_refs=("test-binding",),
            )
            loaded = bool(os.environ.get("NVIDIA_API_KEY"))
        return snapshot, loaded

    def test_post_mprf_uses_mprf_snapshot_and_secret_source_without_leak(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._activate_mprf(root); pool = self._provider_config(root)
            snapshot, loaded = self._collect(root, pool)
            self.assertTrue(loaded)
            self.assertTrue(snapshot.snapshot_id.startswith("mprf-"))
            self.assertTrue(snapshot.provider_eligible["nvidia"])
            self.assertFalse(snapshot.provider_eligible["codex"])
            self.assertEqual(snapshot.model_refs["nvidia"], "nvidia/fixture-primary")
            self.assertEqual((snapshot.model_fallback_refs or {})["nvidia"], ("nvidia/fixture-fallback",))
            self.assertIn("provider-runtime-source:mprf", snapshot.evidence_refs)
            self.assertNotIn("pre-mprf-static-policy", snapshot.evidence_refs)
            self.assertNotIn("fixture-secret", json.dumps(snapshot.to_dict()))

    def test_post_mprf_missing_secret_fails_closed_without_static_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._activate_mprf(root); pool = self._provider_config(root, secret_exists=False)
            with patch.dict(os.environ, {"GCH_NVIDIA_MODEL_POOL": str(pool)}, clear=True):
                with self.assertRaisesRegex(ProviderRuntimeBindingError, "secret source"):
                    collect_production_provider_eligibility(root, "missing-secret", codex_ready_override=False)

    def test_post_mprf_invalid_approval_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._activate_mprf(root, valid=False); pool = self._provider_config(root)
            with patch.dict(os.environ, {"GCH_NVIDIA_MODEL_POOL": str(pool)}, clear=True):
                with self.assertRaisesRegex(ProviderRuntimeBindingError, "approval"):
                    collect_production_provider_eligibility(root, "bad-approval", codex_ready_override=False)

    def test_post_mprf_rejects_overbroad_secret_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._activate_mprf(root); pool = self._provider_config(root, secret_mode=0o644)
            with patch.dict(os.environ, {"GCH_NVIDIA_MODEL_POOL": str(pool)}, clear=True):
                with self.assertRaisesRegex(ProviderRuntimeBindingError, "permissions"):
                    collect_production_provider_eligibility(root, "bad-secret-mode", codex_ready_override=False)

    def test_pre_mprf_preserves_static_compatibility_and_does_not_autoload_secret(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pool = self._provider_config(root)
            snapshot, loaded = self._collect(root, pool)
            self.assertFalse(loaded)
            self.assertTrue(snapshot.snapshot_id.startswith("pre-mprf-"))
            self.assertFalse(snapshot.provider_eligible["nvidia"])
            self.assertIn("pre-mprf-static-policy", snapshot.evidence_refs)

    def test_mprf_snapshot_flows_into_router_without_mprf_selection_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._activate_mprf(root); pool = self._provider_config(root)
            snapshot, _ = self._collect(root, pool)
            request = RouterRequestV2(
                ROUTER_REQUEST_SCHEMA_V2, "REQ-READ", "P1", "R1", "T1", "E1", "d"*64,
                "REVIEW", ("reasoning", "read_only", "review"), False, GOVERNED_POLICY_V1, snapshot,
            )
            decision = route_request(request)
            self.assertTrue(decision.eligible)
            self.assertEqual(decision.provider_ref, "nvidia")
            self.assertEqual(decision.model_ref, "nvidia/fixture-primary")
            action = RouterRequestV2(
                ROUTER_REQUEST_SCHEMA_V2, "REQ-ACTION", "P1", "R1", "T1", "E2", "e"*64,
                "ACTION", ("filesystem_write",), True, GOVERNED_POLICY_V1, snapshot,
            )
            blocked = route_request(action)
            self.assertFalse(blocked.eligible)
            self.assertEqual(blocked.reason_code, "action_provider_unavailable")
            self.assertEqual(blocked.provider_ref, "")

    def test_production_full_plan_source_uses_mprf_binding_not_static_collector(self):
        source = (Path(__file__).resolve().parents[1] / "runtime/orchestrator/gate_orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("collect_production_provider_eligibility", source)
        self.assertNotIn("collect_static_provider_eligibility", source)

    def test_provider_route_blocked_is_provider_failure_for_durable_wait(self):
        self.assertEqual(_failure_class("PROVIDER_ROUTE_BLOCKED:read_provider_unavailable"), "PROVIDER_FAILURE")
        self.assertEqual(_failure_class("PROVIDER_ROUTE_BLOCKED:action_provider_unavailable"), "PROVIDER_FAILURE")


if __name__ == "__main__":
    unittest.main()

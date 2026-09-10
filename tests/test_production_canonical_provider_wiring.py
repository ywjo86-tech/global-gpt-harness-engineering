from __future__ import annotations
import inspect
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.gate_orchestrator import execute_gate
from runtime.orchestrator.production_canonical_authority import (
    ProductionCanonicalAuthorityError,
    _canonical_materialization_created_at,
    build_production_canonical_worker_authority_provider,
    production_canonical_package_identity,
)

class ProductionCanonicalProviderWiringTests(unittest.TestCase):
    def test_execute_gate_exposes_injected_readiness_inputs(self):
        sig = inspect.signature(execute_gate)
        self.assertIn("codex_auth_readiness", sig.parameters)
        self.assertIn("codex_readiness_recheck_probes", sig.parameters)
        self.assertIsNone(sig.parameters["codex_auth_readiness"].default)
        self.assertIsNone(sig.parameters["codex_readiness_recheck_probes"].default)

    def test_package_identity_is_deterministic(self):
        kwargs = dict(
            project_id="wallet-affiliate-collector",
            gate_id="G1",
            lv_id="LV3-5",
            run_id="run-provider",
        )
        first = production_canonical_package_identity(**kwargs)
        second = production_canonical_package_identity(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first[1], 1)
        self.assertTrue(first[0].startswith("PKG-"))

    def test_materialization_timestamp_is_create_once_across_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _canonical_materialization_created_at(
                root,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                preferred_created_at_utc="2026-09-10T08:00:00Z",
            )
            second = _canonical_materialization_created_at(
                root,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                preferred_created_at_utc="2026-09-10T09:00:00Z",
            )
            self.assertEqual(first, "2026-09-10T08:00:00Z")
            self.assertEqual(second, first)

    def test_provider_missing_readiness_fails_before_any_probe(self):
        provider = build_production_canonical_worker_authority_provider(
            codex_auth_readiness=None,
            readiness_recheck_probes=None,
            verify_git_provenance=False,
        )
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            provider(
                mode="normal",
                project_root=Path("/tmp/project"),
                harness_root=Path("/tmp/harness"),
                package_root=Path("/tmp/package"),
                parent_package_root=Path("/tmp/package"),
                manifest={},
                recovery_package=None,
                recovery_preflight=None,
                requirements_sha256="1" * 64,
                project_id="wallet-affiliate-collector",
                gate_id="G1",
                lv_id="LV3-5",
                run_id="run-provider",
                canonical_plan_sha256="2" * 64,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_READINESS_REQUIRED",
        )

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from runtime.orchestrator.gate_controller import GateControllerError
from runtime.orchestrator.gate_orchestrator import (
    GateLV,
    GatePlan,
    _canonical_worker_authority_extra,
)

REQ = "1" * 64
PLAN = "2" * 64
PROJECTION_SHA = "3" * 64
AUTH_SHA = "4" * 64


def plan() -> GatePlan:
    return GatePlan(
        project_id="wallet-affiliate-collector",
        project_root="/tmp/project",
        gate_id="G1",
        canonical_plan_path="plan.md",
        canonical_plan_sha256=PLAN,
        lvs=[
            GateLV(
                gate_id="G1",
                lv_id="LV3-5",
                order=1,
                purpose="deduplicator",
                dependencies=[],
                owned_files=["app/services/deduplicator.py"],
                completion_criteria=["stable"],
                execution="implementation",
                tests=["tests/test_deduplicator.py"],
            )
        ],
    )


def exact_projection():
    return {
        "active_tool_authorization_contracts": [{"contract_id": "TAC-1"}],
        "owned_files": ["app/services/deduplicator.py"],
        "requirement_digest": REQ,
        "tool_authorization_projection": {"worker_task_id": "TASK-4A-08"},
        "tool_authorization_projection_sha256": PROJECTION_SHA,
        "canonical_authority_binding": {"worker_task_id": "TASK-4A-08"},
        "canonical_authority_binding_digest": AUTH_SHA,
    }


class GateCanonicalWorkerInjectionTests(unittest.TestCase):
    def kwargs(self):
        return dict(
            mode="normal",
            project_root=Path("/tmp/project"),
            harness_root=Path("/tmp/harness"),
            package_root=Path("/tmp/package"),
            parent_package_root=Path("/tmp/package"),
            manifest={"lv_id": "LV3-5"},
            recovery_package=None,
            recovery_preflight=None,
            context={"requirements_sha256": REQ},
            plan=plan(),
            lv_id="LV3-5",
            run_id="run-1",
        )

    def test_missing_provider_does_not_fabricate_authority(self):
        self.assertEqual(_canonical_worker_authority_extra(None, **self.kwargs()), {})

    def test_exact_projection_is_accepted(self):
        seen = {}
        def provider(**kwargs):
            seen.update(kwargs)
            return exact_projection()
        value = _canonical_worker_authority_extra(provider, **self.kwargs())
        self.assertEqual(value["requirement_digest"], REQ)
        self.assertEqual(seen["canonical_plan_sha256"], PLAN)
        self.assertEqual(seen["mode"], "normal")

    def test_partial_projection_fails_closed(self):
        def provider(**kwargs):
            value = exact_projection()
            value.pop("canonical_authority_binding_digest")
            return value
        with self.assertRaises(GateControllerError):
            _canonical_worker_authority_extra(provider, **self.kwargs())

    def test_unknown_projection_field_fails_closed(self):
        def provider(**kwargs):
            value = exact_projection()
            value["run_id"] = "override"
            return value
        with self.assertRaises(GateControllerError):
            _canonical_worker_authority_extra(provider, **self.kwargs())

    def test_task_binding_mismatch_fails_closed(self):
        def provider(**kwargs):
            value = exact_projection()
            value["canonical_authority_binding"] = {"worker_task_id": "TASK-OTHER"}
            return value
        with self.assertRaises(GateControllerError):
            _canonical_worker_authority_extra(provider, **self.kwargs())

    def test_recovery_lineage_inputs_are_forwarded_separately(self):
        seen = {}
        def provider(**kwargs):
            seen.update(kwargs)
            return exact_projection()
        kwargs = self.kwargs()
        kwargs.update(
            mode="recovery",
            package_root=Path("/tmp/recovery-attempt"),
            parent_package_root=Path("/tmp/original-lv-package"),
            manifest=None,
            recovery_package={"package_sha256": "5" * 64},
            recovery_preflight={"preflight_sha256": "6" * 64},
        )
        _canonical_worker_authority_extra(provider, **kwargs)
        self.assertEqual(seen["mode"], "recovery")
        self.assertEqual(seen["parent_package_root"], Path("/tmp/original-lv-package"))
        self.assertIsNone(seen["manifest"])


if __name__ == "__main__":
    unittest.main()

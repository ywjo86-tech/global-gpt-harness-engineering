from __future__ import annotations

import ast
import unittest
from pathlib import Path

from runtime.ai_office.capability_governance import CAPABILITY_NEED_SCHEMA_V1, CapabilityNeedV1, OWNER_CAPABILITIES, route_capability_need
from runtime.orchestrator.office_execution_backend_adapter import OfficeExecutionBackendAdapter, OfficeExecutionBackendAdapterError
from runtime.orchestrator.office_execution_contract import OFFICE_EXECUTION_REQUEST_SCHEMA_V1, OfficeExecutionRequestV1

D = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
AI_OFFICE_ROOT = ROOT / "runtime" / "ai_office"


def _imports_and_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports, calls, assigned = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name): calls.add(fn.id)
            elif isinstance(fn, ast.Attribute): calls.add(fn.attr)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name): assigned.add(target.id)
                elif isinstance(target, ast.Attribute): assigned.add(target.attr)
    return imports, calls, assigned


def _request(effect="READ_ONLY"):
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "proj", "run", "workflow", "TASK-015", "task-exec",
        "intent", D, effect, "gov", D, "risk", D, "approval", D, "binding", D,
        "package", D, "contract", D, "assignment", D, "GATE-005", "full-plan-run", "TASK-015", "corr",
    )


class AIOfficeAuthorityNegativeSpaceTest(unittest.TestCase):
    def test_028_ai_office_has_no_direct_router_mprf_full_mcp_or_gate_authority(self) -> None:
        forbidden_import_prefixes = ("runtime.full_mcp", "runtime.mprf", "runtime.orchestrator.provider_router")
        forbidden_calls = {"route_request", "execute_gate", "FullMCPBackendAdapter"}
        forbidden_assignments = {"provider", "provider_ref", "model", "model_ref", "selected_provider",
                                 "selected_model", "final_assignee", "gate_decision", "fanin_decision"}
        violations = []
        for path in sorted(AI_OFFICE_ROOT.glob("*.py")):
            imports, calls, assigned = _imports_and_calls(path)
            bad_imports = sorted(item for item in imports if item.startswith(forbidden_import_prefixes))
            bad_calls = sorted(calls & forbidden_calls)
            bad_assignments = sorted(assigned & forbidden_assignments)
            if bad_imports or bad_calls or bad_assignments:
                violations.append((path.name, bad_imports, bad_calls, bad_assignments))
        self.assertEqual(violations, [])

    def test_028_state_change_and_mixed_owner_paths_fail_closed(self) -> None:
        mixed = route_capability_need(CapabilityNeedV1(
            CAPABILITY_NEED_SCHEMA_V1, "need:mixed-negative", ("reasoning", "filesystem_write"),
            "STATE_CHANGING", "purpose:negative", "scope:negative"))
        self.assertEqual((mixed.disposition, mixed.owner_boundary), ("BLOCKED", ""))
        request = _request("READ_ONLY")
        def handler(_payload):
            return {"office_request_digest":request.request_digest, "project_id":"proj", "project_run_id":"run",
                    "workflow_item_id":"workflow", "task_execution_id":"task-exec", "correlation_id":"corr",
                    "status":"COMPLETED", "result_digest":D, "effect_ref":"forbidden-effect", "audit_ref":"audit",
                    "reconciliation_state":"NOT_REQUIRED", "error_code":""}
        with self.assertRaises(OfficeExecutionBackendAdapterError):
            OfficeExecutionBackendAdapter(handler).execute(request)

    def test_028_phase7_provider_lifecycle_capabilities_remain_outside_ai_office(self) -> None:
        ai_office_caps = set(OWNER_CAPABILITIES["AI_OFFICE"])
        reserved = {"provider_failover", "provider_registry_mutation", "provider_model_selection",
                    "automatic_reroute", "provider_lifecycle"}
        self.assertFalse(ai_office_caps & reserved)
        onboarding = (AI_OFFICE_ROOT / "agent_onboarding.py").read_text(encoding="utf-8")
        self.assertNotIn("runtime.orchestrator.provider_router", onboarding)
        self.assertNotIn("runtime.mprf", onboarding)
        self.assertNotIn("provider registry", onboarding.lower())


if __name__ == "__main__":
    unittest.main()

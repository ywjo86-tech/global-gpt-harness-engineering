from __future__ import annotations

import ast
import unittest
from pathlib import Path


TARGETS = {
    "dcc": Path("runtime/orchestrator/durable_continuation.py"),
    "wait_recovery": Path("runtime/orchestrator/wait_recovery.py"),
    "attention_delivery": Path("runtime/orchestrator/attention_delivery.py"),
    "attention_outbox": Path("runtime/orchestrator/production_attention.py"),
    "operator_checkpoint": Path("runtime/orchestrator/operator_turn_checkpoint.py"),
}

# Provider routing may be *observed* by wait_recovery to prove that a previous
# WAITING_PROVIDER condition cleared. It may not execute a provider request.
COMMON_FORBIDDEN_IMPORTS = {
    "production_tool_transport",
    "tool_authorization",
    "runtime_release",
    "production_full_plan_entry",
    "gate_orchestrator",
    "completion_authority",
    "production_approval",
}
COMMON_FORBIDDEN_CALLS = {
    "execute_with_private_result",
    "execute_request",
    "dispatch_request",
    "activate_runtime_release",
    "create_user_approval",
    "create_approval",
    "register_job",
    "run_production_full_plan",
    "resume_operator_plan_after_receipt",
    "bind_manual_action_and_resume",
    "_queue_item",
}


def imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
    return names


def called_names(source: str) -> set[str]:
    tree = ast.parse(source)
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    return calls


def authority_violations(source: str, *, allow_router_observation: bool = False) -> set[str]:
    imports = imported_modules(source)
    calls = called_names(source)
    violations = {f"import:{name}" for name in COMMON_FORBIDDEN_IMPORTS & imports}
    violations |= {f"call:{name}" for name in COMMON_FORBIDDEN_CALLS & calls}
    if not allow_router_observation:
        if "provider_router" in imports:
            violations.add("import:provider_router")
        if "route_request" in calls:
            violations.add("call:route_request")
    return violations


class DCCHarnessAuthorityNegativeSpaceTests(unittest.TestCase):
    def test_dcc_has_no_provider_effect_runtime_approval_or_next_gate_authority(self):
        source = TARGETS["dcc"].read_text(encoding="utf-8")
        self.assertEqual(authority_violations(source), set())

    def test_wait_recovery_may_observe_router_but_cannot_execute_or_dispatch(self):
        source = TARGETS["wait_recovery"].read_text(encoding="utf-8")
        self.assertEqual(authority_violations(source, allow_router_observation=True), set())
        self.assertIn("route_request", called_names(source))
        self.assertIn("provider_router", imported_modules(source))

    def test_attention_delivery_and_outbox_have_outbound_evidence_only_authority(self):
        for key in ("attention_delivery", "attention_outbox"):
            with self.subTest(module=key):
                source = TARGETS[key].read_text(encoding="utf-8")
                self.assertEqual(authority_violations(source), set())

    def test_operator_checkpoint_has_no_control_plane_authority(self):
        source = TARGETS["operator_checkpoint"].read_text(encoding="utf-8")
        self.assertEqual(authority_violations(source), set())
        self.assertIn('CONTROL_AUTHORITY = "NONE"', source)

    def test_negative_space_guard_detects_deliberately_forbidden_fixture(self):
        forbidden = """
from runtime.orchestrator.provider_router import route_request
from runtime.orchestrator.runtime_release import activate_runtime_release

def bad():
    route_request({})
    activate_runtime_release('x')
    execute_with_private_result('x')
"""
        violations = authority_violations(forbidden)
        self.assertIn("import:provider_router", violations)
        self.assertIn("import:runtime_release", violations)
        self.assertIn("call:route_request", violations)
        self.assertIn("call:activate_runtime_release", violations)
        self.assertIn("call:execute_with_private_result", violations)


if __name__ == "__main__":
    unittest.main()

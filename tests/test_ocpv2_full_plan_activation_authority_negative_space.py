from __future__ import annotations

import re
import unittest
from dataclasses import fields
from pathlib import Path

from runtime.orchestrator.approved_full_plan_activation_contract import ApprovedFullPlanActivationRequestV1


REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVATION_MODULES = (
    "runtime/orchestrator/approved_full_plan_activation_contract.py",
    "runtime/orchestrator/approved_full_plan_binding.py",
    "runtime/ai_office/full_plan_activation.py",
    "runtime/orchestrator/full_plan_activation.py",
)


def read_sources(*relative_paths: str) -> str:
    return "\n".join((REPO_ROOT / path).read_text(encoding="utf-8") for path in relative_paths)


class OCPv2FullPlanActivationAuthorityNegativeSpaceTests(unittest.TestCase):
    def test_executable_activation_modules_have_no_effect_runtime_imports(self) -> None:
        sources = read_sources(*ACTIVATION_MODULES)
        for forbidden in (
            "FullMCPRuntime",
            "execute_production_worker",
            "dispatch_action_through_production_gateway",
            "provider_router",
            "subprocess.Popen",
            "os.system",
            "systemctl",
            "shell=True",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sources)

    def test_no_new_executor_owner_or_outbox_class_is_created(self) -> None:
        sources = read_sources(*ACTIVATION_MODULES)
        self.assertNotIn("EXECUTION_OWNERS.add", sources)
        self.assertNotIn("class FullPlanActivationOutbox", sources)

    def test_remote_request_contract_carries_no_execution_or_host_authority_fields(self) -> None:
        request_fields = {field.name for field in fields(ApprovedFullPlanActivationRequestV1)}
        forbidden = {
            "provider",
            "model",
            "backend",
            "command",
            "argv",
            "environment",
            "owned_scope",
            "editable_scope",
            "mapping_root",
        }
        self.assertFalse(request_fields & forbidden, request_fields & forbidden)

    def test_gate_and_engine_authority_use_fixed_harness_namespaces(self) -> None:
        source = (REPO_ROOT / "runtime/orchestrator/approved_full_plan_binding.py").read_text(encoding="utf-8")
        compact = re.sub(r"\s+", " ", source)
        self.assertRegex(
            compact,
            r"resolve_harness_authority_file\( harness_state_root=harness_state_root, project_id=str\(mapping\.project_id\), kind=\"approval\", raw=gate_ref\.approval_evidence\.path",
        )
        self.assertRegex(
            compact,
            r"resolve_harness_authority_file\( harness_state_root=harness_state_root, project_id=project_id, kind=\"artifact\", raw=engine_ref\.path",
        )
        self.assertNotRegex(compact, r"resolve_committed_project_file\([^)]*approval_evidence")
        self.assertNotRegex(compact, r"resolve_committed_project_file\([^)]*engine_requirement_evidence")


if __name__ == "__main__":
    unittest.main()

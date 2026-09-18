from __future__ import annotations

import ast
import unittest
from pathlib import Path

from runtime.orchestrator.office_execution_contract import (
    MANUAL_ACTION_HANDOFF_SCHEMA_V1,
    NON_MUTATING_CONTINUATION_SCHEMA_V1,
    OFFICE_EXECUTION_REQUEST_SCHEMA_V1,
    OFFICE_EXECUTION_RESULT_SCHEMA_V1,
    ManualActionHandoffRefV1,
    NonMutatingContinuationRefV1,
    OfficeExecutionContractError,
    OfficeExecutionRequestV1,
    OfficeExecutionResultV1,
)

D = "a" * 64


def request(effect: str = "STATE_CHANGING") -> OfficeExecutionRequestV1:
    return OfficeExecutionRequestV1(
        OFFICE_EXECUTION_REQUEST_SCHEMA_V1, "proj", "run", "workflow", "task", "task-exec",
        "intent-ref", D, effect, "gov-ref", D, "risk-ref", D, "delegated-auth", D,
        "auth-binding", D, "execution-package", D, "execution-contract", D, "corr",
    )


class AIOfficeExecutionContractTest(unittest.TestCase):
    def test_002_request_result_and_handoff_digests_are_canonical(self) -> None:
        req = request()
        self.assertEqual(64, len(req.request_digest))
        result = OfficeExecutionResultV1(
            OFFICE_EXECUTION_RESULT_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
            req.request_digest, "COMPLETED", D, "effect-ref", "audit-ref", "CONFIRMED", "",
        )
        self.assertEqual(req.request_digest, result.request_digest)
        handoff = ManualActionHandoffRefV1(
            MANUAL_ACTION_HANDOFF_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
            "action-package", D, "manual-auth", D, "source-identity", D,
        )
        self.assertEqual(64, len(handoff.handoff_digest))

    def test_002_non_mutating_continuation_requires_read_only_and_dependency_safety(self) -> None:
        continuation = NonMutatingContinuationRefV1(
            NON_MUTATING_CONTINUATION_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
            ("reasoning", "review", "documentation"), "READ_ONLY", True, "dependency-safe", D,
            "full-plan-router-handoff", D,
        )
        self.assertEqual("READ_ONLY", continuation.execution_authority)
        self.assertEqual(64, len(continuation.continuation_digest))
        with self.assertRaises(OfficeExecutionContractError):
            NonMutatingContinuationRefV1(
                NON_MUTATING_CONTINUATION_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
                ("reasoning",), "STATE_CHANGING", True, "dependency-safe", D, "full-plan-router-handoff", D,
            )
        with self.assertRaises(OfficeExecutionContractError):
            NonMutatingContinuationRefV1(
                NON_MUTATING_CONTINUATION_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
                ("reasoning",), "READ_ONLY", False, "dependency-safe", D, "full-plan-router-handoff", D,
            )

    def test_002_internal_or_provider_material_is_rejected(self) -> None:
        values = request().to_dict(); values["operation_intent_ref"] = "runtime.full_mcp.private"
        with self.assertRaises(OfficeExecutionContractError):
            OfficeExecutionRequestV1(**values)
        with self.assertRaises(TypeError):
            OfficeExecutionRequestV1(**{**request().to_dict(), "provider_id": "nvidia"})
        with self.assertRaises(TypeError):
            NonMutatingContinuationRefV1(**{
                **NonMutatingContinuationRefV1(
                    NON_MUTATING_CONTINUATION_SCHEMA_V1, "proj", "run", "workflow", "task-exec", "corr",
                    ("review",), "READ_ONLY", True, "dependency-safe", D, "full-plan-router-handoff", D,
                ).to_dict(),
                "provider_ref": "anything",
            })

    def test_003_public_boundary_has_no_full_mcp_import_or_concrete_backend_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        # TASK-002 validates its own public boundary. Downstream adapter/coordinator
        # negative-space is rechecked at GATE-002 after TASK-003/004 exist.
        paths = [root / "runtime/orchestrator/office_execution_contract.py"]
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
                if isinstance(node, ast.ImportFrom): imports.append(node.module or "")
            self.assertFalse(any(name.startswith("runtime.full_mcp") for name in imports), path)
            concrete_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            self.assertNotIn("FullMCPBackendAdapter", concrete_names, path)


if __name__ == "__main__": unittest.main()

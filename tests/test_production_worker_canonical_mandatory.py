from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from runtime.orchestrator.production_execution_gateway import (
    GatewayError,
    build_gateway_request,
)
from runtime.orchestrator.production_worker_executor import (
    ProductionWorkerError,
    _production_host_execution_gateway,
    _validate_production_gateway_request,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_DECISION_REF,
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "runtime/orchestrator/production_worker_executor.py"

PROJECT = "wallet-affiliate-collector"
RUN = "run-phase3b-r1"
GATE = "G1"
LV = "LV3-5"
PLAN = "d" * 64
RUN_REQUIREMENT = "e" * 64
OWNED = [
    "app/services/deduplicator.py",
    "tests/test_deduplicator.py",
]


def digest(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def canonical_binding() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "orchestration.canonical-launch-authority.v1",
        "package_ref": "execution-package://PKG-PHASE3B@1",
        "package_digest": "1" * 64,
        "contract_ref": "canonical-contract://CEC-TASK-4A-08@1",
        "contract_digest": "2" * 64,
        "contract_activation_digest": "3" * 64,
        "worker_task_id": "TASK-4A-08",
        "criterion_set_digest": "4" * 64,
        "execution_obligation": "MUTATION_REQUIRED",
        "preflight_evidence_digest": "5" * 64,
        "codex_auth_readiness_ref": "CAE-ready",
        "codex_auth_recheck_evidence_ref": "CAE-recheck",
        "launch_authorization_digest": "6" * 64,
        "migration_authority_ref": "migration-authority://R4.1/manifest",
    }
    return value


def tool_authority() -> tuple[list[dict[str, object]], dict[str, object]]:
    approved = build_dec007_approved_contracts(
        project_id=PROJECT,
        gate_id=GATE,
        lv_id=LV,
        run_id=RUN,
        canonical_plan_sha256=PLAN,
        owned_files=OWNED,
    )
    package_binding = "7" * 64
    active = [
        activate_contract(
            item,
            package_binding_sha256=package_binding,
            authorized_decisions={DEC007_DECISION_REF: "USER_DECISION"},
        ).to_dict()
        for item in approved
    ]
    projection: dict[str, object] = {
        "decision_ref": DEC007_DECISION_REF,
        "worker_task_id": "TASK-4A-08",
        "active_contract_count": len(active),
        "contract_ids": sorted(item["contract_id"] for item in active),
        "operation_class_ids": sorted(item["operation_class_id"] for item in active),
        "owned_scope_sha256": owned_scope_digest(OWNED),
        "package_binding_sha256": package_binding,
        "requirement_digests": {
            item["operation_class_id"]: item["requirement_digest"]
            for item in active
        },
    }
    return active, projection


def valid_gateway_request(*, attempt: int = 1) -> dict[str, object]:
    active, projection = tool_authority()
    binding = canonical_binding()
    return build_gateway_request(
        project_id=PROJECT,
        run_id=RUN,
        gate_id=GATE,
        lv_id=LV,
        attempt=attempt,
        workspace_identity={
            "project_id": PROJECT,
            "workspace_kind": "project_root",
        },
        package_manifest_sha256="a" * 64,
        preflight_evidence_sha256="b" * 64,
        runtime_prompt_artifact={
            "kind": "worker_runtime_prompt",
            "name": "executor.prompt.txt",
        },
        runtime_prompt_sha256="c" * 64,
        adapter_contract_version="SEM-025.v2",
        structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
        active_tool_authorization_contracts=active,
        owned_files=OWNED,
        canonical_plan_sha256=PLAN,
        requirement_digest=RUN_REQUIREMENT,
        tool_authorization_projection=projection,
        tool_authorization_projection_sha256=digest(projection),
        canonical_authority_binding=binding,
        canonical_authority_binding_digest=digest(binding),
    )


def reseal_outer_request(value: dict[str, object]) -> dict[str, object]:
    unsigned = dict(value)
    unsigned.pop("request_digest", None)
    value["request_digest"] = digest(unsigned)
    return value


def keyword_true(call: ast.Call, name: str) -> bool:
    return any(
        item.arg == name
        and isinstance(item.value, ast.Constant)
        and item.value.value is True
        for item in call.keywords
    )


class ProductionWorkerCanonicalMandatoryBehaviorTests(unittest.TestCase):
    def test_normal_host_request_accepts_exact_canonical_authority(self):
        value = _validate_production_gateway_request(
            valid_gateway_request(attempt=1),
            configured_backend="HOST_GATEWAY",
        )
        self.assertEqual(
            value["canonical_authority_binding"]["worker_task_id"],
            "TASK-4A-08",
        )

    def test_recovery_attempt_uses_same_fail_closed_boundary(self):
        value = valid_gateway_request(attempt=2)
        value["canonical_authority_binding"] = {}
        value["canonical_authority_binding_digest"] = ""
        reseal_outer_request(value)
        with self.assertRaises(ProductionWorkerError) as caught:
            _validate_production_gateway_request(
                value,
                configured_backend="HOST_GATEWAY",
            )
        self.assertIn("CANONICAL_AUTHORITY_REQUIRED", str(caught.exception))

    def test_missing_tool_authority_is_rejected_by_production_boundary(self):
        value = valid_gateway_request()
        value["tool_authorization_projection"] = {}
        value["tool_authorization_projection_sha256"] = ""
        value["active_tool_authorization_contracts"] = []
        reseal_outer_request(value)
        with self.assertRaises(ProductionWorkerError) as caught:
            _validate_production_gateway_request(
                value,
                configured_backend="HOST_GATEWAY",
            )
        self.assertIn("CANONICAL_TOOL_AUTHORITY_REQUIRED", str(caught.exception))

    def test_production_gateway_factory_blocks_before_transport(self):
        transport = Mock()
        value = valid_gateway_request()
        value["canonical_authority_binding"] = {}
        value["canonical_authority_binding_digest"] = ""
        reseal_outer_request(value)

        gateway = _production_host_execution_gateway(transport)
        with self.assertRaises(GatewayError):
            gateway.execute(
                value,
                prompt=b"bounded prompt",
                last_message=Path("/tmp/phase3b-last-message"),
                timeout=1,
                cancel_path=Path("/tmp/phase3b-cancel"),
            )
        transport.assert_not_called()

    def test_local_test_seam_does_not_invent_canonical_authority(self):
        value = {"execution_backend": "LOCAL_CHILD", "legacy": True}
        self.assertEqual(
            _validate_production_gateway_request(
                value,
                configured_backend="LOCAL_CHILD",
            ),
            value,
        )


class ProductionWorkerCanonicalMandatoryRepositoryInvariantTests(unittest.TestCase):
    def test_production_executor_import_is_exact(self):
        tree = ast.parse(TARGET.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "production_execution_gateway"
            for alias in node.names
        }
        self.assertIn("validate_gateway_request", imported)

    def test_all_runtime_host_gateway_constructors_outside_gateway_module_are_mandatory(self):
        violations = []
        for path in sorted((ROOT / "runtime/orchestrator").glob("*.py")):
            if path.name == "production_execution_gateway.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "HostExecutionGateway"
                    and not keyword_true(node, "require_canonical_authority")
                ):
                    violations.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            violations,
            [],
            "runtime HostExecutionGateway bypass callsites: " + ", ".join(violations),
        )

    def test_executor_binds_validation_before_transport_factory_call(self):
        tree = ast.parse(TARGET.read_text(encoding="utf-8"))
        helper_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_validate_production_gateway_request"
        ]
        factory_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_production_host_execution_gateway"
        ]
        self.assertTrue(helper_calls)
        self.assertTrue(factory_calls)
        self.assertLess(
            min(node.lineno for node in helper_calls),
            min(node.lineno for node in factory_calls),
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from runtime.orchestrator.production_execution_gateway import (
    GatewayError,
    HostExecutionGateway,
    build_gateway_request,
    validate_gateway_request,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_DECISION_REF,
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)

PROJECT = "wallet-affiliate-collector"
RUN = "run-mandatory"
GATE = "G1"
LV = "LV3-5"
PLAN = "d" * 64
RUN_REQ = "e" * 64
OWNED = [
    "app/services/deduplicator.py",
    "tests/test_deduplicator.py",
]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def authority_binding():
    return {
        "schema_version": "orchestration.canonical-launch-authority.v1",
        "package_ref": "execution-package://PKG-1@1",
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


def exact_tool_authority():
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
    projection = {
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


def valid_request():
    active, projection = exact_tool_authority()
    binding = authority_binding()
    return build_gateway_request(
        project_id=PROJECT,
        run_id=RUN,
        gate_id=GATE,
        lv_id=LV,
        attempt=1,
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
        adapter_contract_version="adapter.v1",
        structured_event_contract_version="events.v1",
        active_tool_authorization_contracts=active,
        owned_files=OWNED,
        canonical_plan_sha256=PLAN,
        requirement_digest=RUN_REQ,
        tool_authorization_projection=projection,
        tool_authorization_projection_sha256=digest(projection),
        canonical_authority_binding=binding,
        canonical_authority_binding_digest=digest(binding),
    )


def reseal_request(value):
    unsigned = dict(value)
    unsigned.pop("request_digest", None)
    value["request_digest"] = digest(unsigned)
    return value


class GatewayCanonicalMandatoryTests(unittest.TestCase):
    def test_valid_exact_authority_is_accepted_in_mandatory_mode(self):
        value = validate_gateway_request(
            valid_request(),
            require_canonical_authority=True,
        )
        self.assertEqual(
            value["canonical_authority_binding"]["worker_task_id"],
            "TASK-4A-08",
        )

    def test_missing_canonical_authority_is_rejected_even_if_outer_request_is_resealed(self):
        value = valid_request()
        value["canonical_authority_binding"] = {}
        value["canonical_authority_binding_digest"] = ""
        reseal_request(value)
        with self.assertRaises(GatewayError) as caught:
            validate_gateway_request(value, require_canonical_authority=True)
        self.assertIn("CANONICAL_AUTHORITY_REQUIRED", str(caught.exception))

    def test_missing_tool_projection_is_rejected_in_mandatory_mode(self):
        value = valid_request()
        value["tool_authorization_projection"] = {}
        value["tool_authorization_projection_sha256"] = ""
        value["active_tool_authorization_contracts"] = []
        reseal_request(value)
        with self.assertRaises(GatewayError) as caught:
            validate_gateway_request(value, require_canonical_authority=True)
        self.assertIn("CANONICAL_TOOL_AUTHORITY_REQUIRED", str(caught.exception))

    def test_nested_canonical_digest_field_must_be_sha256(self):
        value = valid_request()
        value["canonical_authority_binding"]["package_digest"] = "not-a-digest"
        value["canonical_authority_binding_digest"] = digest(
            value["canonical_authority_binding"]
        )
        reseal_request(value)
        with self.assertRaises(GatewayError):
            validate_gateway_request(value, require_canonical_authority=True)

    def test_plan_and_requirement_binding_must_be_exact_sha256(self):
        value = valid_request()
        value["requirement_digest"] = ""
        reseal_request(value)
        with self.assertRaises(GatewayError):
            validate_gateway_request(value, require_canonical_authority=True)

    def test_host_gateway_enforcement_blocks_before_transport(self):
        called = {"value": False}

        def transport(*args, **kwargs):
            called["value"] = True
            return {}

        value = valid_request()
        value["canonical_authority_binding"] = {}
        value["canonical_authority_binding_digest"] = ""
        reseal_request(value)

        gateway = HostExecutionGateway(
            transport=transport,
            require_canonical_authority=True,
        )
        with self.assertRaises(GatewayError):
            gateway.execute(
                value,
                prompt=b"x",
                last_message=Path("/tmp/last-message"),
                timeout=1,
                cancel_path=Path("/tmp/cancel"),
            )
        self.assertFalse(called["value"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import unittest

from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.production_execution_gateway import (
    GatewayError,
    build_gateway_request,
    validate_gateway_request,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_DECISION_REF,
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def canonical_binding():
    return {
        "schema_version": "orchestration.canonical-launch-authority.v2",
        "package_ref": "package://PKG-1@1#" + "1" * 64,
        "package_digest": "1" * 64,
        "contract_ref": "contract://CEC-1@1#" + "2" * 64,
        "contract_digest": "2" * 64,
        "contract_activation_digest": "3" * 64,
        "worker_task_id": "TASK-4A-08",
        "criterion_set_digest": "4" * 64,
        "execution_obligation": "MUTATION_REQUIRED",
        "preflight_evidence_digest": "5" * 64,
        "codex_auth_readiness_ref": "CAE-initial",
        "codex_auth_recheck_evidence_ref": "CAE-recheck",
        "codex_cli_version": "0.163.0",
        "launch_authorization_digest": "6" * 64,
        "migration_authority_ref": "migration-authority://R4.1/manifest",
    }


def build_request(binding=None, binding_digest=None):
    binding = canonical_binding() if binding is None else binding
    digest = _digest(binding) if binding_digest is None else binding_digest
    owned = ("owned.txt",)
    approved = build_dec007_approved_contracts(
        project_id="wallet-affiliate-collector",
        gate_id="G1",
        lv_id="LV3-5",
        run_id="run-1",
        canonical_plan_sha256="d" * 64,
        owned_files=owned,
    )
    contracts = [
        activate_contract(
            item,
            package_binding_sha256="7" * 64,
            authorized_decisions={DEC007_DECISION_REF: "USER_DECISION"},
        ).to_dict()
        for item in approved
    ]
    projection = {
        "decision_ref": DEC007_DECISION_REF,
        "worker_task_id": "TASK-4A-08",
        "active_contract_count": len(contracts),
        "contract_ids": sorted(item["contract_id"] for item in contracts),
        "operation_class_ids": sorted(item["operation_class_id"] for item in contracts),
        "owned_scope_sha256": owned_scope_digest(owned),
        "package_binding_sha256": "7" * 64,
        "requirement_digests": {
            item["operation_class_id"]: item["requirement_digest"]
            for item in contracts
        },
    }
    return build_gateway_request(
        project_id="wallet-affiliate-collector",
        run_id="run-1",
        gate_id="G1",
        lv_id="LV3-5",
        attempt=1,
        workspace_identity={
            "project_id": "wallet-affiliate-collector",
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
        canonical_plan_sha256="d" * 64,
        requirement_digest="e" * 64,
        active_tool_authorization_contracts=contracts,
        owned_files=list(owned),
        tool_authorization_projection=projection,
        tool_authorization_projection_sha256=_digest(projection),
        canonical_authority_binding=binding,
        canonical_authority_binding_digest=digest,
    )


class GatewayCanonicalAuthorityBindingTests(unittest.TestCase):
    def test_exact_canonical_authority_binding_is_accepted(self):
        value = build_request()
        validated = validate_gateway_request(value)
        self.assertEqual(
            validated["canonical_authority_binding_digest"],
            _digest(validated["canonical_authority_binding"]),
        )

    def test_codex_launch_version_must_match_the_launch_bound_version(self):
        from runtime.orchestrator.production_execution_gateway import (
            validate_codex_launch_version,
        )

        value = build_request()
        self.assertEqual(validate_codex_launch_version(value, "0.163.0"), "0.163.0")
        with self.assertRaisesRegex(GatewayError, "CODEX_LAUNCH_VERSION_BINDING_MISMATCH"):
            validate_codex_launch_version(value, "0.164.0")

    def test_codex_execution_rejects_not_applicable_or_unbound_launch_version(self):
        from runtime.orchestrator.production_execution_gateway import (
            validate_codex_launch_version,
        )

        binding = canonical_binding()
        binding["codex_cli_version"] = "NOT_APPLICABLE"
        with self.assertRaisesRegex(GatewayError, "CODEX_LAUNCH_VERSION_BINDING_MISMATCH"):
            validate_codex_launch_version(
                build_request(binding=binding, binding_digest=_digest(binding)),
                "0.163.0",
            )

    def test_nested_binding_tamper_is_rejected_even_with_resealed_outer_request(self):
        value = build_request()
        value["canonical_authority_binding"]["contract_digest"] = "f" * 64
        unsigned = dict(value)
        unsigned.pop("request_digest")
        value["request_digest"] = _digest(unsigned)
        with self.assertRaises(GatewayError) as caught:
            validate_gateway_request(value)
        self.assertIn("canonical authority binding mismatch", str(caught.exception))

    def test_wrong_canonical_schema_is_rejected(self):
        binding = canonical_binding()
        binding["schema_version"] = "forged.v1"
        value = build_request(binding=binding, binding_digest=_digest(binding))
        with self.assertRaises(GatewayError):
            validate_gateway_request(value)

    def test_legacy_empty_binding_remains_parseable_during_bridge_rollout(self):
        value = build_gateway_request(
            project_id="wallet-affiliate-collector",
            run_id="run-legacy",
            gate_id="G1",
            lv_id="LV3-5",
            attempt=1,
            workspace_identity={"project_id": "wallet-affiliate-collector"},
            package_manifest_sha256="a" * 64,
            preflight_evidence_sha256="b" * 64,
            runtime_prompt_artifact={
                "kind": "worker_runtime_prompt",
                "name": "executor.prompt.txt",
            },
            runtime_prompt_sha256="c" * 64,
            adapter_contract_version="adapter.v1",
            structured_event_contract_version="events.v1",
        )
        validated = validate_gateway_request(value)
        self.assertEqual(validated["canonical_authority_binding"], {})
        self.assertEqual(validated["canonical_authority_binding_digest"], "")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import unittest

from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.production_execution_gateway import (
    GatewayError,
    build_gateway_request,
    validate_gateway_request,
)


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def canonical_binding():
    return {
        "schema_version": "orchestration.canonical-launch-authority.v1",
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
        "launch_authorization_digest": "6" * 64,
        "migration_authority_ref": "migration-authority://R4.1/manifest",
    }


def build_request(binding=None, binding_digest=None):
    binding = canonical_binding() if binding is None else binding
    digest = _digest(binding) if binding_digest is None else binding_digest
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

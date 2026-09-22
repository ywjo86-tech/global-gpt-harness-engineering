from __future__ import annotations

import unittest

from runtime.orchestrator.operator_control import OPERATOR_DIRECTIVE_SCHEMA, OperatorDirectiveV1
from runtime.orchestrator.production_execution_gateway import (
    GatewayError,
    _digest,
    build_gateway_request,
)
from runtime.orchestrator.remote_operator_ingress import (
    RemoteExecutionGatewayError,
    dispatch_action_through_production_gateway,
)
from runtime.orchestrator.tool_authorization import (
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)


class RemoteOperatorGatewayBoundaryTests(unittest.TestCase):
    def _directive(self, *, state_change=True):
        return OperatorDirectiveV1.from_mapping({
            "schema_version": OPERATOR_DIRECTIVE_SCHEMA,
            "project_id": "p", "run_id": "r", "task_id": "L", "task_execution_id": "E1",
            "current_stage": "PREPARE",
            "requested_next_stage": "ACTION" if state_change else "VERIFY",
            "required_capabilities": ["filesystem_write"] if state_change else ["reasoning"],
            "state_change_required": state_change,
            "input_artifact_digests": ["a" * 64] if state_change else [],
            "gate_id": "g", "directive_id": "D-GW",
        })

    def _canonical_request(self):
        package_binding = "f" * 64
        plan = "d" * 64
        owned = ("owned.txt",)
        approved = build_dec007_approved_contracts(
            project_id="p", gate_id="g", lv_id="L", run_id="r",
            canonical_plan_sha256=plan, owned_files=owned,
        )
        contracts = [
            activate_contract(
                item,
                package_binding_sha256=package_binding,
                authorized_decisions={"DEC-007": "USER_DECISION"},
            ).to_dict()
            for item in approved
        ]
        projection = {
            "decision_ref": "DEC-007",
            "worker_task_id": "TASK-4A-08",
            "active_contract_count": 3,
            "contract_ids": sorted(item["contract_id"] for item in contracts),
            "operation_class_ids": sorted(item["operation_class_id"] for item in contracts),
            "owned_scope_sha256": owned_scope_digest(owned),
            "package_binding_sha256": package_binding,
            "requirement_digests": {
                item["operation_class_id"]: item["requirement_digest"] for item in contracts
            },
        }
        authority = {
            "schema_version": "orchestration.canonical-launch-authority.v1",
            "package_ref": "package:1",
            "package_digest": "1" * 64,
            "contract_ref": "contract:1",
            "contract_digest": "2" * 64,
            "contract_activation_digest": "3" * 64,
            "worker_task_id": "TASK-4A-08",
            "criterion_set_digest": "4" * 64,
            "execution_obligation": "MUTATION_REQUIRED",
            "preflight_evidence_digest": "5" * 64,
            "codex_auth_readiness_ref": "auth:ready",
            "codex_auth_recheck_evidence_ref": "auth:recheck",
            "launch_authorization_digest": "6" * 64,
            "migration_authority_ref": "migration:none",
        }
        return build_gateway_request(
            project_id="p", run_id="r", gate_id="g", lv_id="L", attempt=1,
            workspace_identity={"project_id": "p", "workspace_kind": "project_root"},
            package_manifest_sha256="a" * 64,
            preflight_evidence_sha256="b" * 64,
            runtime_prompt_artifact={"kind": "worker_runtime_prompt", "name": "executor.prompt.txt"},
            runtime_prompt_sha256="c" * 64,
            adapter_contract_version="SEM-025.v2",
            structured_event_contract_version="codex-exec-jsonl.0.150.1.v1",
            active_tool_authorization_contracts=contracts,
            owned_files=list(owned),
            canonical_plan_sha256=plan,
            requirement_digest="e" * 64,
            tool_authorization_projection=projection,
            tool_authorization_projection_sha256=_digest(projection),
            canonical_authority_binding=authority,
            canonical_authority_binding_digest=_digest(authority),
        )

    def test_state_changing_action_reaches_canonical_gateway_exactly_once(self):
        calls = []
        request = self._canonical_request()

        def gateway(validated):
            calls.append(validated["execution_request_id"])
            return {"status": "COMPLETED", "request_digest": validated["request_digest"]}

        result = dispatch_action_through_production_gateway(
            self._directive(), gateway_request=request, gateway_dispatch=gateway,
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(calls, [request["execution_request_id"]])

    def test_read_only_transition_does_not_call_mutation_gateway(self):
        calls = []
        result = dispatch_action_through_production_gateway(
            self._directive(state_change=False),
            gateway_request={},
            gateway_dispatch=lambda request: calls.append(request),
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_missing_canonical_authorization_projection_fails_closed(self):
        request = self._canonical_request()
        request["tool_authorization_projection"] = {}
        unsigned = dict(request); unsigned.pop("request_digest")
        request["request_digest"] = _digest(unsigned)
        calls = []
        with self.assertRaisesRegex(RemoteExecutionGatewayError, "EXECUTION_GATEWAY_BLOCKED"):
            dispatch_action_through_production_gateway(
                self._directive(), gateway_request=request,
                gateway_dispatch=lambda validated: calls.append(validated),
            )
        self.assertEqual(calls, [])

    def test_gateway_identity_mismatch_is_blocked(self):
        request = self._canonical_request()
        request["run_id"] = "other"
        unsigned = dict(request); unsigned.pop("request_digest")
        request["request_digest"] = _digest(unsigned)
        with self.assertRaisesRegex(RemoteExecutionGatewayError, "EXECUTION_GATEWAY_BLOCKED"):
            dispatch_action_through_production_gateway(
                self._directive(), gateway_request=request, gateway_dispatch=lambda _: None,
            )

    def test_dispatch_failure_is_projected_as_gateway_block_not_direct_fallback(self):
        request = self._canonical_request()
        with self.assertRaisesRegex(RemoteExecutionGatewayError, "EXECUTION_GATEWAY_BLOCKED"):
            dispatch_action_through_production_gateway(
                self._directive(), gateway_request=request,
                gateway_dispatch=lambda _: (_ for _ in ()).throw(GatewayError("HOST_GATEWAY_UNAVAILABLE")),
            )


if __name__ == "__main__":
    unittest.main()

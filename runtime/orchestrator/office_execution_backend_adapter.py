"""Backend-neutral AI Office execution adapter.

Concrete backend composition is deliberately external.  This module accepts an
injected ExecutionRuntimeHandler-compatible callable and never imports or
constructs a concrete action backend.
"""
from __future__ import annotations

from typing import Any, Mapping

from .office_execution_contract import (
    OFFICE_EXECUTION_RESULT_SCHEMA_V1,
    BackendNeutralExecutionPort,
    OfficeExecutionContractError,
    OfficeExecutionRequestV1,
    OfficeExecutionResultV1,
)
from .production_execution_gateway import ExecutionRuntimeHandler

PORT_SCHEMA_V1 = "ai-office.execution-backend-port.v1"


class OfficeExecutionBackendAdapterError(ValueError):
    pass


class OfficeExecutionBackendAdapter:
    def __init__(self, runtime_handler: ExecutionRuntimeHandler | BackendNeutralExecutionPort) -> None:
        if not callable(runtime_handler):
            raise OfficeExecutionBackendAdapterError("ExecutionRuntimeHandler is required")
        self._runtime_handler = runtime_handler

    @staticmethod
    def _port_request(request: OfficeExecutionRequestV1) -> dict[str, Any]:
        if not isinstance(request, OfficeExecutionRequestV1):
            raise OfficeExecutionBackendAdapterError("OfficeExecutionRequestV1 is required")
        return {
            "schema_version": PORT_SCHEMA_V1,
            "office_request_digest": request.request_digest,
            "office_execution_request": request.to_dict(),
            "authorization_lineage": {
                "governance_decision_ref": request.governance_decision_ref,
                "governance_decision_digest": request.governance_decision_digest,
                "risk_envelope_ref": request.risk_envelope_ref,
                "risk_envelope_digest": request.risk_envelope_digest,
                "delegated_authorization_ref": request.delegated_authorization_ref,
                "delegated_authorization_digest": request.delegated_authorization_digest,
                "authorization_binding_ref": request.authorization_binding_ref,
                "authorization_binding_digest": request.authorization_binding_digest,
            },
            "expected_effect_semantics": request.expected_effect_semantics,
            "execution_package_ref": request.execution_package_ref,
            "execution_package_digest": request.execution_package_digest,
            "execution_contract_ref": request.execution_contract_ref,
            "execution_contract_digest": request.execution_contract_digest,
        }

    @staticmethod
    def _project_result(request: OfficeExecutionRequestV1, raw: Mapping[str, Any]) -> OfficeExecutionResultV1:
        if not isinstance(raw, Mapping):
            raise OfficeExecutionBackendAdapterError("runtime handler result must be a mapping")
        if raw.get("office_request_digest") != request.request_digest:
            raise OfficeExecutionBackendAdapterError("runtime result request binding mismatch")
        exact = {
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "workflow_item_id": request.workflow_item_id,
            "task_execution_id": request.task_execution_id,
            "correlation_id": request.correlation_id,
        }
        if any(raw.get(key) != value for key, value in exact.items()):
            raise OfficeExecutionBackendAdapterError("runtime result identity binding mismatch")
        status = str(raw.get("status", ""))
        result_digest = str(raw.get("result_digest", ""))
        effect_ref = str(raw.get("effect_ref", ""))
        audit_ref = str(raw.get("audit_ref", ""))
        reconciliation_state = str(raw.get("reconciliation_state", "NOT_REQUIRED"))
        error_code = str(raw.get("error_code", ""))
        if request.expected_effect_semantics == "READ_ONLY" and effect_ref:
            raise OfficeExecutionBackendAdapterError("READ_ONLY execution cannot return a mutation effect reference")
        if request.expected_effect_semantics == "STATE_CHANGING" and status == "COMPLETED" and not effect_ref:
            raise OfficeExecutionBackendAdapterError("completed state-changing execution requires effect evidence")
        try:
            return OfficeExecutionResultV1(
                schema_version=OFFICE_EXECUTION_RESULT_SCHEMA_V1,
                project_id=request.project_id,
                project_run_id=request.project_run_id,
                workflow_item_id=request.workflow_item_id,
                task_execution_id=request.task_execution_id,
                correlation_id=request.correlation_id,
                request_digest=request.request_digest,
                status=status,
                result_digest=result_digest,
                effect_ref=effect_ref,
                audit_ref=audit_ref,
                reconciliation_state=reconciliation_state,
                error_code=error_code,
            )
        except OfficeExecutionContractError as exc:
            raise OfficeExecutionBackendAdapterError(str(exc)) from exc

    def execute(self, request: OfficeExecutionRequestV1) -> OfficeExecutionResultV1:
        payload = self._port_request(request)
        try:
            raw = self._runtime_handler(payload)
        except Exception as exc:
            raise OfficeExecutionBackendAdapterError(f"execution runtime handler failed: {type(exc).__name__}") from exc
        return self._project_result(request, raw)

from __future__ import annotations

from typing import Sequence

from runtime.orchestrator.tool_authorization import (
    ClosedOperationRegistry,
    RegisteredOperation,
    ToolAuthorizationContract,
    ToolAuthorizationError,
    validate_contract,
)


class OperationRegistryError(ValueError):
    pass


class FullMCPOperationRegistry:
    """Sealed wrapper around the preserved closed-registry authority."""

    def __init__(self, operations: Sequence[RegisteredOperation]) -> None:
        try:
            self._registry = ClosedOperationRegistry(tuple(operations))
        except ToolAuthorizationError as exc:
            raise OperationRegistryError("operation registry sealing failed") from exc

    def resolve(self, operation_class_id: str) -> RegisteredOperation:
        try:
            return self._registry.resolve(operation_class_id)
        except ToolAuthorizationError as exc:
            raise OperationRegistryError("unknown operation blocked") from exc
    def resolve_for_contract(
        self, operation_class_id: str, contract: ToolAuthorizationContract
    ) -> RegisteredOperation:
        try:
            validate_contract(contract)
        except ToolAuthorizationError as exc:
            raise OperationRegistryError("authorization contract is invalid") from exc
        if contract.contract_status != "ACTIVE":
            raise OperationRegistryError("authorization contract is not ACTIVE")
        if contract.operation_class_id != operation_class_id:
            raise OperationRegistryError("operation/authorization contract mismatch")
        operation = self.resolve(operation_class_id)
        if (
            operation.capability_class != contract.capability_class
            or operation.operation_intent != contract.operation_intent
        ):
            raise OperationRegistryError("registry/authorization taxonomy mismatch")
        return operation

    def dynamic_specs(self, operation_class_ids: Sequence[str] | None = None) -> list[dict]:
        try:
            return self._registry.dynamic_specs(operation_class_ids)
        except ToolAuthorizationError as exc:
            raise OperationRegistryError("dynamic registry projection failed") from exc

    def evidence(self) -> dict[str, object]:
        value = self._registry.evidence()
        return {**value, "sealed": True, "authority": "PRESERVED_CLOSED_OPERATION_REGISTRY"}

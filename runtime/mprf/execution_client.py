"""Public-boundary-only execution client reserved for the future MPRF consumer."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from runtime.orchestrator.public_execution_contract import (
    PublicExecutionRequestV1,
    PublicExecutionResultV1,
    public_execution_result_from_mapping,
)

PublicExecutionTransport = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class PublicExecutionClientError(ValueError):
    pass


class PublicExecutionClient:
    def __init__(self, transport: PublicExecutionTransport) -> None:
        if not callable(transport):
            raise PublicExecutionClientError("public execution transport must be callable")
        self._transport = transport

    def execute(self, request: PublicExecutionRequestV1) -> PublicExecutionResultV1:
        if not isinstance(request, PublicExecutionRequestV1):
            raise PublicExecutionClientError("request must use the public execution contract")
        raw = self._transport(request.to_dict())
        if not isinstance(raw, Mapping):
            raise PublicExecutionClientError("public execution transport returned a non-object")
        result = public_execution_result_from_mapping(raw)
        if result.operation_request_id != request.operation_request_id or result.correlation_id != request.correlation_id:
            raise PublicExecutionClientError("public execution response binding mismatch")
        return result

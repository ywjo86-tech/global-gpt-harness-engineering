"""Fail-closed Ruflo filtering proxy for individually qualified read-only tools.

The proxy is intentionally not an orchestrator, provider router, memory owner,
or effect authority.  It exposes zero tools by default and can project only an
individually qualified read-only tool into the existing closed tool registry.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

from .external_advisory_contract import (
    ExternalCapabilityContractError,
    ExternalCapabilityRequestV1,
    ExternalCapabilityResultV1,
    canonical_external_digest,
)
from .tool_authorization import RegisteredOperation, ToolAuthorizationError

RUFLO_PINNED_VERSION = "3.44.0"
RUFLO_PINNED_COMMIT = "0a96fb8857dabd343d71d76c3ca703100a2923bc"
RUFLO_CAPABILITY_ID = "external.ruflo.coordination_advisory.v1"
RUFLO_DENY_EGRESS_POLICY = "egress:deny-all"

_STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _closed_object_schema(value: object, field: str) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("type") != "object"
        or value.get("additionalProperties") is not False
        or not isinstance(value.get("properties", {}), Mapping)
    ):
        raise ExternalCapabilityContractError(f"Ruflo {field} must be a closed object schema")
    return value


def _validate_closed_payload(schema: Mapping[str, Any], payload: Mapping[str, Any], field: str) -> None:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise ExternalCapabilityContractError(f"Ruflo {field} schema is malformed")
    if any(key not in payload for key in required) or any(key not in properties for key in payload):
        raise ExternalCapabilityContractError(f"Ruflo {field} violates closed schema")


@dataclass(frozen=True, slots=True)
class RufloQualifiedToolV1:
    runtime_version: str
    runtime_commit: str
    tool_id: str
    operation_registration_id: str
    operation_class_id: str
    capability_class: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    schema_digest: str
    effect_class: str
    read_only: bool
    filesystem_write: bool
    shell_execution: bool
    git_write: bool
    memory_read: bool
    memory_write: bool
    canonical_state_write: bool
    agent_spawn: bool
    worker_spawn: bool
    swarm_execution: bool
    daemon: bool
    hooks: bool
    background_task: bool
    provider_call: bool
    model_call: bool
    network_egress: bool
    egress_policy_ref: str
    max_delegation_depth: int

    def __post_init__(self) -> None:
        if self.runtime_version != RUFLO_PINNED_VERSION or self.runtime_commit != RUFLO_PINNED_COMMIT:
            raise ExternalCapabilityContractError("Ruflo runtime identity is not the approved pin")
        for field in ("tool_id", "operation_registration_id", "operation_class_id", "capability_class"):
            value = getattr(self, field)
            if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
                raise ExternalCapabilityContractError(f"Ruflo {field} is not a safe stable identifier")
        input_schema = _closed_object_schema(self.input_schema, "input schema")
        output_schema = _closed_object_schema(self.output_schema, "output schema")
        expected_schema_digest = canonical_external_digest(
            {"input_schema": input_schema, "output_schema": output_schema}
        )
        if self.schema_digest != expected_schema_digest:
            raise ExternalCapabilityContractError("Ruflo tool schema digest mismatch")
        if self.effect_class != "READ_ONLY" or self.read_only is not True:
            raise ExternalCapabilityContractError("Ruflo tool must be strictly read-only")
        forbidden = (
            self.filesystem_write,
            self.shell_execution,
            self.git_write,
            self.memory_read,
            self.memory_write,
            self.canonical_state_write,
            self.agent_spawn,
            self.worker_spawn,
            self.swarm_execution,
            self.daemon,
            self.hooks,
            self.background_task,
            self.provider_call,
            self.model_call,
            self.network_egress,
        )
        if any(value is not False for value in forbidden):
            raise ExternalCapabilityContractError("Ruflo tool declares a forbidden behavior class")
        if self.egress_policy_ref != RUFLO_DENY_EGRESS_POLICY:
            raise ExternalCapabilityContractError("Ruflo tool egress is not deny-by-default")
        if isinstance(self.max_delegation_depth, bool) or self.max_delegation_depth != 0:
            raise ExternalCapabilityContractError("Ruflo tool delegation depth must be zero")


def ruflo_registered_operation(tool: RufloQualifiedToolV1) -> RegisteredOperation:
    operation = RegisteredOperation(
        tool.operation_registration_id,
        tool.operation_class_id,
        tool.capability_class,
        "READ",
        "READ_ONLY",
        dict(tool.input_schema),
        dict(tool.output_schema),
    )
    try:
        operation.validate()
    except ToolAuthorizationError as exc:
        raise ExternalCapabilityContractError("Ruflo tool cannot enter the closed registry") from exc
    return operation


class RufloFilteringProxy:
    """Zero-tool-by-default proxy that invokes one exact qualified tool once."""

    def __init__(
        self,
        *,
        runtime_version: str,
        runtime_commit: str,
        runtime_invoker: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        qualified_tools: Sequence[RufloQualifiedToolV1] = (),
    ) -> None:
        if runtime_version != RUFLO_PINNED_VERSION or runtime_commit != RUFLO_PINNED_COMMIT:
            raise ExternalCapabilityContractError("Ruflo runtime identity is not the approved pin")
        if not callable(runtime_invoker):
            raise ExternalCapabilityContractError("Ruflo runtime invoker is unavailable")
        self.runtime_version = runtime_version
        self.runtime_commit = runtime_commit
        self._runtime_invoker = runtime_invoker
        tools: dict[str, RufloQualifiedToolV1] = {}
        operation_ids: set[str] = set()
        registration_ids: set[str] = set()
        for tool in tuple(qualified_tools):
            if tool.runtime_version != runtime_version or tool.runtime_commit != runtime_commit:
                raise ExternalCapabilityContractError("Ruflo qualified tool runtime binding mismatch")
            if tool.tool_id in tools or tool.operation_class_id in operation_ids or tool.operation_registration_id in registration_ids:
                raise ExternalCapabilityContractError("duplicate Ruflo qualified tool identity")
            tools[tool.tool_id] = tool
            operation_ids.add(tool.operation_class_id)
            registration_ids.add(tool.operation_registration_id)
        self._tools = tools

    @property
    def qualified_tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def registered_operations(self) -> tuple[RegisteredOperation, ...]:
        return tuple(ruflo_registered_operation(self._tools[tool_id]) for tool_id in self.qualified_tool_ids)

    def invoke(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        *,
        request: ExternalCapabilityRequestV1,
        evidence_ref: str,
    ) -> ExternalCapabilityResultV1:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise ExternalCapabilityContractError("unknown Ruflo tool is blocked")
        if request.capability_id != RUFLO_CAPABILITY_ID or request.capability_version != RUFLO_PINNED_VERSION:
            raise ExternalCapabilityContractError("Ruflo request capability binding mismatch")
        if request.provider_bound:
            raise ExternalCapabilityContractError("Ruflo v1 read-only tool cannot carry provider binding")
        if request.schema_digest != tool.schema_digest or request.egress_policy_ref != tool.egress_policy_ref:
            raise ExternalCapabilityContractError("Ruflo request qualification binding mismatch")
        if not isinstance(arguments, Mapping):
            raise ExternalCapabilityContractError("Ruflo tool arguments must be a mapping")
        _validate_closed_payload(tool.input_schema, arguments, "input")
        raw_result = self._runtime_invoker(tool.tool_id, dict(arguments))
        if not isinstance(raw_result, Mapping):
            raise ExternalCapabilityContractError("Ruflo tool output must be a mapping")
        _validate_closed_payload(tool.output_schema, raw_result, "output")
        return ExternalCapabilityResultV1.from_external_payload(
            request=request,
            external_payload=dict(raw_result),
            evidence_ref=evidence_ref,
        )

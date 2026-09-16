from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
INVOCATION_CONTEXT_SCHEMA = "gch.full-mcp.invocation-context.v1"


class FullMCPContractError(ValueError):
    pass


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise FullMCPContractError(f"{field} is not a safe stable identifier")
    return value
def _workspace_root(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
        raise FullMCPContractError("workspace_root is invalid")
    if "\\" in value:
        raise FullMCPContractError("workspace_root must use POSIX separators")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or path.as_posix() == "/":
        raise FullMCPContractError("workspace_root must be a canonical absolute workspace path")
    return path.as_posix()


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise FullMCPContractError(f"{field} is not a SHA-256 digest")
    return value


def _scope_tuple(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise FullMCPContractError(f"{field} must be a sequence")
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise FullMCPContractError(f"{field} contains an invalid path")
    if len(result) != len(set(result)):
        raise FullMCPContractError(f"{field} contains duplicates")
    return result


@dataclass(frozen=True, slots=True)
class InvocationContext:
    schema_version: str
    project_id: str
    run_id: str
    gate_id: str
    lv_id: str
    attempt: int
    request_digest: str
    correlation_id: str
    workspace_root: str
    canonical_plan_sha256: str
    dependency_lock_sha256: str
    authorization_contract_digests: tuple[str, ...]
    read_scopes: tuple[str, ...]
    mutable_scopes: tuple[str, ...]
    read_scope_sha256: str
    mutable_scope_sha256: str
    validation_profile_digests: tuple[str, ...]
    invocation_context_id: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("invocation_context_id")
        return value

    def sealed(self) -> "InvocationContext":
        validate_invocation_context(self, require_id=False)
        return replace(self, invocation_context_id="ctx-" + canonical_sha256(self.unsigned()))

    def to_dict(self) -> dict[str, Any]:
        validate_invocation_context(self)
        return asdict(self)


def validate_invocation_context(context: InvocationContext, *, require_id: bool = True) -> None:
    if context.schema_version != INVOCATION_CONTEXT_SCHEMA:
        raise FullMCPContractError("unsupported invocation context schema")
    for field in ("project_id", "run_id", "gate_id", "lv_id", "correlation_id"):
        _safe_id(getattr(context, field), field)
    _workspace_root(context.workspace_root)
    if not isinstance(context.attempt, int) or context.attempt < 1:
        raise FullMCPContractError("attempt must be a positive integer")
    for field in ("request_digest", "canonical_plan_sha256", "dependency_lock_sha256",
                  "read_scope_sha256", "mutable_scope_sha256"):
        _sha256(getattr(context, field), field)
    auth_digests = tuple(context.authorization_contract_digests)
    if not auth_digests or len(auth_digests) != len(set(auth_digests)):
        raise FullMCPContractError("authorization contract digest set is empty or duplicated")
    for digest in auth_digests:
        _sha256(digest, "authorization_contract_digest")
    for digest in context.validation_profile_digests:
        _sha256(digest, "validation_profile_digest")
    read_scopes = _scope_tuple(context.read_scopes, "read_scopes")
    mutable_scopes = _scope_tuple(context.mutable_scopes, "mutable_scopes")
    if scope_digest(read_scopes) != context.read_scope_sha256:
        raise FullMCPContractError("read scope digest mismatch")
    if scope_digest(mutable_scopes) != context.mutable_scope_sha256:
        raise FullMCPContractError("mutable scope digest mismatch")
    if require_id:
        expected = "ctx-" + canonical_sha256(context.unsigned())
        if context.invocation_context_id != expected:
            raise FullMCPContractError("invocation_context_id mismatch")


def scope_digest(values: Sequence[str]) -> str:
    values = _scope_tuple(values, "scope")
    return canonical_sha256(sorted(values))


@dataclass(frozen=True, slots=True)
class MCPMetaBinding:
    invocation_context_id: str
    request_digest: str
    correlation_id: str
    operation_request_id: str

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "MCPMetaBinding":
        keys = {
            "gch/full-mcp/invocation_context_id": "invocation_context_id",
            "gch/full-mcp/request_digest": "request_digest",
            "gch/full-mcp/correlation_id": "correlation_id",
            "gch/full-mcp/operation_request_id": "operation_request_id",
        }
        missing = [key for key in keys if key not in meta]
        if missing:
            raise FullMCPContractError("required Full MCP metadata is missing")
        values = {field: meta[key] for key, field in keys.items()}
        if any(not isinstance(value, str) for value in values.values()):
            raise FullMCPContractError("Full MCP metadata values must be strings")
        binding = cls(**values)
        binding.validate()
        return binding

    def validate(self) -> None:
        if not self.invocation_context_id.startswith("ctx-"):
            raise FullMCPContractError("invalid invocation_context_id")
        suffix = self.invocation_context_id[4:]
        _sha256(suffix, "invocation_context_id")
        _sha256(self.request_digest, "request_digest")
        _safe_id(self.correlation_id, "correlation_id")
        _safe_id(self.operation_request_id, "operation_request_id")

    def bind_to(self, context: InvocationContext) -> None:
        self.validate()
        validate_invocation_context(context)
        if (
            self.invocation_context_id != context.invocation_context_id
            or self.request_digest != context.request_digest
            or self.correlation_id != context.correlation_id
        ):
            raise FullMCPContractError("MCP metadata/context binding mismatch")


def context_from_dict(raw: Mapping[str, Any]) -> InvocationContext:
    try:
        value = dict(raw)
        for field in ("authorization_contract_digests", "read_scopes", "mutable_scopes", "validation_profile_digests"):
            value[field] = tuple(value.get(field, ()))
        context = InvocationContext(**value)
    except (TypeError, KeyError) as exc:
        raise FullMCPContractError("invocation context payload is malformed") from exc
    validate_invocation_context(context)
    return context

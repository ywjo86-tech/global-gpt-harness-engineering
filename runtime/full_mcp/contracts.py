from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
INVOCATION_CONTEXT_SCHEMA_V1 = "gch.full-mcp.invocation-context.v1"
INVOCATION_CONTEXT_SCHEMA_V2 = "gch.full-mcp.invocation-context.v2"
INVOCATION_CONTEXT_SCHEMA = INVOCATION_CONTEXT_SCHEMA_V1
GIT_PUBLICATION_AUTH_SCHEMA_V1 = "gch.full-mcp.git-publication-authorization.v1"
GIT_STAGE_INTENT_SCHEMA_V1 = "gch.full-mcp.git-stage-intent.v1"
GIT_COMMIT_INTENT_SCHEMA_V1 = "gch.full-mcp.git-commit-intent.v1"
GIT_PUSH_INTENT_SCHEMA_V1 = "gch.full-mcp.git-push-intent.v1"
PUBLICATION_OPERATIONS = ("git_stage", "git_commit", "git_push")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")


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
    operation_policy_digests: tuple[str, ...] = ()
    invocation_context_id: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("invocation_context_id")
        if self.schema_version == INVOCATION_CONTEXT_SCHEMA_V1:
            value.pop("operation_policy_digests", None)
        return value

    def sealed(self) -> "InvocationContext":
        validate_invocation_context(self, require_id=False)
        return replace(self, invocation_context_id="ctx-" + canonical_sha256(self.unsigned()))

    def to_dict(self) -> dict[str, Any]:
        validate_invocation_context(self)
        value = asdict(self)
        if self.schema_version == INVOCATION_CONTEXT_SCHEMA_V1:
            value.pop("operation_policy_digests", None)
        return value


def validate_invocation_context(context: InvocationContext, *, require_id: bool = True) -> None:
    if context.schema_version not in {INVOCATION_CONTEXT_SCHEMA_V1, INVOCATION_CONTEXT_SCHEMA_V2}:
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
    policy_digests = tuple(context.operation_policy_digests)
    if len(policy_digests) != len(set(policy_digests)):
        raise FullMCPContractError("operation policy digest set contains duplicates")
    for digest in policy_digests:
        _sha256(digest, "operation_policy_digest")
    if context.schema_version == INVOCATION_CONTEXT_SCHEMA_V1 and policy_digests:
        raise FullMCPContractError("InvocationContext.v1 cannot bind operation policies")
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
        for field in ("authorization_contract_digests", "read_scopes", "mutable_scopes", "validation_profile_digests", "operation_policy_digests"):
            value[field] = tuple(value.get(field, ()))
        context = InvocationContext(**value)
    except (TypeError, KeyError) as exc:
        raise FullMCPContractError("invocation context payload is malformed") from exc
    validate_invocation_context(context)
    return context


def _git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not GIT_SHA_RE.fullmatch(value):
        raise FullMCPContractError(f"{field} is not a git object id")
    return value


def _bounded_subject(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or "\n" in value or "\r" in value:
        raise FullMCPContractError("commit subject is invalid")
    return value


@dataclass(frozen=True, slots=True)
class GitPublicationAuthorizationV1:
    schema_version: str
    repository_identity_digest: str
    approved_branch: str
    approved_remote: str
    remote_url_fingerprint: str
    allowed_path_digest: str
    expected_remote_head: str
    protected_branch_policy_ref: str
    approval_ref: str
    issued_at: str
    expires_at: str
    operations: tuple[str, ...] = PUBLICATION_OPERATIONS

    def __post_init__(self) -> None:
        if self.schema_version != GIT_PUBLICATION_AUTH_SCHEMA_V1:
            raise FullMCPContractError("unsupported GitPublicationAuthorization schema")
        for value, field in (
            (self.repository_identity_digest, "repository_identity_digest"),
            (self.remote_url_fingerprint, "remote_url_fingerprint"),
            (self.allowed_path_digest, "allowed_path_digest"),
        ):
            _sha256(value, field)
        _git_sha(self.expected_remote_head, "expected_remote_head")
        for value, field in (
            (self.approved_branch, "approved_branch"), (self.approved_remote, "approved_remote"),
            (self.protected_branch_policy_ref, "protected_branch_policy_ref"), (self.approval_ref, "approval_ref"),
        ):
            _safe_id(value, field)
        if not self.issued_at or not self.expires_at:
            raise FullMCPContractError("publication authorization timestamps are required")
        try:
            issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FullMCPContractError("publication authorization timestamp format is invalid") from exc
        if issued.tzinfo is None or expires.tzinfo is None or issued >= expires:
            raise FullMCPContractError("publication authorization time window is invalid")
        if tuple(self.operations) != PUBLICATION_OPERATIONS:
            raise FullMCPContractError("publication authorization operation set must be exact")

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value["operations"] = list(self.operations); return value

    @property
    def policy_digest(self) -> str:
        return canonical_sha256(self.unsigned())

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "GitPublicationAuthorizationV1":
        try:
            value = dict(raw); value["operations"] = tuple(value.get("operations", ()))
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise FullMCPContractError("publication authorization payload is malformed") from exc


@dataclass(frozen=True, slots=True)
class GitStageIntentV1:
    schema_version: str
    paths: tuple[str, ...]
    expected_worktree_digest: str
    expected_head: str
    candidate_diff_digest: str
    publication_policy_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != GIT_STAGE_INTENT_SCHEMA_V1:
            raise FullMCPContractError("unsupported GitStageIntent schema")
        paths = _scope_tuple(self.paths, "paths")
        if not paths:
            raise FullMCPContractError("stage paths must be non-empty")
        for value, field in ((self.expected_worktree_digest, "expected_worktree_digest"),
                             (self.candidate_diff_digest, "candidate_diff_digest"),
                             (self.publication_policy_digest, "publication_policy_digest")):
            _sha256(value, field)
        _git_sha(self.expected_head, "expected_head")


@dataclass(frozen=True, slots=True)
class GitCommitIntentV1:
    schema_version: str
    expected_staged_diff_digest: str
    expected_index_digest: str
    expected_head: str
    expected_parent: str
    subject: str
    publication_policy_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != GIT_COMMIT_INTENT_SCHEMA_V1:
            raise FullMCPContractError("unsupported GitCommitIntent schema")
        for value, field in ((self.expected_staged_diff_digest, "expected_staged_diff_digest"),
                             (self.expected_index_digest, "expected_index_digest"),
                             (self.publication_policy_digest, "publication_policy_digest")):
            _sha256(value, field)
        _git_sha(self.expected_head, "expected_head"); _git_sha(self.expected_parent, "expected_parent")
        _bounded_subject(self.subject)


@dataclass(frozen=True, slots=True)
class GitPushIntentV1:
    schema_version: str
    remote: str
    branch: str
    local_commit_sha: str
    expected_remote_head: str
    publication_policy_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != GIT_PUSH_INTENT_SCHEMA_V1:
            raise FullMCPContractError("unsupported GitPushIntent schema")
        _safe_id(self.remote, "remote"); _safe_id(self.branch, "branch")
        _git_sha(self.local_commit_sha, "local_commit_sha"); _git_sha(self.expected_remote_head, "expected_remote_head")
        _sha256(self.publication_policy_digest, "publication_policy_digest")

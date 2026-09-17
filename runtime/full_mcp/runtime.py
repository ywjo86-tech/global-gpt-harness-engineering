from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from runtime.orchestrator.tool_authorization import (
    OperationIdentity,
    RegisteredOperation,
    ToolAuthorizationContract,
    ToolAuthorizationError,
    ToolEffectJournal,
)

from .authorization import (
    FullMCPAuthorizationError,
    OperationRequestReplayGuard,
    authorize_registered_operation,
    validate_contract_set,
)
from .contracts import (
    GIT_COMMIT_INTENT_SCHEMA_V1, GIT_PUSH_INTENT_SCHEMA_V1, GIT_STAGE_INTENT_SCHEMA_V1,
    INVOCATION_CONTEXT_SCHEMA_V2, FullMCPContractError, GitCommitIntentV1,
    GitPublicationAuthorizationV1, GitPushIntentV1, GitStageIntentV1, InvocationContext,
    MCPMetaBinding, canonical_sha256, scope_digest,
)
from .filesystem_service import FilesystemService, FilesystemServiceError
from .git_service import GitService, GitServiceError
from .observability import ObservabilityError, ObservabilityStore
from .operation_registry import FullMCPOperationRegistry, OperationRegistryError
from .path_policy import PathPolicyError, WorkspacePathPolicy
from .publication_evidence import seal_publication_evidence
from .process_service import ProcessService, ProcessServiceError, ShellPolicy
from .validation_profiles import ValidationProfileCatalog, ValidationProfileError, default_validation_catalog
from .validation_service import ValidationService, ValidationServiceError

RESULT_SCHEMA = "gch.full-mcp.result.v1"


class FullMCPRuntimeError(ValueError):
    def __init__(self, code: str, stage: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _object_schema(properties: Mapping[str, object], required: Sequence[str] = ()) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


def _str(nullable: bool = False) -> dict[str, object]:
    return {"type": ["string", "null"]} if nullable else {"type": "string"}


def _bool() -> dict[str, object]:
    return {"type": "boolean"}


def _int() -> dict[str, object]:
    return {"type": "integer"}


def _array(items: Mapping[str, object]) -> dict[str, object]:
    return {"type": "array", "items": dict(items)}


def operation_definitions(*, include_publication: bool = False) -> tuple[RegisteredOperation, ...]:
    line_edit = _object_schema(
        {"start_line": _int(), "end_line": _int(), "replacement": _str()},
        ("start_line", "end_line", "replacement"),
    )
    expectation = {
        "type": "string",
        "enum": [
            "RESULT_PRESENT", "AUDIT_PRESENT", "EFFECT_RECEIPT_PRESENT",
            "EXIT_ZERO", "NO_SECURITY_BLOCK", "RESTORE_EQUIVALENT",
        ],
    }
    any_object = _object_schema({})
    specs = (
        ("filesystem_read", "FILE_READ", "READ", "READ_ONLY",
         _object_schema({"path": _str(), "encoding": _str(), "max_bytes": _int()}, ("path",)), any_object),
        ("filesystem_write", "FILE_WRITE", "WRITE", "STATE_CHANGING",
         _object_schema({"path": _str(), "content": _str(), "expected_absent": _bool(), "expected_sha256": _str(True)}, ("path", "content")), any_object),
        ("filesystem_patch", "FILE_WRITE", "WRITE", "STATE_CHANGING",
         _object_schema({"path": _str(), "base_sha256": _str(), "edits": _array(line_edit), "final_newline": {"type": ["boolean", "null"]}}, ("path", "base_sha256", "edits")), any_object),
        ("filesystem_search", "SEARCH", "SEARCH", "READ_ONLY",
         _object_schema({"root": _str(), "query": _str(), "mode": _str(), "glob": _str(), "max_matches": _int(), "max_file_bytes": _int()}, ("query",)), any_object),
        ("filesystem_metadata", "FILE_READ", "READ", "READ_ONLY",
         _object_schema({"path": _str(), "include_sha256": _bool()}, ("path",)), any_object),
        ("shell_execute", "SHELL", "EXECUTE", "STATE_CHANGING",
         _object_schema({"argv": _array(_str()), "cwd": _str(), "timeout_seconds": _int(), "stdin": _str(True), "env": {"type": "object"}}, ("argv", "cwd", "timeout_seconds")), any_object),
        ("git_status", "GIT", "READ", "READ_ONLY", _object_schema({"paths": _array(_str())}), any_object),
        ("git_diff", "GIT", "READ", "READ_ONLY",
         _object_schema({"paths": _array(_str()), "base_ref": _str(True), "target_ref": _str(True), "cached": _bool(), "context_lines": _int(), "max_bytes": _int()}), any_object),
        ("git_branch", "GIT", "READ", "READ_ONLY", _object_schema({}), any_object),
        ("git_restore", "GIT", "WRITE", "STATE_CHANGING",
         _object_schema({"paths": _array(_str()), "source_ref": _str()}, ("paths", "source_ref")), any_object),
        ("git_prepare_commit", "GIT", "READ", "READ_ONLY",
         _object_schema({"paths": _array(_str()), "subject": _str()}, ("paths", "subject")), any_object),
        ("validation_execute", "TEST", "VALIDATE", "STATE_CHANGING",
         _object_schema({"profile_id": _str()}, ("profile_id",)), any_object),
        ("execution_status", "OTHER", "READ", "READ_ONLY",
         _object_schema({"operation_request_id": _str()}, ("operation_request_id",)), any_object),
        ("validate", "OTHER", "VALIDATE", "READ_ONLY",
         _object_schema({"operation_request_id": _str(), "expectations": _array(expectation)}, ("operation_request_id", "expectations")), any_object),
    )
    if include_publication:
        specs += (
            ("git_stage", "GIT", "WRITE", "STATE_CHANGING",
             _object_schema({
                 "intent_schema_version": _str(), "paths": _array(_str()),
                 "expected_worktree_digest": _str(), "expected_head": _str(),
                 "candidate_diff_digest": _str(), "publication_policy_digest": _str(),
             }, ("intent_schema_version", "paths", "expected_worktree_digest", "expected_head",
                 "candidate_diff_digest", "publication_policy_digest")), any_object),
            ("git_commit", "GIT", "WRITE", "STATE_CHANGING",
             _object_schema({
                 "intent_schema_version": _str(), "expected_staged_diff_digest": _str(),
                 "expected_index_digest": _str(), "expected_head": _str(), "expected_parent": _str(),
                 "subject": _str(), "publication_policy_digest": _str(),
             }, ("intent_schema_version", "expected_staged_diff_digest", "expected_index_digest",
                 "expected_head", "expected_parent", "subject", "publication_policy_digest")), any_object),
            ("git_push", "GIT", "WRITE", "STATE_CHANGING",
             _object_schema({
                 "intent_schema_version": _str(), "remote": _str(), "branch": _str(),
                 "local_commit_sha": _str(), "expected_remote_head": _str(),
                 "publication_policy_digest": _str(),
             }, ("intent_schema_version", "remote", "branch", "local_commit_sha",
                 "expected_remote_head", "publication_policy_digest")), any_object),
        )
    return tuple(
        RegisteredOperation(
            operation_registration_id=f"REG-{name.upper().replace('_', '-')}",
            operation_class_id=name,
            capability_class=capability,
            operation_intent=intent,
            effect_class=effect,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        for name, capability, intent, effect, input_schema, output_schema in specs
    )


def _validate_closed_arguments(operation: RegisteredOperation, arguments: Mapping[str, Any]) -> None:
    if not isinstance(arguments, Mapping):
        raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "SCHEMA", "tool arguments must be an object")
    properties = operation.input_schema.get("properties", {})
    required = operation.input_schema.get("required", [])
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise FullMCPRuntimeError("INTERNAL_ERROR", "SCHEMA", "registered schema is malformed")
    if any(key not in arguments for key in required) or any(key not in properties for key in arguments):
        raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "SCHEMA", "tool arguments violate the closed schema")


@dataclass(slots=True)
class RuntimeServices:
    filesystem: FilesystemService
    process: ProcessService
    git: GitService
    validation: ValidationService
    observability: ObservabilityStore
    effects: ToolEffectJournal


class FullMCPRuntime:
    def __init__(
        self,
        *,
        context: InvocationContext,
        contracts: Sequence[ToolAuthorizationContract],
        registry: FullMCPOperationRegistry,
        services: RuntimeServices,
        publication_authorizations: Sequence[GitPublicationAuthorizationV1] = (),
    ) -> None:
        validated = validate_contract_set(context, contracts)
        self.context = context
        self.contracts = {contract.operation_class_id: contract for contract in validated}
        self.registry = registry
        self.services = services
        authorizations = tuple(publication_authorizations)
        if authorizations and context.schema_version != INVOCATION_CONTEXT_SCHEMA_V2:
            raise FullMCPAuthorizationError("publication authority requires InvocationContext.v2")
        self.publication_authorizations: dict[str, GitPublicationAuthorizationV1] = {}
        for authorization in authorizations:
            digest = authorization.policy_digest
            if digest in self.publication_authorizations:
                raise FullMCPAuthorizationError("duplicate publication policy digest")
            if digest not in context.operation_policy_digests:
                raise FullMCPAuthorizationError("publication policy is not invocation-bound")
            self.publication_authorizations[digest] = authorization
        self.replay_guard = OperationRequestReplayGuard()
        registered = {item["name"] for item in registry.dynamic_specs()}
        if registered != set(self.contracts):
            raise FullMCPAuthorizationError("closed registry and active authorization contract set differ")

    def tool_specs(self) -> list[dict[str, object]]:
        return self.registry.dynamic_specs()

    def _preflight_state_change(self, operation_name: str, arguments: Mapping[str, Any]) -> None:
        try:
            if operation_name in {"filesystem_write", "filesystem_patch"}:
                self.services.filesystem.policy.resolve_mutable(arguments.get("path"))
            elif operation_name == "shell_execute":
                cwd = arguments.get("cwd")
                if not isinstance(cwd, str):
                    raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "POLICY", "shell cwd is invalid")
                target = self.services.process.path_policy.resolve_read(cwd)
                if not target.is_dir() or target.is_symlink():
                    raise FullMCPRuntimeError("PATH_POLICY_VIOLATION", "POLICY", "shell cwd is unsafe")
                argv = arguments.get("argv")
                self.services.process.shell_policy.validate_argv(argv)
                env = arguments.get("env", {})
                self.services.process.shell_policy.build_env(env)
            elif operation_name == "git_restore":
                paths = arguments.get("paths")
                if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence) or not paths:
                    raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "POLICY", "restore paths are invalid")
                for path in paths:
                    self.services.git.path_policy.resolve_mutable(path)
            elif operation_name in {"git_stage", "git_commit", "git_push"}:
                self._publication_authorization(operation_name, arguments)
                self._publication_intent(operation_name, arguments)
            elif operation_name == "validation_execute":
                profile_id = arguments.get("profile_id")
                if not isinstance(profile_id, str):
                    raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "POLICY", "profile id is invalid")
                profile = self.services.validation.catalog.get(profile_id)
                if profile.profile_digest not in self.context.validation_profile_digests:
                    raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "validation profile is not invocation-bound")
        except FullMCPRuntimeError:
            raise
        except (PathPolicyError, ProcessServiceError, ValidationProfileError) as exc:
            code = getattr(exc, "code", "PATH_POLICY_VIOLATION")
            raise FullMCPRuntimeError(code, "POLICY", "state-changing operation policy preflight failed") from exc

    def _publication_authorization(self, operation_name: str, arguments: Mapping[str, Any]) -> GitPublicationAuthorizationV1:
        if self.context.schema_version != INVOCATION_CONTEXT_SCHEMA_V2:
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication requires InvocationContext.v2")
        digest = arguments.get("publication_policy_digest")
        if not isinstance(digest, str) or digest not in self.context.operation_policy_digests:
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication policy is not invocation-bound")
        authorization = self.publication_authorizations.get(digest)
        if authorization is None or authorization.policy_digest != digest:
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication authorization is unavailable")
        if operation_name not in authorization.operations:
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication operation is not authorized")
        try:
            issued = datetime.fromisoformat(authorization.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(authorization.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication time binding is invalid") from exc
        now = datetime.now(timezone.utc)
        if issued.tzinfo is None or expires.tzinfo is None or not (issued <= now < expires):
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication authorization is outside its validity window")
        if not authorization.protected_branch_policy_ref.startswith("ALLOW-"):
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "protected-branch policy does not authorize publication")
        if authorization.repository_identity_digest != self.services.git.repository_identity_digest():
            raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "repository identity binding mismatch")
        branch = self.services.git.branch()
        if branch["detached"] or branch["branch"] != authorization.approved_branch:
            raise FullMCPRuntimeError("GIT_BRANCH_MISMATCH", "POLICY", "approved branch binding mismatch")
        if operation_name == "git_stage":
            paths = arguments.get("paths")
            if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence) or not paths:
                raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "POLICY", "publication paths are invalid")
            if scope_digest(tuple(str(item) for item in paths)) != authorization.allowed_path_digest:
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "publication path digest mismatch")
        elif operation_name == "git_commit":
            staged = self.services.git.publication_staged_paths()
            if not staged or scope_digest(tuple(staged)) != authorization.allowed_path_digest:
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "staged publication scope mismatch")
        elif operation_name == "git_push":
            if arguments.get("remote") != authorization.approved_remote or arguments.get("branch") != authorization.approved_branch:
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "push remote/branch binding mismatch")
            if arguments.get("expected_remote_head") != authorization.expected_remote_head:
                raise FullMCPRuntimeError("GIT_REMOTE_STALE", "POLICY", "push freshness binding mismatch")
            if self.services.git.remote_url_fingerprint(authorization.approved_remote) != authorization.remote_url_fingerprint:
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "POLICY", "remote URL fingerprint mismatch")
        return authorization

    def _publication_intent(self, operation_name: str, arguments: Mapping[str, Any]) -> object:
        if operation_name == "git_stage":
            return GitStageIntentV1(
                schema_version=str(arguments.get("intent_schema_version", "")),
                paths=tuple(arguments.get("paths", ())),
                expected_worktree_digest=str(arguments.get("expected_worktree_digest", "")),
                expected_head=str(arguments.get("expected_head", "")),
                candidate_diff_digest=str(arguments.get("candidate_diff_digest", "")),
                publication_policy_digest=str(arguments.get("publication_policy_digest", "")),
            )
        if operation_name == "git_commit":
            return GitCommitIntentV1(
                schema_version=str(arguments.get("intent_schema_version", "")),
                expected_staged_diff_digest=str(arguments.get("expected_staged_diff_digest", "")),
                expected_index_digest=str(arguments.get("expected_index_digest", "")),
                expected_head=str(arguments.get("expected_head", "")),
                expected_parent=str(arguments.get("expected_parent", "")),
                subject=str(arguments.get("subject", "")),
                publication_policy_digest=str(arguments.get("publication_policy_digest", "")),
            )
        if operation_name == "git_push":
            return GitPushIntentV1(
                schema_version=str(arguments.get("intent_schema_version", "")),
                remote=str(arguments.get("remote", "")), branch=str(arguments.get("branch", "")),
                local_commit_sha=str(arguments.get("local_commit_sha", "")),
                expected_remote_head=str(arguments.get("expected_remote_head", "")),
                publication_policy_digest=str(arguments.get("publication_policy_digest", "")),
            )
        raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "POLICY", "unknown publication operation")

    def _identity(self, operation: RegisteredOperation, binding: MCPMetaBinding, contract: ToolAuthorizationContract) -> OperationIdentity:
        return OperationIdentity(
            operation_registration_id=operation.operation_registration_id,
            operation_dispatch_id=f"DISPATCH-{binding.operation_request_id}",
            operation_callsite_id="FULL-MCP-STDIO",
            operation_class_id=operation.operation_class_id,
            worker_task_id=contract.worker_task_id,
            worker_action_id=binding.operation_request_id,
            project_id=self.context.project_id,
            gate_id=self.context.gate_id,
            lv_id=self.context.lv_id,
            run_id=self.context.run_id,
            plan_digest=self.context.canonical_plan_sha256,
            requirement_digest=contract.requirement_digest,
            package_digest=self.context.dependency_lock_sha256,
            owned_scope_sha256=self.context.mutable_scope_sha256,
        )

    def _dispatch(self, operation_name: str, arguments: Mapping[str, Any]) -> tuple[dict[str, object], int | None, str | None, str | None]:
        if operation_name == "filesystem_read":
            data = self.services.filesystem.read(
                arguments["path"], encoding=arguments.get("encoding", "utf-8"), max_bytes=arguments.get("max_bytes", 1048576)
            )
            return data, None, None, None
        if operation_name == "filesystem_write":
            data = self.services.filesystem.write(
                arguments["path"], arguments["content"], expected_absent=arguments.get("expected_absent", False),
                expected_sha256=arguments.get("expected_sha256")
            )
            return data, None, None, None
        if operation_name == "filesystem_patch":
            data = self.services.filesystem.patch(
                arguments["path"], base_sha256=arguments["base_sha256"], edits=arguments["edits"],
                final_newline=arguments.get("final_newline")
            )
            return data, None, None, None
        if operation_name == "filesystem_search":
            data = self.services.filesystem.search(
                root=arguments.get("root", "."), query=arguments["query"], mode=arguments.get("mode", "LITERAL"),
                glob=arguments.get("glob", "**/*"), max_matches=arguments.get("max_matches", 200),
                max_file_bytes=arguments.get("max_file_bytes", 1048576)
            )
            return data, None, None, None
        if operation_name == "filesystem_metadata":
            data = self.services.filesystem.metadata(arguments["path"], include_sha256=arguments.get("include_sha256", True))
            return data, None, None, None
        if operation_name == "shell_execute":
            data = self.services.process.execute(
                argv=arguments["argv"], cwd=arguments["cwd"], timeout_seconds=arguments["timeout_seconds"],
                stdin=arguments.get("stdin"), env=arguments.get("env", {})
            )
            if data["timed_out"]:
                raise FullMCPRuntimeError("PROCESS_TIMEOUT", "EXECUTE", "process timed out", retryable=False)
            if data["cancelled"]:
                raise FullMCPRuntimeError("PROCESS_CANCELLED", "EXECUTE", "process was cancelled", retryable=False)
            if data["exit_code"] != 0:
                raise FullMCPRuntimeError("NONZERO_EXIT", "EXECUTE", "process returned nonzero", retryable=False)
            return data, int(data["exit_code"]), str(data["stdout"]), str(data["stderr"])
        if operation_name == "git_status":
            return self.services.git.status(arguments.get("paths", ())), None, None, None
        if operation_name == "git_diff":
            return self.services.git.diff(
                arguments.get("paths", ()), base_ref=arguments.get("base_ref"), target_ref=arguments.get("target_ref"),
                cached=arguments.get("cached", False), context_lines=arguments.get("context_lines", 3),
                max_bytes=arguments.get("max_bytes", 1048576)
            ), None, None, None
        if operation_name == "git_branch":
            return self.services.git.branch(), None, None, None
        if operation_name == "git_restore":
            return self.services.git.restore(arguments["paths"], source_ref=arguments["source_ref"]), None, None, None
        if operation_name == "git_prepare_commit":
            return self.services.git.prepare_commit(arguments["paths"], subject=arguments["subject"]), None, None, None
        if operation_name == "git_stage":
            data = self.services.git.stage_publication(
                arguments["paths"], expected_worktree_digest=arguments["expected_worktree_digest"],
                expected_head=arguments["expected_head"], candidate_diff_digest=arguments["candidate_diff_digest"],
            )
            data["publication_evidence"] = seal_publication_evidence(
                "git_stage", arguments["publication_policy_digest"], data
            )
            return data, None, None, None
        if operation_name == "git_commit":
            data = self.services.git.commit_publication(
                expected_staged_diff_digest=arguments["expected_staged_diff_digest"],
                expected_index_digest=arguments["expected_index_digest"], expected_head=arguments["expected_head"],
                expected_parent=arguments["expected_parent"], subject=arguments["subject"],
            )
            data["publication_evidence"] = seal_publication_evidence(
                "git_commit", arguments["publication_policy_digest"], data
            )
            return data, None, None, None
        if operation_name == "git_push":
            data = self.services.git.push_publication(
                remote=arguments["remote"], branch=arguments["branch"],
                local_commit_sha=arguments["local_commit_sha"], expected_remote_head=arguments["expected_remote_head"],
            )
            data["publication_evidence"] = seal_publication_evidence(
                "git_push", arguments["publication_policy_digest"], data
            )
            return data, None, None, None
        if operation_name == "validation_execute":
            data = self.services.validation.execute(arguments["profile_id"])
            if data["exit_code"] != 0:
                raise FullMCPRuntimeError("VALIDATION_FAILED", "VALIDATE", "validation profile failed", retryable=False)
            return data, int(data["exit_code"]), str(data["stdout"]), str(data["stderr"])
        if operation_name == "execution_status":
            return self.services.validation.execution_status(arguments["operation_request_id"]), None, None, None
        if operation_name == "validate":
            return self.services.validation.validate(arguments["operation_request_id"], arguments["expectations"]), None, None, None
        raise FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "DISPATCH", "unknown operation")

    def call(self, operation_name: str, arguments: Mapping[str, Any] | None, meta: Mapping[str, Any]) -> dict[str, object]:
        started_wall = _utc_now()
        started_mono = time.monotonic_ns()
        binding: MCPMetaBinding | None = None
        operation: RegisteredOperation | None = None
        effect_id: str | None = None
        try:
            binding = MCPMetaBinding.from_meta(meta)
            binding.bind_to(self.context)
            operation = self.registry.resolve(operation_name)
            args = {} if arguments is None else arguments
            _validate_closed_arguments(operation, args)
            contract = self.contracts.get(operation_name)
            if contract is None:
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "AUTHORIZATION", "active contract is missing")
            resolved = self.registry.resolve_for_contract(operation_name, contract)
            auth = authorize_registered_operation(
                context=self.context, binding=binding, contract=contract, operation=resolved,
                worker_task_id=contract.worker_task_id, worker_action_id=binding.operation_request_id,
            )
            if auth.get("authorization_status") != "AUTHORIZED":
                raise FullMCPRuntimeError("AUTHORIZATION_DENIED", "AUTHORIZATION", "authorization exact-match failed")
            if self.services.observability.status(binding.operation_request_id) is not None:
                raise FullMCPRuntimeError("EFFECT_REPLAY_BLOCKED", "AUTHORIZATION", "operation request replay blocked")
            self.replay_guard.consume(binding, self.context)
            if operation.effect_class == "STATE_CHANGING":
                self._preflight_state_change(operation_name, args)
                identity = self._identity(operation, binding, contract)
                try:
                    effect_id = self.services.effects.begin(identity, auth, scope_ref=str(args.get("path", args.get("cwd", ""))))
                except ToolAuthorizationError as exc:
                    raise FullMCPRuntimeError("EFFECT_REPLAY_BLOCKED", "EFFECT_INTENT", "logical effect replay blocked") from exc
                data, exit_code, stdout, stderr = self._dispatch(operation_name, args)
                self.services.effects.complete(identity, execution_status="COMPLETED", security_status="PASS")
            else:
                data, exit_code, stdout, stderr = self._dispatch(operation_name, args)
            return self._finish(
                binding=binding, operation_name=operation_name, started_wall=started_wall, started_mono=started_mono,
                status="COMPLETED", data=data, exit_code=exit_code, stdout=stdout, stderr=stderr,
                effect_id=effect_id, error=None,
            )
        except Exception as exc:
            mapped = self._map_error(exc)
            if binding is None:
                operation_request_id = "invalid-request"
                correlation_id = "invalid-correlation"
            else:
                operation_request_id = binding.operation_request_id
                correlation_id = binding.correlation_id
            synthetic = MCPMetaBinding(
                invocation_context_id=self.context.invocation_context_id,
                request_digest=self.context.request_digest,
                correlation_id=correlation_id,
                operation_request_id=operation_request_id,
            )
            return self._finish(
                binding=synthetic, operation_name=operation_name if isinstance(operation_name, str) else "invalid-operation",
                started_wall=started_wall, started_mono=started_mono,
                status="BLOCKED" if mapped.code in {
                    "AUTHENTICATION_FAILED", "AUTHORIZATION_DENIED", "INPUT_SCHEMA_INVALID", "WORKSPACE_VIOLATION",
                    "PATH_POLICY_VIOLATION", "SYMLINK_VIOLATION", "SENSITIVE_PATH_BLOCKED", "COMMAND_NOT_ALLOWED",
                    "GIT_BOUNDARY_VIOLATION", "GIT_INDEX_NOT_CLEAN", "GIT_HEAD_DRIFT",
                    "GIT_WORKTREE_DRIFT", "GIT_CANDIDATE_DRIFT", "GIT_INDEX_DRIFT",
                    "GIT_BRANCH_MISMATCH", "GIT_REMOTE_STALE", "GIT_NON_FAST_FORWARD",
                    "GIT_PUSH_REJECTED", "GIT_REMOTE_HEAD_UNAVAILABLE",
                    "EFFECT_REPLAY_BLOCKED", "RECOVERY_AMBIGUOUS",
                } else "FAILED",
                data=None, exit_code=None, stdout=None, stderr=None, effect_id=effect_id,
                error={"code": mapped.code, "stage": mapped.stage, "retryable": mapped.retryable},
            )

    def _map_error(self, exc: Exception) -> FullMCPRuntimeError:
        if isinstance(exc, FullMCPRuntimeError):
            return exc
        if isinstance(exc, (FullMCPContractError, FullMCPAuthorizationError)):
            return FullMCPRuntimeError("AUTHORIZATION_DENIED", "AUTHORIZATION", "request authorization failed")
        if isinstance(exc, OperationRegistryError):
            return FullMCPRuntimeError("INPUT_SCHEMA_INVALID", "REGISTRY", "unknown or invalid operation")
        if isinstance(exc, PathPolicyError):
            return FullMCPRuntimeError("PATH_POLICY_VIOLATION", "POLICY", "path policy rejected request")
        if isinstance(exc, FilesystemServiceError):
            return FullMCPRuntimeError(exc.code, "FILESYSTEM", "filesystem operation failed")
        if isinstance(exc, ProcessServiceError):
            return FullMCPRuntimeError(exc.code, "PROCESS", "process operation failed")
        if isinstance(exc, GitServiceError):
            return FullMCPRuntimeError(exc.code, "GIT", "git operation failed")
        if isinstance(exc, ValidationServiceError):
            return FullMCPRuntimeError(exc.code, "VALIDATION", "validation operation failed")
        if isinstance(exc, ObservabilityError):
            return FullMCPRuntimeError("PERSISTENCE_FAILED", "OBSERVABILITY", "observability persistence failed")
        if isinstance(exc, ToolAuthorizationError):
            return FullMCPRuntimeError("RECOVERY_AMBIGUOUS", "EFFECT", "effect state requires recovery")
        return FullMCPRuntimeError("INTERNAL_ERROR", "RUNTIME", "unexpected runtime failure")

    def _finish(
        self, *, binding: MCPMetaBinding, operation_name: str, started_wall: str, started_mono: int,
        status: str, data: dict[str, object] | None, exit_code: int | None, stdout: str | None,
        stderr: str | None, effect_id: str | None, error: dict[str, object] | None,
    ) -> dict[str, object]:
        ended_wall = _utc_now()
        duration_ms = max(0, (time.monotonic_ns() - started_mono) // 1_000_000)
        state = "RESULT_SEALED" if status == "COMPLETED" else status
        try:
            event = self.services.observability.append_event(
                operation_request_id=binding.operation_request_id,
                correlation_id=binding.correlation_id,
                operation=operation_name,
                state=state,
                effect_id=effect_id,
                error_code=None if error is None else str(error["code"]),
            )
            existing = self.services.observability.status(binding.operation_request_id)
            if (
                existing is not None
                and status == "BLOCKED"
                and error is not None
                and error.get("code") == "EFFECT_REPLAY_BLOCKED"
            ):
                audit_ref = str(event["audit_ref"])
                result_digest = canonical_sha256({
                    "schema_version": "gch.full-mcp.replay-block.v1",
                    "operation_request_id": binding.operation_request_id,
                    "correlation_id": binding.correlation_id,
                    "operation": operation_name,
                    "status": status,
                    "audit_ref": audit_ref,
                    "existing_result_digest": existing.get("result_digest"),
                    "error_code": error.get("code"),
                })
            else:
                terminal = self.services.observability.seal_result(
                    operation_request_id=binding.operation_request_id,
                    correlation_id=binding.correlation_id,
                    operation=operation_name,
                    state=status,
                    started_at=started_wall,
                    ended_at=ended_wall,
                    audit_ref=str(event["audit_ref"]),
                    effect_id=effect_id,
                    error_code=None if error is None else str(error["code"]),
                    exit_code=exit_code,
                    security_block=status == "BLOCKED",
                    restore_equivalent=False,
                )
                audit_ref = str(event["audit_ref"])
                result_digest = str(terminal["result_digest"])
        except ObservabilityError:
            audit_ref = ""
            result_digest = "0" * 64
            status = "FAILED"
            data = None
            exit_code = None
            stdout = None
            stderr = None
            error = {"code": "PERSISTENCE_FAILED", "stage": "OBSERVABILITY", "retryable": False}
        return {
            "schema_version": RESULT_SCHEMA,
            "operation_request_id": binding.operation_request_id,
            "correlation_id": binding.correlation_id,
            "operation": operation_name,
            "status": status,
            "started_at": started_wall,
            "ended_at": ended_wall,
            "duration_ms": int(duration_ms),
            "data": data,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "result_digest": result_digest,
            "audit_ref": audit_ref,
            "effect_id": effect_id,
            "error": error,
        }


def build_default_runtime(
    context: InvocationContext,
    contracts: Sequence[ToolAuthorizationContract],
    *,
    catalog: ValidationProfileCatalog | None = None,
    shell_policy: ShellPolicy | None = None,
    publication_authorizations: Sequence[GitPublicationAuthorizationV1] = (),
) -> FullMCPRuntime:
    workspace_root = Path(context.workspace_root)
    path_policy = WorkspacePathPolicy(
        workspace_root,
        read_scopes=context.read_scopes,
        mutable_scopes=context.mutable_scopes,
    )
    filesystem = FilesystemService(path_policy)
    process = ProcessService(path_policy, shell_policy=shell_policy or ShellPolicy())
    git = GitService(workspace_root, path_policy)
    observability = ObservabilityStore(workspace_root, context.run_id)
    effects = ToolEffectJournal(workspace_root / "_workspace" / "full-mcp" / context.run_id / "effects")
    selected_catalog = catalog or default_validation_catalog()
    validation = ValidationService(
        context,
        selected_catalog,
        process,
        status_provider=observability.status,
    )
    services = RuntimeServices(
        filesystem=filesystem,
        process=process,
        git=git,
        validation=validation,
        observability=observability,
        effects=effects,
    )
    return FullMCPRuntime(
        context=context,
        contracts=contracts,
        registry=FullMCPOperationRegistry(operation_definitions(include_publication=bool(publication_authorizations))),
        services=services,
        publication_authorizations=publication_authorizations,
    )

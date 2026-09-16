from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from runtime.orchestrator.tool_authorization import (
    TOOL_AUTH_CONTRACT_VERSION,
    RegisteredOperation,
    ToolAuthorizationContract,
    owned_scope_digest,
)
from runtime.full_mcp.authorization import (
    FullMCPAuthorizationError,
    OneShotContextReader,
    OperationRequestReplayGuard,
    authorize_registered_operation,
    build_context_payload,
    validate_contract_set,
)
from runtime.full_mcp.contracts import (
    FullMCPContractError,
    InvocationContext,
    MCPMetaBinding,
    scope_digest,
)
from runtime.full_mcp.operation_registry import FullMCPOperationRegistry, OperationRegistryError
from runtime.full_mcp.path_policy import PathPolicyError, WorkspacePathPolicy

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
def active_contract(*, operation_class_id: str = "TEST_READ") -> ToolAuthorizationContract:
    owned = owned_scope_digest(["owned"])
    return ToolAuthorizationContract(
        contract_id="TAC-TEST-READ", contract_version=TOOL_AUTH_CONTRACT_VERSION,
        contract_status="ACTIVE", worker_task_id="TASK-TEST",
        requirement_refs=("REQ-002",), plan_task_refs=("TASK-TEST",),
        operation_class_id=operation_class_id, capability_class="FILE_READ", operation_intent="READ",
        requirement_binding="REQUIRED", scope_binding="IN_SCOPE",
        scope_authorization_source="USER_DECISION", authorization_decision_ref="DEC-TEST",
        validity_scope="TASK_ONLY", security_obligation_profile="SECRET_SCAN_REQUIRED",
        approval_authority="USER_DECISION", project_id="GH-FULL-MCP-PH4",
        gate_id="GATE-002", lv_id="LV-TEST", run_id="run-test",
        canonical_plan_sha256=SHA_A, requirement_digest=SHA_B,
        owned_scope_sha256=owned, package_binding_sha256=SHA_B,
    ).sealed()


def context(contract: ToolAuthorizationContract) -> InvocationContext:
    mutable = ("owned",)
    return InvocationContext(
        schema_version="gch.full-mcp.invocation-context.v1",
        project_id="GH-FULL-MCP-PH4", run_id="run-test", gate_id="GATE-002",
        lv_id="LV-TEST", attempt=1, request_digest=SHA_C,
        correlation_id="corr-test", workspace_root="/workspace/GH-FULL-MCP-PH4",
        canonical_plan_sha256=SHA_A,
        dependency_lock_sha256=SHA_B, authorization_contract_digests=(contract.contract_digest,),
        read_scopes=(".",), mutable_scopes=mutable, read_scope_sha256=scope_digest((".",)),
        mutable_scope_sha256=scope_digest(mutable), validation_profile_digests=(),
    ).sealed()
def operation() -> RegisteredOperation:
    return RegisteredOperation(
        operation_registration_id="REG-TEST-READ", operation_class_id="TEST_READ",
        capability_class="FILE_READ", operation_intent="READ", effect_class="READ_ONLY",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"], "additionalProperties": False},
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                       "required": ["ok"], "additionalProperties": False},
    )


def meta(ctx: InvocationContext, operation_request_id: str = "op-1") -> MCPMetaBinding:
    return MCPMetaBinding(
        invocation_context_id=ctx.invocation_context_id,
        request_digest=ctx.request_digest,
        correlation_id=ctx.correlation_id,
        operation_request_id=operation_request_id,
    )


class FoundationAuthenticationTests(unittest.TestCase):
    def test_context_is_immutable_and_digest_bound(self) -> None:
        contract = active_contract()
        ctx = context(contract)
        self.assertEqual(validate_contract_set(ctx, [contract]), (contract,))
        with self.assertRaises(FrozenInstanceError):
            ctx.run_id = "changed"  # type: ignore[misc]
        broken = replace(ctx, request_digest=SHA_A)
        with self.assertRaises(ValueError):
            validate_contract_set(broken, [contract])
    def test_one_shot_context_fd_digest_and_replay_guard(self) -> None:
        contract = active_contract()
        ctx = context(contract)
        raw, digest = build_context_payload(ctx)
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, raw)
        finally:
            os.close(write_fd)
        reader = OneShotContextReader(read_fd, digest)
        self.assertEqual(reader.read_once(), ctx)
        with self.assertRaises(FullMCPAuthorizationError):
            reader.read_once()

    def test_context_fd_digest_mismatch_fails_closed(self) -> None:
        ctx = context(active_contract())
        raw, _ = build_context_payload(ctx)
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, raw)
        finally:
            os.close(write_fd)
        with self.assertRaises(FullMCPAuthorizationError):
            OneShotContextReader(read_fd, "0" * 64).read_once()

    def test_dependency_lock_package_binding_mismatch_fails_closed(self) -> None:
        contract = active_contract()
        mismatched = replace(
            contract, package_binding_sha256=SHA_C, contract_digest=""
        ).sealed()
        ctx = context(mismatched)
        with self.assertRaises(FullMCPAuthorizationError):
            validate_contract_set(ctx, [mismatched])

    def test_metadata_requires_exact_string_values_and_context_binding(self) -> None:
        ctx = context(active_contract())
        raw_meta = {
            "gch/full-mcp/invocation_context_id": ctx.invocation_context_id,
            "gch/full-mcp/request_digest": ctx.request_digest,
            "gch/full-mcp/correlation_id": 123,
            "gch/full-mcp/operation_request_id": "op-typed",
        }
        with self.assertRaises(FullMCPContractError):
            MCPMetaBinding.from_meta(raw_meta)
        with self.assertRaises(FullMCPContractError):
            replace(meta(ctx, "op-mismatch"), correlation_id="other-corr").bind_to(ctx)

    def test_metadata_and_operation_replay_binding(self) -> None:
        ctx = context(active_contract())
        guard = OperationRequestReplayGuard()
        binding = meta(ctx)
        guard.consume(binding, ctx)
        with self.assertRaises(FullMCPAuthorizationError):
            guard.consume(binding, ctx)
    def test_preserved_authorization_exact_match_and_registry(self) -> None:
        contract = active_contract()
        ctx = context(contract)
        op = operation()
        registry = FullMCPOperationRegistry([op])
        self.assertEqual(registry.resolve_for_contract("TEST_READ", contract), op)
        result = authorize_registered_operation(
            context=ctx, binding=meta(ctx), contract=contract, operation=op,
            worker_task_id="TASK-TEST", worker_action_id="ACTION-1",
        )
        self.assertEqual(result["authorization_status"], "AUTHORIZED")
        blocked = authorize_registered_operation(
            context=ctx, binding=meta(ctx, "op-2"), contract=contract, operation=op,
            worker_task_id="OTHER-TASK", worker_action_id="ACTION-2",
        )
        self.assertEqual(blocked["authorization_status"], "BLOCK")
        with self.assertRaises(OperationRegistryError):
            registry.resolve("UNKNOWN")

    def test_duplicate_registry_operation_is_rejected(self) -> None:
        op = operation()
        with self.assertRaises(OperationRegistryError):
            FullMCPOperationRegistry([op, op])
class PathPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "read").mkdir()
        (self.root / "owned").mkdir()
        (self.root / "sensitive").mkdir()
        (self.root / "read/file.txt").write_text("ok", encoding="utf-8")
        (self.root / "sensitive/.env").write_text("SECRET=x", encoding="utf-8")
        (self.root / "read/link").symlink_to("/etc/passwd")
        self.policy = WorkspacePathPolicy(
            self.root, read_scopes=(".",), mutable_scopes=("owned",),
            read_only_exceptions=("sensitive/.env",),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_allowed_read_and_mutable_targets(self) -> None:
        self.assertEqual(self.policy.resolve_read("read/file.txt"), self.root / "read/file.txt")
        self.assertEqual(self.policy.resolve_mutable("owned/new.txt"), self.root / "owned/new.txt")
        self.assertEqual(self.policy.classify("owned/new.txt"), "MUTABLE")

    def test_traversal_absolute_and_symlink_escape_are_blocked(self) -> None:
        (self.root / "read/linkdir").symlink_to("/etc", target_is_directory=True)
        for target in ("../outside", "/etc/passwd", "read/link", "read/linkdir/passwd"):
            with self.subTest(target=target), self.assertRaises(PathPolicyError):
                self.policy.resolve_read(target)

    def test_sensitive_paths_fail_closed_except_explicit_read_only_exception(self) -> None:
        self.assertEqual(
            self.policy.resolve_read("sensitive/.env"), self.root / "sensitive/.env"
        )
        for target in ("owned/.env", "owned/.git/config", "owned/token.json",
                       "owned/credentials-prod.json", "owned/secret_key"):
            with self.subTest(target=target), self.assertRaises(PathPolicyError):
                self.policy.resolve_mutable(target)
        for target in ("owned/token.json", "owned/credentials-prod.json"):
            with self.subTest(target=target), self.assertRaises(PathPolicyError):
                self.policy.resolve_read(target)

    def test_mutation_outside_owned_scope_is_blocked(self) -> None:
        with self.assertRaises(PathPolicyError):
            self.policy.resolve_mutable("read/file.txt")

    def test_noncanonical_workspace_root_is_rejected(self) -> None:
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(PathPolicyError):
            WorkspacePathPolicy(alias, read_scopes=(".",), mutable_scopes=("owned",))

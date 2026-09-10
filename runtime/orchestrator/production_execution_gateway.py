"""Explicit execution gateway contract for HOST-side production workers.

The first implementation is deliberately transport-neutral.  A host runner can be
injected for local compatibility tests; production without a configured host
transport fails closed instead of falling back to the nested child backend.
"""
from __future__ import annotations
import re

import hashlib
import base64
import json
import os
import socket
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .codex_dynamic_transport import PINNED_CODEX_VERSION, TRANSPORT_CONTRACT_VERSION
from .lv_execution_package import canonical_json_bytes
from .tool_authorization import (
    DEC007_CONTRACT_IDS, DEC007_DECISION_REF, DEC007_WORKER_TASK_ID,
    ToolAuthorizationContract, ToolAuthorizationError, owned_scope_digest, validate_contract,
)

GATEWAY_CONTRACT_VERSION = "HOST-GATEWAY.v1"
LOCAL_CHILD = "LOCAL_CHILD"
HOST_GATEWAY = "HOST_GATEWAY"
SUPPORTED_BACKENDS = frozenset({LOCAL_CHILD, HOST_GATEWAY})
AF_UNIX_PATH_LIMIT = 108


class GatewayError(ValueError):
    """Contract, transport, or binding failure; all are fail-closed."""


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _request_id(payload: Mapping[str, Any]) -> str:
    seed = "|".join(str(payload.get(key, "")) for key in (
        "project_id", "run_id", "gate_id", "lv_id", "attempt", "package_preflight_binding_digest",
    ))
    return "exec-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _required(payload: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    if not isinstance(payload, Mapping) or any(field not in payload for field in fields):
        raise GatewayError("gateway schema is incomplete")


def resolve_gateway_socket_path(workspace_root: str | Path, endpoint: str) -> Path:
    """Resolve a safe UDS path, shortening only when Linux pathname limits require it."""
    root = Path(workspace_root).resolve()
    relative = Path(endpoint)
    if (not endpoint or relative.is_absolute() or ".." in relative.parts
            or any(ord(char) < 32 for char in endpoint)):
        raise GatewayError("gateway transport endpoint is invalid")
    candidate = root / relative
    if len(os.fsencode(str(candidate))) < AF_UNIX_PATH_LIMIT:
        return candidate
    # Preserve workspace/endpoint binding without putting the long workspace
    # path itself into the AF_UNIX pathname.  The alias remains user-owned and
    # is still protected by the normal socket owner/mode/peer checks.
    seed = f"{root}\0{endpoint}".encode("utf-8")
    alias = hashlib.sha256(seed).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / f"harness-host-gateway-{alias}.sock"


def _workspace_artifact_binding(workspace_root: str | Path, target: str | Path, *,
                                require_parent: bool = True) -> tuple[Path, str]:
    """Bind an artifact to its exact workspace-relative location."""
    root = Path(workspace_root)
    path = Path(target)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or not path.is_absolute():
        raise GatewayError("workspace artifact binding is invalid")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise GatewayError("workspace artifact is outside write scope") from exc
    if not relative.parts or ".." in relative.parts or any(ord(char) < 32 for char in relative.as_posix()):
        raise GatewayError("workspace artifact binding is invalid")
    canonical = root / relative
    try:
        canonical.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise GatewayError("workspace artifact path resolution mismatch") from exc
    if require_parent and (not canonical.parent.is_dir() or canonical.parent.is_symlink()
                           or not os.access(canonical.parent, os.W_OK)):
        raise GatewayError("workspace artifact parent is missing or unwritable")
    if require_parent:
        parent_stat = canonical.parent.stat()
        if parent_stat.st_uid != os.getuid():
            raise GatewayError("workspace artifact parent ownership or mode is unsafe")
    if canonical.exists() and (canonical.is_symlink() or not canonical.is_file()):
        raise GatewayError("workspace artifact target is unsafe")
    return canonical, relative.as_posix()


def build_gateway_request(*, project_id: str, run_id: str, gate_id: str, lv_id: str,
                          attempt: int, workspace_identity: Mapping[str, Any],
                          package_manifest_sha256: str, preflight_evidence_sha256: str,
                          runtime_prompt_artifact: Mapping[str, Any], runtime_prompt_sha256: str,
                          adapter_contract_version: str, structured_event_contract_version: str,
                          execution_backend: str = HOST_GATEWAY,
                          transport_endpoint: str = "runtime/host-gateway.sock",
                          execution_request_id: str | None = None,
                          active_tool_authorization_contracts: list[Mapping[str, Any]] | None = None,
                          owned_files: list[str] | None = None,
                          canonical_plan_sha256: str = "",
                          requirement_digest: str = "",
                          tool_authorization_projection: Mapping[str, Any] | None = None,
                          tool_authorization_projection_sha256: str = "",
                          canonical_authority_binding: Mapping[str, Any] | None = None,
                          canonical_authority_binding_digest: str = "") -> dict[str, Any]:
    if execution_backend not in SUPPORTED_BACKENDS:
        raise GatewayError("unsupported execution backend")
    if not isinstance(attempt, int) or attempt < 1:
        raise GatewayError("gateway attempt is invalid")
    if not all(isinstance(value, str) and value for value in (
        project_id, run_id, gate_id, lv_id, package_manifest_sha256,
        preflight_evidence_sha256, runtime_prompt_sha256,
        adapter_contract_version, structured_event_contract_version,
    )):
        raise GatewayError("gateway identity is incomplete")
    if not isinstance(workspace_identity, Mapping) or not workspace_identity:
        raise GatewayError("workspace identity is missing")
    if not isinstance(runtime_prompt_artifact, Mapping) or not runtime_prompt_artifact:
        raise GatewayError("runtime prompt artifact identity is missing")
    payload = {
        "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
        "execution_request_id": "", "project_id": project_id, "run_id": run_id,
        "gate_id": gate_id, "lv_id": lv_id, "attempt": attempt,
        "workspace_canonical_identity": dict(workspace_identity),
        "package_preflight_binding": {
            "package_manifest_sha256": package_manifest_sha256,
            "preflight_evidence_sha256": preflight_evidence_sha256,
        },
        "runtime_prompt_artifact": dict(runtime_prompt_artifact),
        "runtime_prompt_sha256": runtime_prompt_sha256,
        "adapter_contract_version": adapter_contract_version,
        "structured_event_contract_version": structured_event_contract_version,
        "execution_backend": execution_backend,
        "transport_endpoint": transport_endpoint,
        "transport_compatibility": {
            "codex_version": PINNED_CODEX_VERSION,
            "transport_contract_version": TRANSPORT_CONTRACT_VERSION,
            "experimental_api_required": True,
            "dynamic_tool_request_required": True,
            "native_environment_count": 0,
            "native_command_runtime_count": 0,
            "native_file_runtime_count": 0,
            "direct_mcp_effect_source_count": 0,
        },
        "active_tool_authorization_contracts": [dict(item) for item in (active_tool_authorization_contracts or [])],
        "owned_files": list(owned_files or []),
        "canonical_plan_sha256": canonical_plan_sha256,
        "requirement_digest": requirement_digest,
        "tool_authorization_projection": dict(tool_authorization_projection or {}),
        "tool_authorization_projection_sha256": tool_authorization_projection_sha256,
        "canonical_authority_binding": dict(canonical_authority_binding or {}),
        "canonical_authority_binding_digest": canonical_authority_binding_digest,
    }
    payload["execution_request_id"] = execution_request_id or _request_id(payload)
    payload["request_digest"] = _digest(payload)
    return payload


def validate_gateway_request(payload: Mapping[str, Any], *, expected: Mapping[str, Any] | None = None, require_canonical_authority: bool = False) -> dict[str, Any]:
    fields = ("gateway_contract_version", "execution_request_id", "project_id", "run_id", "gate_id", "lv_id",
              "attempt", "workspace_canonical_identity", "package_preflight_binding", "runtime_prompt_artifact",
              "runtime_prompt_sha256", "adapter_contract_version", "structured_event_contract_version",
              "execution_backend", "request_digest")
    fields = fields + ("transport_endpoint", "transport_compatibility",
                       "active_tool_authorization_contracts", "owned_files")
    fields = fields + ("canonical_plan_sha256", "requirement_digest")
    fields = fields + ("tool_authorization_projection", "tool_authorization_projection_sha256")
    fields = fields + ("canonical_authority_binding", "canonical_authority_binding_digest")
    _required(payload, fields)
    if payload["gateway_contract_version"] != GATEWAY_CONTRACT_VERSION or payload["execution_backend"] not in SUPPORTED_BACKENDS:
        raise GatewayError("gateway request version or backend is invalid")
    if not isinstance(payload["attempt"], int) or payload["attempt"] < 1:
        raise GatewayError("gateway request attempt is invalid")
    request_id = payload.get("execution_request_id")
    if (not isinstance(request_id, str) or not request_id
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in request_id)):
        raise GatewayError("gateway execution request id is unsafe")
    endpoint = payload.get("transport_endpoint")
    if (not isinstance(endpoint, str) or not endpoint or Path(endpoint).is_absolute()
            or ".." in Path(endpoint).parts or any(ord(char) < 32 for char in endpoint)):
        raise GatewayError("gateway transport endpoint is invalid")
    compatibility = payload.get("transport_compatibility")
    if (not isinstance(compatibility, Mapping)
            or compatibility.get("codex_version") != PINNED_CODEX_VERSION
            or compatibility.get("transport_contract_version") != TRANSPORT_CONTRACT_VERSION
            or compatibility.get("experimental_api_required") is not True
            or compatibility.get("dynamic_tool_request_required") is not True
            or any(compatibility.get(field) != 0 for field in (
                "native_environment_count", "native_command_runtime_count",
                "native_file_runtime_count", "direct_mcp_effect_source_count"))):
        raise GatewayError("TRANSPORT_COMPATIBILITY_BLOCK")
    if not isinstance(payload.get("active_tool_authorization_contracts"), list):
        raise GatewayError("sealed authorization projection is malformed")
    owned_files = payload.get("owned_files")
    if (not isinstance(owned_files, list) or any(not isinstance(item, str) or not item for item in owned_files)):
        raise GatewayError("owned file projection is malformed")
    if (not isinstance(payload.get("canonical_plan_sha256"), str)
            or not isinstance(payload.get("requirement_digest"), str)):
        raise GatewayError("plan or requirement binding is malformed")
    canonical_binding = payload.get("canonical_authority_binding")
    canonical_binding_digest = payload.get("canonical_authority_binding_digest")
    if not isinstance(canonical_binding, Mapping) or not isinstance(canonical_binding_digest, str):
        raise GatewayError("canonical authority binding is malformed")
    if canonical_binding or canonical_binding_digest:
        required_canonical_fields = {
            "schema_version",
            "package_ref",
            "package_digest",
            "contract_ref",
            "contract_digest",
            "contract_activation_digest",
            "worker_task_id",
            "criterion_set_digest",
            "execution_obligation",
            "preflight_evidence_digest",
            "codex_auth_readiness_ref",
            "codex_auth_recheck_evidence_ref",
            "launch_authorization_digest",
            "migration_authority_ref",
        }
        if (
            set(canonical_binding) != required_canonical_fields
            or canonical_binding.get("schema_version")
                != "orchestration.canonical-launch-authority.v1"
            or any(
                not isinstance(canonical_binding.get(field), str)
                or not canonical_binding.get(field)
                for field in required_canonical_fields - {"execution_obligation"}
            )
            or canonical_binding.get("execution_obligation")
                not in {"READ_ONLY_EXECUTION", "MUTATION_REQUIRED", "NONE_SATISFIED"}
            or not canonical_binding_digest
            or _digest(canonical_binding) != canonical_binding_digest
        ):
            raise GatewayError("canonical authority binding mismatch")

    projection = payload.get("tool_authorization_projection")
    projection_digest = payload.get("tool_authorization_projection_sha256")
    contracts = payload.get("active_tool_authorization_contracts")
    if require_canonical_authority:
        sha = re.compile(r"[0-9a-f]{64}\Z")
        package_preflight = payload.get("package_preflight_binding")
        if not canonical_binding or not canonical_binding_digest:
            raise GatewayError("CANONICAL_AUTHORITY_REQUIRED")
        if (
            not isinstance(package_preflight, Mapping)
            or not sha.fullmatch(str(package_preflight.get("package_manifest_sha256", "")))
            or not sha.fullmatch(str(package_preflight.get("preflight_evidence_sha256", "")))
        ):
            raise GatewayError("canonical package/preflight binding is malformed")
        if (
            not sha.fullmatch(str(payload.get("canonical_plan_sha256", "")))
            or not sha.fullmatch(str(payload.get("requirement_digest", "")))
        ):
            raise GatewayError("canonical plan/requirement binding is incomplete")
        if (
            not isinstance(projection, Mapping)
            or not projection
            or not isinstance(projection_digest, str)
            or not sha.fullmatch(projection_digest)
            or not isinstance(contracts, list)
            or not contracts
            or not owned_files
        ):
            raise GatewayError("CANONICAL_TOOL_AUTHORITY_REQUIRED")
        digest_fields = (
            "package_digest",
            "contract_digest",
            "contract_activation_digest",
            "criterion_set_digest",
            "preflight_evidence_digest",
            "launch_authorization_digest",
        )
        if any(
            not sha.fullmatch(str(canonical_binding.get(field, "")))
            for field in digest_fields
        ):
            raise GatewayError("canonical authority digest field is invalid")
    if canonical_binding and projection:
        if canonical_binding.get("worker_task_id") != projection.get("worker_task_id"):
            raise GatewayError("canonical authority worker task binding mismatch")
    if projection or contracts:
        if (not isinstance(projection, Mapping) or not isinstance(projection_digest, str)
                or _digest(projection) != projection_digest
                or projection.get("decision_ref") != DEC007_DECISION_REF
                or projection.get("worker_task_id") != DEC007_WORKER_TASK_ID
                or projection.get("active_contract_count") != 3
                or set(projection.get("operation_class_ids", [])) != set(DEC007_CONTRACT_IDS)
                or projection.get("owned_scope_sha256") != owned_scope_digest(owned_files)):
            raise GatewayError("sealed authorization projection mismatch")
        validated_ids = set()
        for raw in contracts:
            try:
                value = dict(raw); value["requirement_refs"] = tuple(value.get("requirement_refs", ()))
                value["plan_task_refs"] = tuple(value.get("plan_task_refs", ()))
                contract = ToolAuthorizationContract(**value); validate_contract(contract)
            except (TypeError, ToolAuthorizationError) as exc:
                raise GatewayError("sealed authorization contract is invalid") from exc
            if (contract.contract_status != "ACTIVE"
                    or contract.contract_id != DEC007_CONTRACT_IDS.get(contract.operation_class_id)
                    or contract.worker_task_id != DEC007_WORKER_TASK_ID
                    or contract.authorization_decision_ref != DEC007_DECISION_REF
                    or contract.project_id != payload.get("project_id")
                    or contract.gate_id != payload.get("gate_id")
                    or contract.lv_id != payload.get("lv_id")
                    or contract.run_id != payload.get("run_id")
                    or contract.canonical_plan_sha256 != payload.get("canonical_plan_sha256")
                    or projection.get("requirement_digests", {}).get(contract.operation_class_id)
                       != contract.requirement_digest
                    or contract.owned_scope_sha256 != projection.get("owned_scope_sha256")
                    or contract.package_binding_sha256 != projection.get("package_binding_sha256")):
                raise GatewayError("sealed authorization contract binding mismatch")
            validated_ids.add(contract.contract_id)
        if validated_ids != set(DEC007_CONTRACT_IDS.values()):
            raise GatewayError("sealed authorization set is incomplete")
    unsigned = dict(payload); digest = unsigned.pop("request_digest")
    if not isinstance(digest, str) or _digest(unsigned) != digest:
        raise GatewayError("gateway request digest mismatch")
    if expected:
        for key in ("execution_request_id", "project_id", "run_id", "gate_id", "lv_id", "attempt"):
            if key in expected and payload.get(key) != expected[key]:
                raise GatewayError("gateway request binding mismatch")
    return dict(payload)


def build_gateway_result(request: Mapping[str, Any], *, backend_identity: str,
                         process_termination_category: str, exit_status_category: str,
                         structured_event_metadata: Mapping[str, Any],
                         stderr_security_metadata: Mapping[str, Any],
                         final_message_metadata: Mapping[str, Any],
                         worker_result_identity: Mapping[str, Any],
                         execution_status: str) -> dict[str, Any]:
    request = validate_gateway_request(request)
    if backend_identity not in SUPPORTED_BACKENDS:
        raise GatewayError("gateway result backend is invalid")
    if execution_status not in {"COMPLETED", "FAILED", "BLOCKED"}:
        raise GatewayError("gateway result status is invalid")
    payload = {
        "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
        "execution_request_id": request["execution_request_id"],
        "project_id": request["project_id"], "run_id": request["run_id"],
        "gate_id": request["gate_id"], "lv_id": request["lv_id"], "attempt": request["attempt"],
        "backend_identity": backend_identity,
        "process_termination_category": process_termination_category,
        "exit_status_category": exit_status_category,
        "structured_event_metadata": dict(structured_event_metadata),
        "stderr_security_metadata": dict(stderr_security_metadata),
        "final_message_metadata": dict(final_message_metadata),
        "worker_result_identity": dict(worker_result_identity),
        "request_digest": request["request_digest"],
        "execution_status": execution_status,
    }
    payload["result_digest"] = _digest(payload)
    return payload


def validate_gateway_result(payload: Mapping[str, Any], *, expected_request: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("gateway_contract_version", "execution_request_id", "project_id", "run_id", "gate_id", "lv_id",
              "attempt", "backend_identity", "process_termination_category", "exit_status_category",
              "structured_event_metadata", "stderr_security_metadata", "final_message_metadata",
              "worker_result_identity", "request_digest", "execution_status", "result_digest")
    _required(payload, fields)
    request = validate_gateway_request(expected_request)
    if payload["gateway_contract_version"] != GATEWAY_CONTRACT_VERSION:
        raise GatewayError("gateway result version is invalid")
    for key in ("execution_request_id", "project_id", "run_id", "gate_id", "lv_id", "attempt"):
        if payload.get(key) != request.get(key):
            raise GatewayError("gateway result binding mismatch")
    if payload.get("request_digest") != request["request_digest"]:
        raise GatewayError("gateway result request digest mismatch")
    unsigned = dict(payload); digest = unsigned.pop("result_digest")
    if not isinstance(digest, str) or _digest(unsigned) != digest:
        raise GatewayError("gateway result digest mismatch")
    return dict(payload)


@dataclass(frozen=True)
class GatewayExecution:
    stdout: bytes
    stderr: bytes
    final_message: bytes
    process_evidence: dict[str, Any]
    adapter_evidence: dict[str, Any]
    gateway_request: dict[str, Any]


class HostExecutionGateway:
    """Explicit host transport seam. Missing transport is never a local fallback."""

    backend_identity = HOST_GATEWAY

    def __init__(
        self,
        transport: Callable[..., Mapping[str, Any]] | None = None,
        *,
        require_canonical_authority: bool = False,
    ) -> None:
        self._transport = transport
        self._require_canonical_authority = bool(require_canonical_authority)
        self._seen: set[str] = set()

    def execute(self, request: Mapping[str, Any], *, prompt: bytes, last_message: Path,
                timeout: int, cancel_path: Path) -> GatewayExecution:
        request = validate_gateway_request(
            request,
            require_canonical_authority=self._require_canonical_authority,
        )
        request_id = request["execution_request_id"]
        if request_id in self._seen:
            raise GatewayError("duplicate execution request")
        self._seen.add(request_id)
        if self._transport is None:
            raise GatewayError("HOST_GATEWAY_UNAVAILABLE")
        try:
            result = self._transport(request, prompt=prompt, last_message=last_message,
                                     timeout=timeout, cancel_path=cancel_path)
        except Exception as exc:
            raise GatewayError("HOST_GATEWAY_TRANSPORT_FAILURE") from exc
        if not isinstance(result, Mapping):
            raise GatewayError("malformed host gateway response")
        try:
            stdout = bytes(result.get("stdout", b"")); stderr = bytes(result.get("stderr", b""))
        except (TypeError, ValueError) as exc:
            raise GatewayError("malformed host gateway output") from exc
        process = dict(result.get("process_evidence") or {})
        adapter = dict(result.get("adapter_evidence") or {})
        try:
            final_message = bytes(result.get("final_message", b""))
        except (TypeError, ValueError) as exc:
            raise GatewayError("malformed final-message response") from exc
        return GatewayExecution(stdout, stderr, final_message, process, adapter, request)


class DurableExecutionLedger:
    """Create-once request ledger; only safe metadata is persisted."""

    STATES = frozenset({"RECEIVED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "ADOPTED"})

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request_id: str) -> Path:
        if not request_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in request_id):
            raise GatewayError("unsafe execution request id")
        return self.root / f"{request_id}.json"

    def read(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        path = self._path(str(request["execution_request_id"]))
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GatewayError("malformed execution ledger") from exc
        if not isinstance(record, dict) or record.get("request_digest") != request.get("request_digest"):
            raise GatewayError("execution ledger identity mismatch")
        if record.get("state") not in self.STATES:
            raise GatewayError("unknown execution ledger state")
        return record

    def transition(self, request: Mapping[str, Any], state: str, *, result_digest: str = "") -> dict[str, Any]:
        if state not in self.STATES:
            raise GatewayError("invalid execution ledger state")
        path = self._path(str(request["execution_request_id"]))
        current = self.read(request)
        if current:
            prior = current.get("state")
            allowed = {
                "RECEIVED": {"RUNNING"},
                "RUNNING": {"COMPLETED", "FAILED", "CANCELLED"},
                "COMPLETED": {"ADOPTED"},
                "FAILED": set(), "CANCELLED": set(), "ADOPTED": set(),
            }
            if state not in allowed.get(prior, set()):
                raise GatewayError("invalid execution ledger transition")
        record = {"schema_version": "orchestration.host-gateway-ledger.v1",
                  "execution_request_id": request["execution_request_id"],
                  "request_digest": request["request_digest"], "project_id": request["project_id"],
                  "run_id": request["run_id"], "gate_id": request["gate_id"], "lv_id": request["lv_id"],
                  "attempt": request["attempt"], "state": state, "result_digest": result_digest}
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True, separators=(",", ":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return record


def _frame(payload: Mapping[str, Any]) -> bytes:
    data = canonical_json_bytes(dict(payload))
    return struct.pack("!I", len(data)) + data


def _read_frame(sock: socket.socket, limit: int = 8 * 1024 * 1024) -> dict[str, Any]:
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk: raise GatewayError("host runner closed connection")
        header += chunk
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > limit: raise GatewayError("host runner frame is invalid")
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk: raise GatewayError("host runner response is truncated")
        data += chunk
    try: value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc: raise GatewayError("host runner response is malformed") from exc
    if not isinstance(value, dict): raise GatewayError("host runner response is not an object")
    return value


class UnixSocketGatewayTransport:
    """Authenticated UDS client; payload bytes are transient and never ledgered."""

    def __init__(self, socket_path: str | Path, *, expected_uid: int | None = None,
                 workspace_root: str | Path | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        self.workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None

    def __call__(self, request: Mapping[str, Any], *, prompt: bytes, last_message: Path,
                 timeout: int, cancel_path: Path) -> Mapping[str, Any]:
        if not self.socket_path.is_socket() or self.socket_path.is_symlink():
            raise GatewayError("host runner socket unavailable")
        mode = self.socket_path.stat().st_mode
        if mode & 0o077 or self.socket_path.stat().st_uid != self.expected_uid:
            raise GatewayError("host runner socket permission mismatch")
        if self.workspace_root is None:
            raise GatewayError("host runner workspace binding is missing")
        _, last_message_relative = _workspace_artifact_binding(self.workspace_root, last_message)
        payload = {"request": dict(request), "prompt_b64": base64.b64encode(prompt).decode("ascii"),
                   "workspace_root": str(self.workspace_root) if self.workspace_root else "",
                   "last_message_relative": last_message_relative, "timeout": int(timeout),
                   "cancel_name": cancel_path.name}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(self.socket_path))
            if hasattr(socket, "SO_PEERCRED"):
                peer_pid, peer_uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                if peer_uid != self.expected_uid or peer_pid <= 0:
                    raise GatewayError("host runner peer credential mismatch")
            client.sendall(_frame(payload))
            result = _read_frame(client)
        gateway_result = result.get("gateway_result")
        if not isinstance(gateway_result, Mapping):
            raise GatewayError("host runner gateway result is missing")
        validate_gateway_result(gateway_result, expected_request=request)
        if result.get("request_digest") != request.get("request_digest") or result.get("execution_request_id") != request.get("execution_request_id"):
            raise GatewayError("host runner response binding mismatch")
        try:
            return {"stdout": base64.b64decode(result.get("stdout_b64", ""), validate=True),
                    "stderr": base64.b64decode(result.get("stderr_b64", ""), validate=True),
                    "final_message": base64.b64decode(result.get("final_message_b64", ""), validate=True),
                    "process_evidence": result["process_evidence"], "adapter_evidence": result["adapter_evidence"],
                    "adopted": bool(result.get("adopted", False))}
        except (KeyError, ValueError, TypeError) as exc:
            raise GatewayError("host runner response payload is invalid") from exc


class UnixSocketHostRunner:
    """Single-request host runner for tests and an explicit future service entrypoint."""

    def __init__(self, socket_path: str | Path, ledger_root: str | Path, *, expected_uid: int | None = None,
                 executor: Callable[..., Any] | None = None, broker_native: bool = False) -> None:
        self.socket_path = Path(socket_path); self.ledger = DurableExecutionLedger(ledger_root)
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid; self.executor = executor
        self.broker_native = broker_native

    def serve_once(self, *, timeout: int = 1800) -> None:
        if self.socket_path.exists():
            raise GatewayError("runner socket already exists")
        # Linux AF_UNIX pathname is limited to 108 bytes including NUL.
        if len(os.fsencode(str(self.socket_path))) >= 108:
            raise GatewayError("UDS_PATH_TOO_LONG")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            try:
                os.chmod(self.socket_path, 0o600)
            except OSError as exc:
                raise GatewayError("UDS_CHMOD") from exc
            try:
                server.listen(1)
            except OSError as exc:
                raise GatewayError("UDS_LISTEN") from exc
            with server:
                conn, _ = server.accept()
                with conn:
                    if hasattr(socket, "SO_PEERCRED"):
                        _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                        if uid != self.expected_uid: raise GatewayError("runner peer credential mismatch")
                    envelope = _read_frame(conn)
                    request = validate_gateway_request(envelope.get("request", {}))
                    record = self.ledger.read(request)
                    if record and record["state"] == "COMPLETED":
                        gateway_result = build_gateway_result(request, backend_identity=HOST_GATEWAY,
                            process_termination_category="ADOPTED", exit_status_category="EXIT_0",
                            structured_event_metadata={"adopted": True}, stderr_security_metadata={"status": "NOT_REEXECUTED"},
                            final_message_metadata={"adopted": True}, worker_result_identity={"ledger": "COMPLETED"}, execution_status="COMPLETED")
                        response = {"execution_request_id": request["execution_request_id"], "request_digest": request["request_digest"],
                                    "adopted": True, "process_evidence": {}, "adapter_evidence": {}, "stdout_b64": "", "stderr_b64": ""}
                        response["gateway_result"] = gateway_result
                    else:
                        self.ledger.transition(request, "RECEIVED"); self.ledger.transition(request, "RUNNING")
                        if self.broker_native:
                            from .production_tool_transport import ProductionToolTransport
                            from .production_worker_executor import _secret_findings
                            prompt = base64.b64decode(envelope.get("prompt_b64", ""), validate=True)
                            workspace_root = Path(str(envelope.get("workspace_root", "")))
                            if not workspace_root.is_absolute() or not workspace_root.is_dir() or workspace_root.is_symlink():
                                raise GatewayError("host runner workspace is invalid")
                            def safe(value: Any) -> bool:
                                try: raw = canonical_json_bytes(value) if isinstance(value, Mapping) else bytes(value)
                                except (TypeError, ValueError): return False
                                return not bool(_secret_findings(raw))
                            transport = ProductionToolTransport(
                                request=request, workspace_root=workspace_root,
                                journal_root=self.ledger.root / "tool-effects", security_scan=safe)
                            outcome = transport.run(prompt=prompt.decode("utf-8"), timeout=timeout)
                            completed = outcome.get("completion") == "COMPLETED"
                            final_message = b"broker-native worker turn completed" if completed else b"broker-native worker turn blocked"
                            gateway_result = build_gateway_result(request, backend_identity=HOST_GATEWAY,
                                process_termination_category="EXITED", exit_status_category="EXIT_0" if completed else "NONZERO",
                                structured_event_metadata={"validation": "BROKER_NATIVE", "registry": outcome.get("registry", {})},
                                stderr_security_metadata={"status": "PASS"},
                                final_message_metadata={"exists": True, "nonempty": True, "security": "PASS"},
                                worker_result_identity={"transport": TRANSPORT_CONTRACT_VERSION},
                                execution_status="COMPLETED" if completed else "BLOCKED")
                            response = {"execution_request_id": request["execution_request_id"],
                                "request_digest": request["request_digest"], "adopted": False,
                                "process_evidence": {"exit_code": 0 if completed else 1, "termination": "EXITED",
                                    "transport_compatibility": outcome.get("compatibility", {}),
                                    "registry": outcome.get("registry", {}),
                                    "governed_effect_evidence": list(
                                        outcome.get("governed_effect_evidence", [])
                                    ),
                                    "structured_events": {"contract_version": request["structured_event_contract_version"],
                                        "event_type_counts": {"BROKER_NATIVE_TURN": 1},
                                        "event_type_sequence_category": "BROKER_NATIVE",
                                        "unknown_event_count": 0, "parse_error_count": 0,
                                        "terminal_event_present": completed}},
                                "adapter_evidence": {"backend": HOST_GATEWAY, "contract_version": TRANSPORT_CONTRACT_VERSION,
                                    "strict": False, "structured_event_contract_version": request["structured_event_contract_version"],
                                    "codex_version": PINNED_CODEX_VERSION,
                                    "final_message_target_binding": "WORKSPACE_RELATIVE_EXACT"},
                                "stdout_b64": "", "stderr_b64": "",
                                "final_message_b64": base64.b64encode(final_message).decode("ascii"),
                                "gateway_result": gateway_result}
                            self.ledger.transition(request, "COMPLETED" if completed else "FAILED",
                                                   result_digest=gateway_result["result_digest"])
                            conn.sendall(_frame(response))
                            return
                        if self.executor is None: raise GatewayError("host runner executor is not configured")
                        from .production_worker_executor import CodexExecutionAdapter, _validate_final_message
                        adapter = CodexExecutionAdapter()
                        if (request["adapter_contract_version"] != adapter.contract_version
                                or request["structured_event_contract_version"] != adapter.structured_event_contract_version):
                            raise GatewayError("Codex adapter/structured event contract version mismatch")
                        prompt = base64.b64decode(envelope.get("prompt_b64", ""), validate=True)
                        workspace_root = Path(str(envelope.get("workspace_root", "")))
                        if not workspace_root.is_absolute() or not workspace_root.is_dir() or workspace_root.is_symlink():
                            raise GatewayError("host runner workspace is invalid")
                        codex_version = adapter.probe_version(self.executor)
                        relative_target = envelope.get("last_message_relative")
                        if not isinstance(relative_target, str):
                            raise GatewayError("final-message target binding is missing")
                        target, rebound = _workspace_artifact_binding(
                            workspace_root, workspace_root / relative_target,
                        )
                        if rebound != relative_target:
                            raise GatewayError("final-message target binding mismatch")
                        completed = self.executor(adapter.argv(root=workspace_root, last_message=target), input=prompt, stdout=None, stderr=None, check=False, timeout=timeout)
                        stdout = bytes(getattr(completed, "stdout", b"") or b""); stderr = bytes(getattr(completed, "stderr", b"") or b"")
                        final_message = b""
                        final_metadata: dict[str, Any] = {"exists": False, "nonempty": False, "size_bucket": "0"}
                        if completed.returncode == 0:
                            final_metadata = _validate_final_message(target)
                            final_message = target.read_bytes()
                        gateway_result = build_gateway_result(request, backend_identity=HOST_GATEWAY,
                            process_termination_category="EXITED", exit_status_category="EXIT_0" if completed.returncode == 0 else "NONZERO",
                            structured_event_metadata={"validation": "DEFERRED_TO_WORKER"},
                            stderr_security_metadata={"validation": "DEFERRED_TO_WORKER"},
                            final_message_metadata={**final_metadata, "security": "PASS",
                                                    "staging_binding": "WORKSPACE_RELATIVE_EXACT"},
                            worker_result_identity={"execution_request_id": request["execution_request_id"]},
                            execution_status="COMPLETED" if completed.returncode == 0 else "FAILED")
                        response = {"execution_request_id": request["execution_request_id"], "request_digest": request["request_digest"],
                                    "adopted": False, "process_evidence": {"exit_code": int(getattr(completed, "returncode", 1)), "termination": "EXITED"},
                                    "adapter_evidence": {
                                        "backend": HOST_GATEWAY,
                                        "contract_version": adapter.contract_version,
                                        "strict": True,
                                        "structured_event_contract_version": adapter.structured_event_contract_version,
                                        "codex_version": codex_version,
                                        "final_message_target_binding": "WORKSPACE_RELATIVE_EXACT",
                                    },
                                    "stdout_b64": base64.b64encode(stdout).decode("ascii"), "stderr_b64": base64.b64encode(stderr).decode("ascii")}
                        response["final_message_b64"] = base64.b64encode(final_message).decode("ascii")
                        response["gateway_result"] = gateway_result
                        self.ledger.transition(request, "COMPLETED" if completed.returncode == 0 else "FAILED",
                                               result_digest=gateway_result["result_digest"])
                    conn.sendall(_frame(response))
        finally:
            server.close()
            if self.socket_path.exists(): self.socket_path.unlink()

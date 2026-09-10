"""Pinned broker-native Codex App Server transport (SC-4.0-CANDIDATE).

This module terminates the provider-specific JSON-RPC protocol.  Callers see
only provider-neutral session, turn, tool-request, and tool-result contracts.
Native environments are deliberately set to an empty list; governed effects
can therefore be requested only through the closed dynamic-tool registry.
"""
from __future__ import annotations

import json
import re
import select
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


PINNED_CODEX_VERSION = "0.150.1"
TRANSPORT_CONTRACT_VERSION = "codex-app-server.dynamic-tools.0.150.1.v1"
REQUIRED_SERVER_REQUEST = "item/tool/call"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class TransportError(RuntimeError):
    """Bounded compatibility or protocol failure."""


@dataclass(frozen=True, slots=True)
class WorkerSessionRef:
    provider: str
    session_id: str


@dataclass(frozen=True, slots=True)
class WorkerTurnRef:
    session: WorkerSessionRef
    turn_id: str


@dataclass(frozen=True, slots=True)
class ToolRequestEnvelope:
    operation_class_id: str
    worker_task_id: str
    worker_action_id: str
    arguments: Mapping[str, Any]
    provider_call_id: str


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    status: str
    result_presence: str
    security_status: str
    bounded_payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TransportCompatibility:
    codex_version: str
    experimental_api: bool
    dynamic_tool_request: bool
    dynamic_tool_response: bool
    empty_environment_supported: bool
    schema_verified: bool

    @property
    def compatible(self) -> bool:
        return (
            self.codex_version == PINNED_CODEX_VERSION
            and self.experimental_api
            and self.dynamic_tool_request
            and self.dynamic_tool_response
            and self.empty_environment_supported
            and self.schema_verified
        )


class WorkerAdapter(Protocol):
    def check_compatibility(self) -> TransportCompatibility: ...
    def run_turn(self, *, prompt: str, dynamic_tools: Sequence[Mapping[str, Any]],
                 tool_handler: Callable[[ToolRequestEnvelope], ToolResultEnvelope]) -> Mapping[str, Any]: ...


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise TransportError(f"invalid bounded {name}")
    return value


def validate_compatibility(value: TransportCompatibility) -> None:
    if not value.compatible:
        raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK")


def validate_closed_registry(dynamic_tools: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for item in dynamic_tools:
        if not isinstance(item, Mapping) or item.get("type") != "function":
            raise TransportError("closed dynamic registry contains an unsupported entry")
        name = _safe_id(item.get("name"), "operation class")
        if name in names or name == "UNBOUND_OPERATION_CLASS":
            raise TransportError("closed dynamic registry identity is duplicate or unbound")
        schema = item.get("inputSchema")
        if not isinstance(schema, Mapping) or schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise TransportError("dynamic operation schema is not closed")
        names.append(name)
    if not names:
        raise TransportError("closed dynamic registry is empty")
    return tuple(names)


class CodexAppServerAdapter:
    """Thin stdio JSON-RPC adapter; it never launches a governed effect."""

    def __init__(self, *, process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
                 version_probe: Callable[[], str] | None = None,
                 schema_probe: Callable[[], Mapping[str, bool]] | None = None) -> None:
        self._process_factory = process_factory
        self._version_probe = version_probe or self._probe_version
        self._schema_probe = schema_probe

    @staticmethod
    def _probe_version() -> str:
        try:
            completed = subprocess.run(["codex", "--version"], capture_output=True, text=True,
                                       check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK") from exc
        match = re.fullmatch(r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\r?\n?", completed.stdout or "")
        if completed.returncode != 0 or match is None:
            raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK")
        return match.group(1)

    @staticmethod
    def _probe_schema() -> Mapping[str, bool]:
        try:
            with tempfile.TemporaryDirectory(prefix="codex-transport-schema-") as directory:
                completed = subprocess.run(
                    ["codex", "app-server", "generate-json-schema", "--experimental", "--out", directory],
                    capture_output=True, check=False, timeout=30,
                )
                bundle = Path(directory) / "codex_app_server_protocol.schemas.json"
                if completed.returncode != 0 or not bundle.is_file():
                    raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK")
                raw = bundle.read_bytes()
        except (OSError, subprocess.SubprocessError) as exc:
            raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK") from exc
        checks = {
            "experimental_api": b'"experimentalApi"' in raw,
            "dynamic_tool_request": b'"item/tool/call"' in raw and b'"dynamicTools"' in raw,
            "dynamic_tool_response": b'"contentItems"' in raw,
            "empty_environment_supported": b'"environments"' in raw and b'Empty disables environment access' in raw,
        }
        return {**checks, "schema_verified": all(checks.values())}

    def check_compatibility(self) -> TransportCompatibility:
        schema = dict((self._schema_probe or self._probe_schema)())
        result = TransportCompatibility(self._version_probe(), **schema)
        validate_compatibility(result)
        return result

    @staticmethod
    def registry_evidence(dynamic_tools: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        identities = validate_closed_registry(dynamic_tools)
        return {
            "transport_contract_version": TRANSPORT_CONTRACT_VERSION,
            "registry_kind": "CLOSED_DYNAMIC_ONLY",
            "dynamic_operation_count": len(identities),
            "operation_class_ids": list(identities),
            "native_command_runtime_count": 0,
            "native_file_runtime_count": 0,
            "direct_mcp_effect_source_count": 0,
            "native_fallback": "ABSENT",
        }

    @staticmethod
    def normalize_tool_request(params: Mapping[str, Any], *, worker_task_id: str,
                               worker_action_id: str) -> ToolRequestEnvelope:
        name = _safe_id(params.get("tool"), "operation class")
        call_id = _safe_id(params.get("callId"), "provider call")
        arguments = params.get("arguments")
        if not isinstance(arguments, Mapping):
            raise TransportError("dynamic tool arguments are malformed")
        return ToolRequestEnvelope(name, _safe_id(worker_task_id, "worker task"),
                                   _safe_id(worker_action_id, "worker action"), dict(arguments), call_id)

    @staticmethod
    def protocol_result(result: ToolResultEnvelope) -> dict[str, Any]:
        if result.status not in {"COMPLETED", "BLOCKED", "FAILED"}:
            raise TransportError("bounded tool result status is invalid")
        # Only bounded broker output is returned. Raw launcher output remains
        # private to the broker/security boundary.
        return {"contentItems": [{"type": "inputText", "text": json.dumps({
            "status": result.status,
            "result_presence": result.result_presence,
            "security_status": result.security_status,
            "result": dict(result.bounded_payload),
        }, sort_keys=True, separators=(",", ":"))}]}

    def run_turn(self, *, prompt: str, dynamic_tools: Sequence[Mapping[str, Any]],
                 tool_handler: Callable[[ToolRequestEnvelope], ToolResultEnvelope],
                 worker_task_id: str = "TASK-4A-08", worker_action_id: str = "WORKER_TURN",
                 timeout: int = 180) -> Mapping[str, Any]:
        compatibility = self.check_compatibility()
        registry = self.registry_evidence(dynamic_tools)
        process = self._process_factory(
            ["codex", "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        if process.stdin is None or process.stdout is None:
            raise TransportError("app-server stdio unavailable")
        if not isinstance(timeout, int) or timeout < 1:
            raise TransportError("transport timeout is invalid")
        deadline = time.monotonic() + timeout
        next_id = 1
        pending: dict[int, Mapping[str, Any]] = {}

        def send(value: Mapping[str, Any]) -> None:
            process.stdin.write(json.dumps(dict(value), separators=(",", ":")) + "\n")
            process.stdin.flush()

        def request(method: str, params: Mapping[str, Any]) -> int:
            nonlocal next_id
            request_id = next_id; next_id += 1
            send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
            return request_id

        try:
            initialize_id = request("initialize", {"clientInfo": {"name": "harness-broker", "version": "1"},
                                                    "capabilities": {"experimentalApi": True}})
            thread_id: str | None = None
            turn_id: str | None = None
            terminal = "UNKNOWN"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportError("TRANSPORT_TIMEOUT")
                try:
                    ready, _, _ = select.select([process.stdout], [], [], remaining)
                except (TypeError, ValueError, OSError):
                    # Deterministic in-memory protocol fixtures have no fd.
                    ready = [process.stdout]
                if not ready:
                    raise TransportError("TRANSPORT_TIMEOUT")
                line = process.stdout.readline()
                if not line:
                    raise TransportError("app-server protocol ended before completion")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TransportError("app-server emitted malformed protocol data") from exc
                if message.get("id") == initialize_id:
                    if "error" in message:
                        raise TransportError("TRANSPORT_COMPATIBILITY_BLOCK")
                    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
                    start_id = request("thread/start", {
                        "experimentalRawEvents": False,
                        "dynamicTools": [dict(item) for item in dynamic_tools],
                        "environments": [],
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                    })
                    pending[start_id] = {"kind": "thread"}
                    continue
                message_id = message.get("id")
                if isinstance(message_id, int) and message_id in pending:
                    kind = pending.pop(message_id)["kind"]
                    if "error" in message:
                        raise TransportError("app-server request failed")
                    if kind == "thread":
                        thread = message.get("result", {}).get("thread", {})
                        thread_id = _safe_id(thread.get("id"), "session")
                        turn_request = request("turn/start", {
                            "threadId": thread_id,
                            "input": [{"type": "text", "text": prompt}],
                            "environments": [],
                        })
                        pending[turn_request] = {"kind": "turn"}
                    elif kind == "turn":
                        turn_id = _safe_id(message.get("result", {}).get("turn", {}).get("id"), "turn")
                    continue
                if message.get("method") == REQUIRED_SERVER_REQUEST and "id" in message:
                    try:
                        envelope = self.normalize_tool_request(message.get("params", {}),
                                                               worker_task_id=worker_task_id,
                                                               worker_action_id=worker_action_id)
                        result = tool_handler(envelope)
                        send({"jsonrpc": "2.0", "id": message["id"], "result": self.protocol_result(result)})
                    except Exception:
                        send({"jsonrpc": "2.0", "id": message["id"], "error": {
                            "code": -32001, "message": "BROKER_BLOCK"}})
                        terminal = "BROKER_BLOCKED"
                        break
                    continue
                method = message.get("method")
                if method == "turn/completed":
                    terminal = "COMPLETED"; break
                if method in {"turn/failed", "error"}:
                    terminal = "FAILED"; break
            return {
                "compatibility": asdict(compatibility), "registry": registry,
                "session_ref": asdict(WorkerSessionRef("CODEX_APP_SERVER", thread_id or "UNKNOWN")),
                "turn_ref": {"turn_id": turn_id or "UNKNOWN"}, "completion": terminal,
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()
            for stream in (process.stdin, process.stdout, process.stderr):
                close = getattr(stream, "close", None)
                if callable(close): close()

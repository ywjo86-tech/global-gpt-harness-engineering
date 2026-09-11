"""Registry-selected, fail-closed production implementation worker."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .lv_execution_package import canonical_json_bytes
from .schemas import WorkerRequest
from .tool_authorization import build_contract_candidate
from .production_execution_gateway import (
    GATEWAY_CONTRACT_VERSION, HOST_GATEWAY, LOCAL_CHILD, GatewayError,
    HostExecutionGateway, UnixSocketGatewayTransport, build_gateway_request,
    resolve_gateway_socket_path, validate_gateway_request,
)


class ProductionWorkerError(ValueError):
    pass


def _validate_production_gateway_request(
    gateway_request: Mapping[str, Any],
    *,
    configured_backend: str,
) -> dict[str, Any]:
    if configured_backend != HOST_GATEWAY:
        return dict(gateway_request)
    try:
        return validate_gateway_request(
            gateway_request,
            require_canonical_authority=True,
        )
    except GatewayError as exc:
        raise ProductionWorkerError(str(exc)) from exc


def _production_host_execution_gateway(
    transport: Callable[..., Mapping[str, Any]],
) -> HostExecutionGateway:
    return HostExecutionGateway(
        transport,
        require_canonical_authority=True,
    )


EXECUTOR_ID = "codex-cli-production"
EXECUTOR_VERSION = "1"
ADAPTER_CONTRACT_VERSION = "SEM-025.v2"
SUPPORTED_CODEX_VERSION = "0.150.1"
STRUCTURED_EVENT_CONTRACT_VERSION = "codex-exec-jsonl.0.150.1.v1"
CHECKPOINT_GIT_USER_NAME = "Global GPT Harness"
CHECKPOINT_GIT_USER_EMAIL = "harness@localhost.invalid"
_SECRET = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token)\s*[:=]\s*(\S+)")
_CREDENTIAL_IDENTIFIER = re.compile(
    r"(?i)(?:^|[_-])(api[_-]?key|authorization|bearer|password|token|credential|secret)(?:$|[_-])"
)


class StructuredEventError(ProductionWorkerError):
    """The Codex JSONL stream violated the closed event contract."""

    def __init__(self, message: str, *, safe_metadata: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.safe_metadata = dict(safe_metadata or {})


class StructuredContentSecurityError(ProductionWorkerError):
    """A typed structured-content field failed the existing secret detector."""

    def __init__(self, safe_metadata: Mapping[str, Any]) -> None:
        super().__init__("structured event contains secret-like content")
        self.safe_metadata = dict(safe_metadata)


def _bounded_structured_security_provenance(
    error: StructuredContentSecurityError,
) -> dict[str, Any]:
    """Project existing safe findings to a closed, value-free security summary."""
    findings = error.safe_metadata.get("structured_security_findings")
    finding = findings[0] if isinstance(findings, list) and findings and isinstance(findings[0], Mapping) else {}
    field = finding.get("structured_field_category")
    origin = {
        "COMMAND": "COMMAND_METADATA", "TOOL_INPUT": "COMMAND_METADATA",
        "TOOL_OUTPUT": "COMMAND_OUTPUT", "FILE_CHANGE": "FILE_METADATA",
        "AGENT_MESSAGE": "MODEL_OUTPUT", "REASONING": "MODEL_OUTPUT",
        "CONTENT_TEXT": "GENERATED_EVENT", "OTHER_CONTENT": "GENERATED_EVENT",
        "ERROR_CONTENT": "DIAGNOSTIC", "WEB_SEARCH": "USER_INPUT",
    }.get(field, "UNKNOWN")
    detector = {
        "api-key": "KEY_MATERIAL", "authorization": "AUTH_HEADER_LIKE",
        "bearer": "AUTH_HEADER_LIKE", "token": "TOKEN_LIKE",
        "password": "SECRET_PATTERN", "credential": "SECRET_PATTERN",
        "secret": "SECRET_PATTERN",
    }.get(finding.get("secret_kind"), "UNKNOWN")
    source_id = finding.get("security_command_source_id")
    source_family = finding.get("security_command_source_family")
    execution_phase = finding.get("security_command_execution_phase")
    resolution = finding.get("security_source_resolution")
    candidate_count = finding.get("security_source_candidate_count")
    tool_capability = finding.get("security_tool_capability")
    tool_origin = finding.get("security_tool_data_origin")
    tool_intent = finding.get("security_tool_operation_intent")
    tool_required = finding.get("tool_operation_required_for_worker_task")
    tool_in_scope = finding.get("tool_operation_within_approved_scope")
    worker_task_id = finding.get("worker_task_id")
    worker_action_id = finding.get("worker_action_id")
    tool_policy_id = finding.get("tool_operation_policy_id")
    requirement_binding = finding.get("tool_operation_requirement_binding")
    scope_binding = finding.get("tool_scope_binding")
    scope_authorization = finding.get("tool_scope_authorization_source")
    summary = {
        "security_source_channel": "WORKER",
        "security_value_origin": origin,
        "security_detector_family": detector,
        "security_event_stage": "EVENT_VALIDATION",
        "worker_process_spawn_reached": "YES",
        "worker_process_started": "YES",
        "worker_result_boundary_reached": "NO",
        "independent_verification_reached": "NO",
        "security_command_source_id": source_id if isinstance(source_id, str) else "WORKER_UNKNOWN_EXECUTION",
        "security_command_source_family": source_family if isinstance(source_family, str) else "UNKNOWN",
        "security_command_execution_phase": execution_phase if isinstance(execution_phase, str) else "UNKNOWN",
        "security_source_resolution": resolution if isinstance(resolution, str) else "UNKNOWN",
        "security_source_candidate_count": candidate_count if isinstance(candidate_count, int) and not isinstance(candidate_count, bool) and candidate_count >= 0 else 0,
        "security_tool_capability": tool_capability if isinstance(tool_capability, str) else "UNKNOWN",
        "security_tool_data_origin": tool_origin if isinstance(tool_origin, str) else "UNKNOWN",
        "security_tool_operation_intent": tool_intent if isinstance(tool_intent, str) else "UNKNOWN",
        "tool_operation_required_for_worker_task": tool_required if tool_required in {"YES", "NO", "UNKNOWN"} else "UNKNOWN",
        "tool_operation_within_approved_scope": tool_in_scope if tool_in_scope in {"YES", "NO", "UNKNOWN"} else "UNKNOWN",
        "worker_task_id": worker_task_id if isinstance(worker_task_id, str) else "UNKNOWN",
        "worker_action_id": worker_action_id if isinstance(worker_action_id, str) else "UNKNOWN",
        "tool_operation_policy_id": tool_policy_id if isinstance(tool_policy_id, str) else "UNBOUND_TOOL_POLICY",
        "tool_operation_requirement_binding": requirement_binding if requirement_binding in {"REQUIRED", "OPTIONAL", "UNRELATED", "UNKNOWN"} else "UNKNOWN",
        "tool_scope_binding": scope_binding if scope_binding in {"IN_SCOPE", "OUT_OF_SCOPE", "PARTIAL", "UNKNOWN"} else "UNKNOWN",
        "tool_scope_authorization_source": scope_authorization if scope_authorization in {"REQUIREMENT", "PLAN_TASK", "OWNED_FILES", "APPROVAL_RECORD", "POLICY", "MULTIPLE", "UNKNOWN"} else "UNKNOWN",
    }
    if origin == "COMMAND_OUTPUT":
        summary["tool_auth_contract_candidate"] = build_contract_candidate({**finding, **summary})
    return summary


SUPPORTED_STRUCTURED_EVENTS = (
    "thread.started",
    "turn.started",
    "item.started",
    "item.updated",
    "item.completed",
    "turn.completed",
    "turn.failed",
    "error",
)
_SUPPORTED_STRUCTURED_EVENT_SET = frozenset(SUPPORTED_STRUCTURED_EVENTS)
_SAFE_EVENT_TYPE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
SUPPORTED_STRUCTURED_ITEM_TYPES = (
    "agent_message", "reasoning", "command_execution", "file_change",
    "mcp_tool_call", "collab_tool_call", "web_search", "todo_list", "error",
)
_SUPPORTED_STRUCTURED_ITEM_TYPE_SET = frozenset(SUPPORTED_STRUCTURED_ITEM_TYPES)
_STARTABLE_ITEM_TYPES = frozenset({
    "command_execution", "file_change", "mcp_tool_call", "collab_tool_call", "web_search", "todo_list",
})
_REQUIRED_STRUCTURED_FIELDS = {
    "thread.started": ("thread_id",),
    "turn.started": (),
    "item.started": ("item",),
    "item.updated": ("item",),
    "item.completed": ("item",),
    "turn.completed": ("usage",),
    "turn.failed": ("error",),
    "error": ("message",),
}

_STATUS_CATEGORIES = {
    "in_progress": "IN_PROGRESS", "completed": "COMPLETED",
    "failed": "FAILED", "declined": "DECLINED",
}


def _structured_metadata(*, counts: Mapping[str, int], item_counts: Mapping[str, int],
                         unknown_event_count: int = 0, terminal_status: str = "INCOMPLETE",
                         **extra: Any) -> dict[str, Any]:
    metadata = {
        "contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
        "codex_version": SUPPORTED_CODEX_VERSION,
        "event_type_counts": dict(sorted(counts.items())),
        "item_type_counts": dict(sorted(item_counts.items())),
        "event_type_sequence_category": "INVALID" if terminal_status != "SUCCEEDED" else "THREAD_TURN_ITEMS_TERMINAL",
        "unknown_event_count": unknown_event_count,
        "unknown_item_type_count": 0,
        "parse_error_count": 0,
        "structured_terminal_status": terminal_status,
        "terminal_event_present": terminal_status in {"SUCCEEDED", "FAILED"},
    }
    metadata.update(extra)
    return metadata


def _validated_item(event_type: str, event: Mapping[str, Any], *, counts: Mapping[str, int],
                    item_counts: Mapping[str, int]) -> tuple[str, str]:
    item = event.get("item")
    if not isinstance(item, dict):
        raise StructuredEventError("structured item envelope is invalid")
    item_id = item.get("id")
    item_type = item.get("type")
    if (not isinstance(item_id, str) or not item_id or len(item_id) > 256
            or any(ord(char) < 32 for char in item_id)):
        raise StructuredEventError("structured item identity is invalid")
    if not isinstance(item_type, str) or item_type not in _SUPPORTED_STRUCTURED_ITEM_TYPE_SET:
        raise StructuredEventError(
            "unknown structured item type",
            safe_metadata=_structured_metadata(
                counts=counts, item_counts=item_counts, unknown_item_type_count=1,
                unknown_item_type_category="UNKNOWN_OR_INVALID_ITEM_TYPE",
            ),
        )
    status = item.get("status")
    allowed_statuses = {
        "command_execution": ({"in_progress"}, {"completed", "failed", "declined"}),
        "file_change": ({"in_progress"}, {"completed", "failed"}),
        "mcp_tool_call": ({"in_progress"}, {"completed", "failed"}),
        "collab_tool_call": ({"in_progress"}, {"completed", "failed"}),
    }
    if item_type in allowed_statuses:
        started_statuses, completed_statuses = allowed_statuses[item_type]
        expected = started_statuses if event_type == "item.started" else completed_statuses if event_type == "item.completed" else set()
        if status not in expected:
            expected_category = (
                "IN_PROGRESS" if event_type == "item.started"
                else "COMPLETED_FAILED_OR_DECLINED" if item_type == "command_execution"
                else "COMPLETED_OR_FAILED" if event_type == "item.completed"
                else "NOT_APPLICABLE"
            )
            raise StructuredEventError(
                "structured item status is incompatible with event",
                safe_metadata={
                    "structured_failure_stage": "ITEM_STATUS",
                    "structured_failure_event_type": event_type,
                    "structured_failure_item_type": item_type,
                    "structured_failure_status_category": _STATUS_CATEGORIES.get(status, "UNKNOWN"),
                    "structured_expected_status_category": expected_category,
                },
            )
    return item_id, item_type


def _require_exact_fields(value: Mapping[str, Any], required: set[str], optional: set[str] = set()) -> None:
    if not required.issubset(value) or set(value) - required - optional:
        raise StructuredEventError("structured event contains unknown or missing fields")


def _content_strings(value: Any) -> list[bytes]:
    if isinstance(value, str):
        return [value.encode("utf-8")]
    if isinstance(value, list):
        return [item for child in value for item in _content_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _content_strings(child)]
    if value is None or isinstance(value, (bool, int, float)):
        return []
    raise StructuredEventError("structured content has an unsupported shape")


def _safe_security_findings(value: bytes, *, channel: str, category: str,
                            event_type: str | None = None,
                            item_type: str | None = None,
                            provenance: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    return [{
        "security_channel": channel,
        "structured_field_category": category,
        "event_type": event_type,
        "item_type": item_type,
        "secret_kind": kind,
        "count": count,
        **dict(provenance or {}),
    } for kind, count in sorted(_secret_findings(value).items())]


def _argv_bucket(count: int) -> str:
    return "0" if count == 0 else "1-3" if count <= 3 else "4-8" if count <= 8 else "9+"


def _tokenize_command(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&();<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _direct_command(tokens: list[str]) -> tuple[str, str, str]:
    executable = PurePosixPath(tokens[0]).name
    args = tokens[1:]
    executable_family = "unknown"
    family = "unknown"
    purpose = "UNKNOWN"
    if executable == "git":
        executable_family = family = "git"
        subcommand = next((arg for arg in args if arg in {
            "diff", "status", "show", "log", "rev-parse", "add", "commit", "checkout",
            "restore", "reset", "clean", "merge-base", "diff-tree",
        }), "")
        purpose = ({"diff": "DIFF", "status": "STATUS", "show": "FILE_READ",
                    "log": "FILE_READ"}.get(subcommand, "OTHER"))
    elif executable in {"python", "python3"}:
        executable_family = family = "python"
        purpose = "TEST" if args[:2] in (["-m", "unittest"], ["-m", "pytest"]) else "OTHER"
    elif executable in {"pytest", "py.test"}:
        executable_family = family = "pytest"; purpose = "TEST"
    elif executable == "rg":
        executable_family = "rg"; family = "grep_rg"; purpose = "SEARCH"
    elif executable == "grep":
        executable_family = "grep"; family = "grep_rg"; purpose = "SEARCH"
    elif executable in {"bash", "sh"}:
        executable_family = executable; family = "shell_builtin"; purpose = "OTHER"
    elif executable in {"cd", "pwd", "printf", "echo", "test", "true", "false"}:
        executable_family = family = "shell_builtin"
        purpose = "STATUS" if executable in {"test", "true", "false"} else "OTHER"
    elif executable in {"cc", "gcc", "clang", "c++", "g++", "rustc", "go", "javac", "tsc"}:
        executable_family = "compiler"; family = "compiler"; purpose = "BUILD"
    elif executable in {"sed", "head", "tail", "find", "ls", "file", "nl", "make", "ninja", "cargo", "npm"}:
        executable_family = family = "other_known"
        purpose = "FILE_READ" if executable in {"sed", "head", "tail", "file", "nl"} else "BUILD" if executable in {"make", "ninja"} else "OTHER"
    return family, purpose, executable_family


def _pipeline_stage_metadata(tokens: list[str]) -> tuple[str, str, str]:
    if not tokens or any(token in {"&&", "||", ";", "(", ")"} for token in tokens):
        return "unknown", "UNKNOWN", "unknown"
    _, purpose, executable_family = _direct_command(tokens)
    executable = PurePosixPath(tokens[0]).name
    if executable in {"sed", "awk", "head", "tail"}:
        return executable, "FILTER", executable
    if executable == "cat":
        return "cat", "FORMAT", "cat"
    if executable in {"rg", "grep"}:
        return executable, "SEARCH", executable
    return executable_family, purpose, executable_family


def _node_input_mode(tokens: list[str]) -> str:
    if not tokens:
        return "UNKNOWN"
    executable = PurePosixPath(tokens[0]).name
    args = [token for token in tokens[1:] if token not in {"--"}]
    if executable in {"sed", "awk"}:
        # The first non-option operand is the program; subsequent operands
        # are files.  A lone '-' is stdin.
        operands = [token for token in args if not token.startswith("-")]
        files = operands[1:] if operands else []
        if "-" in files and any(item != "-" for item in files):
            return "MIXED"
        if files and any(item != "-" for item in files):
            return "FILESYSTEM"
        return "STDIN"
    return "UNKNOWN"


_SHELL_OPERATORS = {"|", "&&", "||", ";", ">", ">>", "<", "<<", "(", ")"}
_GRAPH_SOURCE_MAP = {
    ("git", "DIFF"): "GIT_DIFF", ("git", "STATUS"): "GIT_STATUS",
    ("pytest", "TEST"): "TEST_RUNNER", ("python", "TEST"): "TEST_RUNNER",
    ("rg", "SEARCH"): "SEARCH_OUTPUT", ("grep", "SEARCH"): "SEARCH_OUTPUT",
    ("compiler", "BUILD"): "COMPILER_OUTPUT", ("cat", "FORMAT"): "FILE_CONTENT",
}
_GRAPH_SOURCE_CATEGORIES = ("GIT_DIFF", "GIT_STATUS", "TEST_RUNNER", "SEARCH_OUTPUT", "FILE_CONTENT", "COMPILER_OUTPUT", "UNKNOWN")


def _shell_nodes(tokens: list[str]) -> tuple[list[list[str]], list[str]]:
    nodes: list[list[str]] = [[]]
    operators: list[str] = []
    skip_target = False
    for token in tokens:
        if skip_target:
            skip_target = False
            continue
        if token in {">", ">>", "<", "<<"}:
            operators.append(token)
            skip_target = True
            continue
        if token in {"|", "&&", "||", ";"}:
            operators.append(token)
            nodes.append([])
            continue
        if token in {"(", ")"}:
            operators.append(token)
            continue
        nodes[-1].append(token)
    return [node for node in nodes if node], operators


def _shell_graph_metadata(tokens: list[str]) -> dict[str, Any]:
    nodes, operators = _shell_nodes(tokens)
    node_families: list[str] = []
    node_purposes: list[str] = []
    node_roles: list[str] = []
    node_sources: list[str] = []
    node_capabilities: list[str] = []
    node_confidences: list[str] = []
    for node in nodes:
        family, purpose, executable_family = _direct_command(node)
        executable = PurePosixPath(node[0]).name if node else ""
        if executable in {"sed", "awk", "head", "tail"}:
            node_family, node_purpose = executable, "FILTER"
            input_mode = _node_input_mode(node) if executable in {"sed", "awk"} else "STDIN"
            role = "SOURCE_AND_FILTER" if input_mode in {"FILESYSTEM", "MIXED"} else "FILTER" if input_mode == "STDIN" else "UNKNOWN"
            if role == "SOURCE_AND_FILTER":
                node_purpose = "FILE_READ"
        elif executable == "cat":
            node_family, node_purpose, role = "cat", "FORMAT", "FORMATTER"
        else:
            node_family, node_purpose = executable_family, purpose
            role = "SOURCE" if ((family, purpose) in _GRAPH_SOURCE_MAP
                                 or (executable_family, purpose) in _GRAPH_SOURCE_MAP) else "UNKNOWN" if family == "unknown" or executable_family == "unknown" else "CONTROL"
        node_families.append(node_family if node_family in {
            "git", "python", "pytest", "rg", "grep", "sed", "awk", "head", "tail", "cat",
            "shell_builtin", "compiler", "other_known", "unknown",
        } else "unknown")
        node_purposes.append(node_purpose if node_purpose in {
            "DIFF", "STATUS", "TEST", "SEARCH", "FILE_READ", "FILTER", "FORMAT", "BUILD", "DIAGNOSTIC", "OTHER", "UNKNOWN",
        } else "UNKNOWN")
        node_roles.append(role)
        node_confidences.append("STRUCTURAL" if role in {"SOURCE", "SOURCE_AND_FILTER", "FILTER", "CONTROL"} else "UNKNOWN")
        node_capabilities.append("FILTER_ONLY" if role == "FILTER" else "CONTROL_ONLY" if role == "CONTROL" else
                                 "PRODUCES_OUTPUT" if role in {"SOURCE", "SOURCE_AND_FILTER"} and family != "unknown" else "MAY_PRODUCE_OUTPUT" if role == "UNKNOWN" else "UNKNOWN")
        source = (_GRAPH_SOURCE_MAP.get((family, purpose))
                  or _GRAPH_SOURCE_MAP.get((node_family, node_purpose)))
        if role == "SOURCE_AND_FILTER" and node_purpose == "FILE_READ":
            source = "FILE_CONTENT"
        if source:
            node_sources.append(source)
        elif role == "UNKNOWN":
            node_sources.append("UNKNOWN")
    # Unknown executables are never structurally proven shell controls.  Keep
    # the role/capability distinction fail-closed so production serialization
    # cannot collapse an ambiguous node into CONTROL_ONLY.
    for index, family in enumerate(node_families):
        if family == "unknown" and node_roles[index] == "CONTROL":
            node_roles[index] = "UNKNOWN"
            node_confidences[index] = "UNKNOWN"
            node_capabilities[index] = "MAY_PRODUCE_OUTPUT"
    categories = list(dict.fromkeys(node_sources))[:len(_GRAPH_SOURCE_CATEGORIES)]
    source_count = len([source for source in node_sources if source != "UNKNOWN"])
    has_unknown = "UNKNOWN" in node_sources
    if source_count == 1 and not has_unknown:
        output_attribution = "FILTERED_SOURCE" if any(role in {"FILTER", "FORMATTER"} for role in node_roles) else "SINGLE_SOURCE"
    elif source_count > 1:
        output_attribution = "MULTIPLE_POSSIBLE_SOURCES"
    else:
        output_attribution = "UNRESOLVED"
    operator_categories: list[str] = []
    for token in operators:
        category = {"|": "PIPE", "&&": "AND", "||": "OR", ";": "SEQUENCE",
                    ">": "REDIRECTION", ">>": "REDIRECTION", "<": "REDIRECTION", "<<": "REDIRECTION",
                    "(": "SUBSHELL", ")": "SUBSHELL"}.get(token)
        if category and category not in operator_categories:
            operator_categories.append(category)
    if len(operator_categories) > 1:
        normalized_operators = ["MIXED"]
    else:
        normalized_operators = operator_categories or ["UNKNOWN"]
    source_count_total = sum(1 for role in node_roles if role in {"SOURCE", "SOURCE_AND_FILTER"})
    if not source_count_total and nodes and any(capability not in {"FILTER_ONLY", "CONTROL_ONLY"} for capability in node_capabilities):
        node_roles = ["UNKNOWN" if role == "CONTROL" and capability == "MAY_PRODUCE_OUTPUT" else role
                      for role, capability in zip(node_roles, node_capabilities)]
    candidate_count = source_count_total + sum(1 for role, capability in zip(node_roles, node_capabilities)
                                               if role == "UNKNOWN" and capability == "MAY_PRODUCE_OUTPUT")
    candidate_bucket = "1" if candidate_count == 1 else "2" if candidate_count == 2 else "3" if candidate_count == 3 else "4+" if candidate_count >= 4 else "UNKNOWN"
    candidates = []
    for family, purpose, role, capability in zip(node_families, node_purposes, node_roles, node_capabilities):
        if role not in {"SOURCE", "SOURCE_AND_FILTER", "UNKNOWN"}:
            continue
        candidates.append({"source_candidate_role": "SOURCE" if role in {"SOURCE", "SOURCE_AND_FILTER"} else "UNKNOWN",
                           "source_candidate_family": family, "source_candidate_purpose": purpose,
                           "source_candidate_output_capability": capability,
                           "source_candidate_scope": "UNKNOWN",
                           "source_candidate_contribution": "DEFINITE" if source_count_total == 1 and role in {"SOURCE", "SOURCE_AND_FILTER"} else "UNKNOWN" if role == "UNKNOWN" else "POSSIBLE"})
    search_candidates = [candidate for candidate in candidates if candidate["source_candidate_purpose"] == "SEARCH"]
    return {
        "shell_node_count_bucket": "1" if len(nodes) == 1 else "2" if len(nodes) == 2 else "3" if len(nodes) == 3 else "4+" if len(nodes) >= 4 else "UNKNOWN",
        "shell_node_families": node_families, "shell_node_purposes": node_purposes,
        "shell_node_roles": node_roles, "shell_operator_categories": normalized_operators,
        "shell_source_nodes": [{"family": family, "purpose": purpose, "role": role}
                               for family, purpose, role in zip(node_families, node_purposes, node_roles)
                               if role == "SOURCE"],
        "shell_node_output_capabilities": node_capabilities,
        "shell_node_role_confidences": node_confidences,
        "source_candidate_count_bucket": candidate_bucket,
        "source_candidates": candidates,
        "search_source_count_bucket": ("1" if len(search_candidates) == 1 else "2" if len(search_candidates) == 2 else "3" if len(search_candidates) == 3 else "4+" if len(search_candidates) >= 4 else "UNKNOWN"),
        "search_source_families": [candidate["source_candidate_family"] for candidate in search_candidates],
        "search_source_scope_categories": [candidate["source_candidate_scope"] for candidate in search_candidates],
        "search_source_contribution_categories": [candidate["source_candidate_contribution"] for candidate in search_candidates],
        "possible_output_source_categories": categories,
        "shell_output_attribution": output_attribution,
    }


def _graph_file_provenance(
    node: list[str], *, workspace_root: Path | None,
    owned_files: list[str] | None = None, run_root: Path | None = None,
    package_root: Path | None = None, host_runtime_root: Path | None = None,
    temp_root: Path | None = None, dependency_root: Path | None = None,
    system_root: Path | None = None,
) -> dict[str, Any]:
    """Return bounded provenance for a text-processor file operand.

    This deliberately operates on the already parsed node and never exposes
    the operand itself in the graph/evidence representation.
    """
    if not node or PurePosixPath(node[0]).name not in {"sed", "awk"}:
        return {"scope": "UNKNOWN", "origin": "UNKNOWN", "bound_package": False,
                "bound_worker": False, "bound_fixture": False, "generated": False,
                "status": "OPERAND_UNAVAILABLE", "context_status": "UNKNOWN"}
    args = [token for token in node[1:] if token not in {"--"}]
    operands = [token for token in args if not token.startswith("-")]
    files = operands[1:] if operands else []
    files = [item for item in files if item != "-"]
    if not files:
        return {"scope": "UNKNOWN", "origin": "UNKNOWN", "bound_package": False,
                "bound_worker": False, "bound_fixture": False, "generated": False,
                "status": "OPERAND_UNAVAILABLE", "context_status": "UNKNOWN"}
    owned = set(owned_files or ())
    scopes: list[dict[str, Any]] = []
    for raw in files:
        candidate = Path(raw)
        if workspace_root is not None and not candidate.is_absolute():
            candidate = workspace_root / candidate
        provenance = _file_content_provenance(
            candidate, workspace_root=workspace_root, run_root=run_root,
            host_runtime_root=host_runtime_root, temp_root=temp_root,
            dependency_root=dependency_root, system_root=system_root,
            package_bound=bool(package_root is not None and candidate.is_relative_to(package_root)),
            worker_output_bound=False,
            test_fixture_bound=bool(workspace_root is not None and raw in owned and raw.startswith("tests/")),
            generated_current_run=False,
        )
        if workspace_root is not None and raw in owned:
            provenance["file_source_scope"] = "WORKSPACE_OWNED"
        scopes.append(provenance)
    scope_values = {item["file_source_scope"] for item in scopes}
    scope = next(iter(scope_values)) if len(scope_values) == 1 else "UNKNOWN"
    origin_values = {item["file_source_origin_category"] for item in scopes}
    origin = next(iter(origin_values)) if len(origin_values) == 1 else "UNKNOWN"
    return {
        "scope": scope, "origin": origin,
        "bound_package": all(item["file_source_bound_to_package"] for item in scopes),
        "bound_worker": all(item["file_source_bound_to_worker_output"] for item in scopes),
        "bound_fixture": all(item["file_source_bound_to_test_fixture"] for item in scopes),
        "generated": all(item["file_source_generated_in_current_run"] for item in scopes),
        "status": "RESOLVED" if scope != "UNKNOWN" else "PARTIAL",
        "context_status": "OWNED_CONTEXT_AVAILABLE" if owned else "RUN_CONTEXT_AVAILABLE" if run_root is not None else "NO_CONTEXT",
    }


def _pipeline_metadata(tokens: list[str]) -> dict[str, Any]:
    graph = _shell_graph_metadata(tokens)
    nodes, operators = _shell_nodes(tokens)
    stages = [_pipeline_stage_metadata(node) for node in nodes]
    families = [family for family, _, _ in stages]
    purposes = [purpose for _, purpose, _ in stages]
    terminal_family, terminal_purpose, _ = stages[-1] if stages else ("unknown", "UNKNOWN", "unknown")
    source = next((item for item in graph["possible_output_source_categories"] if item != "UNKNOWN"), "UNKNOWN")
    pipe_with_compound = any(item in {"&&", "||", ";", "(", ")"} for item in operators)
    has_redirection = any(item in {">", ">>", "<", "<<"} for item in operators)
    attribution = "UPSTREAM_SOURCE" if graph["shell_output_attribution"] == "FILTERED_SOURCE" and source != "UNKNOWN" and not has_redirection and not pipe_with_compound else "MULTI_STAGE" if len(nodes) > 1 and pipe_with_compound else "UNRESOLVED"
    return {
        "pipeline_stage_count_bucket": "2" if len(nodes) == 2 else "3" if len(nodes) == 3 else "4+" if len(nodes) >= 4 else "UNKNOWN",
        "pipeline_stage_families": families, "pipeline_stage_purposes": purposes,
        "pipeline_operator_category": "PIPE_WITH_COMPOUND" if pipe_with_compound else "PIPE_WITH_REDIRECTION" if has_redirection else "PIPE_ONLY",
        "pipeline_terminal_family": terminal_family if not pipe_with_compound and not has_redirection else "unknown",
        "pipeline_terminal_purpose": terminal_purpose if not pipe_with_compound and not has_redirection else "UNKNOWN",
        "pipeline_upstream_source_category": source if source != "UNKNOWN" and not pipe_with_compound and not has_redirection else "UNKNOWN",
        "pipeline_output_attribution": attribution,
    }


def _command_metadata(command: Any, *, present: bool = True, depth: int = 0) -> dict[str, Any]:
    """Classify command structure without retaining command or argv text."""
    unknown = {
        "command_family": "unknown", "command_purpose": "UNKNOWN",
        "command_shape_category": "UNKNOWN", "executable_family": "unknown",
        "wrapper_depth_bucket": "UNKNOWN", "argv_count_bucket": "UNKNOWN",
        "command_attribution_cause": "UNKNOWN",
        "pipeline_stage_count_bucket": "UNKNOWN", "pipeline_stage_families": [],
        "pipeline_stage_purposes": [], "pipeline_operator_category": "UNKNOWN",
        "pipeline_terminal_family": "unknown", "pipeline_terminal_purpose": "UNKNOWN",
        "pipeline_upstream_source_category": "UNKNOWN",
        "pipeline_output_attribution": "UNRESOLVED",
        "shell_node_count_bucket": "UNKNOWN", "shell_node_families": [],
        "shell_node_purposes": [], "shell_node_roles": [],
        "shell_operator_categories": ["UNKNOWN"],
        "possible_output_source_categories": [], "shell_output_attribution": "UNRESOLVED",
    }
    if not present:
        return {**unknown, "command_attribution_cause": "COMMAND_METADATA_MISSING"}
    if not isinstance(command, str):
        return {**unknown, "command_attribution_cause": "UNSUPPORTED_SCHEMA_SHAPE"}
    if not command.strip():
        return {**unknown, "argv_count_bucket": "0",
                "command_attribution_cause": "COMMAND_METADATA_EMPTY"}
    try:
        tokens = _tokenize_command(command)
    except ValueError:
        return {**unknown, "command_attribution_cause": "PARSE_FAILURE"}
    if not tokens:
        return {**unknown, "argv_count_bucket": "0",
                "command_attribution_cause": "COMMAND_METADATA_EMPTY"}
    operators = set(tokens).intersection(_SHELL_OPERATORS)
    if "\n" in command:
        operators.add(";")
    if operators:
        shape = ("PIPELINE" if "|" in operators else "COMPOUND_AND" if "&&" in operators
                 else "COMPOUND_OR" if "||" in operators else "SUBSHELL" if operators.intersection({"(", ")"}) else "UNKNOWN")
        graph = _shell_graph_metadata(tokens)
        pipeline = _pipeline_metadata(tokens) if "|" in operators else {}
        return {**unknown, **graph, **pipeline, "command_family": "mixed", "command_purpose": "OTHER",
                "command_shape_category": shape,
                "wrapper_depth_bucket": "2+" if depth >= 2 else str(depth),
                "argv_count_bucket": _argv_bucket(len(tokens)),
                "command_attribution_cause": "SHELL_COMPOUND"}
    executable = PurePosixPath(tokens[0]).name
    if executable in {"bash", "sh"}:
        flag_index = next((index for index, token in enumerate(tokens[1:], 1)
                           if token in {"-c", "-lc", "-cl"}), None)
        if flag_index is not None:
            if flag_index + 1 >= len(tokens) or depth >= 2:
                return {**unknown, "command_shape_category": "SHELL_C",
                        "executable_family": executable,
                        "wrapper_depth_bucket": "2+" if depth >= 2 else str(depth + 1),
                        "argv_count_bucket": _argv_bucket(len(tokens)),
                        "command_attribution_cause": "SHELL_WRAPPED"}
            inner = _command_metadata(tokens[flag_index + 1], depth=depth + 1)
            inner_shape = inner["command_shape_category"]
            return {**inner, "command_shape_category": inner_shape if inner_shape in {
                        "PIPELINE", "COMPOUND_AND", "COMPOUND_OR", "SUBSHELL"} else "SHELL_C",
                    "wrapper_depth_bucket": "2+" if depth + 1 >= 2 else "1",
                    "command_attribution_cause": "SHELL_COMPOUND" if inner_shape in {
                        "PIPELINE", "COMPOUND_AND", "COMPOUND_OR", "SUBSHELL"} else "SHELL_WRAPPED"}
        family, purpose, executable_family = _direct_command(tokens)
        return {**unknown, "command_family": family, "command_purpose": purpose,
                "command_shape_category": "SHELL_SCRIPT", "executable_family": executable_family,
                "wrapper_depth_bucket": str(depth), "argv_count_bucket": _argv_bucket(len(tokens)),
                "command_attribution_cause": "SHELL_WRAPPED"}
    family, purpose, executable_family = _direct_command(tokens)
    interpreter_script = executable in {"python", "python3"} and len(tokens) > 1 and not tokens[1].startswith("-")
    cause = "SCRIPT_INTERPRETER" if interpreter_script else "DIRECT_EXEC_UNRECOGNIZED" if family == "unknown" else "OTHER"
    return {**unknown, **_shell_graph_metadata(tokens), "command_family": family, "command_purpose": purpose,
            "command_shape_category": "INTERPRETER_SCRIPT" if interpreter_script else "DIRECT_EXEC",
            "executable_family": executable_family, "wrapper_depth_bucket": str(depth),
            "argv_count_bucket": _argv_bucket(len(tokens)), "command_attribution_cause": cause}


def _safe_owned_paths(root: Path | None, owned_files: list[str] | None) -> list[str]:
    if root is None:
        return []
    return [relative for relative in _safe_scope(owned_files or [])
            if (root / relative).is_file() and not (root / relative).is_symlink()]


def _inner_graph_tokens(command: Any) -> list[str]:
    """Unwrap shell ``-c`` layers for in-memory graph projection only."""
    if isinstance(command, (list, tuple)) and all(isinstance(token, str) for token in command):
        tokens = list(command)
    elif isinstance(command, str):
        try:
            tokens = _tokenize_command(command)
        except (TypeError, ValueError):
            return []
    else:
        return []
    executable = PurePosixPath(tokens[0]).name if tokens else ""
    if executable in {"bash", "sh"}:
        flag_index = next((index for index, token in enumerate(tokens[1:], 1)
                           if token in {"-c", "-lc", "-cl"}), None)
        if flag_index is not None and flag_index + 1 < len(tokens):
            return _inner_graph_tokens(tokens[flag_index + 1])
    return tokens


def _search_provenance(item: Mapping[str, Any], *, workspace_root: Path | None,
                       owned_files: list[str], graph: Mapping[str, Any] | None = None,
                       run_root: Path | None = None, package_root: Path | None = None,
                       host_runtime_root: Path | None = None, temp_root: Path | None = None,
                       dependency_root: Path | None = None, system_root: Path | None = None) -> dict[str, Any]:
    """Derive bounded search input/root/framing metadata without retaining tokens."""
    command = item.get("command")
    if isinstance(command, str):
        try:
            tokens = _tokenize_command(command)
        except (ValueError, TypeError):
            tokens = []
    elif isinstance(command, (list, tuple)) and all(isinstance(token, str) for token in command):
        tokens = list(command)
    else:
        tokens = []
    if graph is None and tokens:
        graph = _shell_graph_metadata(tokens)
    source_nodes = graph.get("shell_source_nodes", []) if isinstance(graph, Mapping) else []
    search_nodes = [node for node in source_nodes if isinstance(node, Mapping)
                    and node.get("purpose") == "SEARCH" and node.get("family") in {"rg", "grep"}]
    executable = search_nodes[0].get("family") if len(search_nodes) == 1 else None
    if executable is None:
        return {"search_input_mode": "UNKNOWN", "search_tool_family": "unknown",
                "search_root_scopes": ["UNKNOWN"], "search_result_record_category": "UNKNOWN",
                "search_result_scope": "UNKNOWN", "search_owned_attribution": "UNRESOLVED",
                "search_framing_category": "UNKNOWN", "search_bound_to_package_scope": False,
                "search_bound_to_owned_workspace": False, "search_generated_in_current_run": False}
    executable_index = next((index for index, token in enumerate(tokens)
                             if token.rsplit("/", 1)[-1] == executable), None)
    if executable_index is None:
        return {"search_input_mode": "UNKNOWN", "search_tool_family": executable,
                "search_root_scopes": ["UNKNOWN"], "search_result_record_category": "UNKNOWN",
                "search_result_scope": "UNKNOWN", "search_owned_attribution": "UNRESOLVED",
                "search_framing_category": "UNKNOWN", "search_bound_to_package_scope": False,
                "search_bound_to_owned_workspace": False, "search_generated_in_current_run": False}
    args = tokens[executable_index + 1:]
    roots = [arg for arg in args if arg not in {"-", "--"} and not arg.startswith("-")]
    explicit_roots = roots[1:] if roots else []
    input_mode = "STDIN" if "-" in args and not any(root != "-" for root in explicit_roots) else "EXPLICIT_ROOT" if explicit_roots else "DEFAULT_WORKDIR"
    if "-" in args and any(root != "-" for root in explicit_roots):
        input_mode = "MIXED"
    root_scopes: set[str] = set()
    if input_mode in {"EXPLICIT_ROOT", "MIXED"}:
        if not roots:
            root_scopes.add("WORKSPACE_OWNED" if workspace_root is not None and owned_files else "WORKSPACE_UNOWNED" if workspace_root is not None else "UNKNOWN")
        elif workspace_root is None:
            root_scopes.add("UNKNOWN")
        else:
            for raw in explicit_roots:
                if raw == "-":
                    continue
                try:
                    candidate = (workspace_root / raw).resolve(strict=False) if not Path(raw).is_absolute() else Path(raw).resolve(strict=False)
                    base = workspace_root.resolve(strict=False)
                    if candidate != base and base not in candidate.parents:
                        root_scopes.add("EXTERNAL")
                    elif any((base / relative).resolve(strict=False) == candidate or
                             candidate in (base / relative).resolve(strict=False).parents for relative in owned_files):
                        root_scopes.add("WORKSPACE_OWNED")
                    else:
                        root_scopes.add("WORKSPACE_UNOWNED")
                except (OSError, RuntimeError, ValueError):
                    root_scopes.add("UNKNOWN")
    if input_mode == "DEFAULT_WORKDIR":
        root_scopes.add("WORKSPACE_OWNED" if workspace_root is not None and owned_files else "WORKSPACE_UNOWNED" if workspace_root is not None else "UNKNOWN")
    if input_mode == "STDIN":
        root_scopes.add("UNKNOWN")
    if len(root_scopes) > 1:
        root_scope = "MULTIPLE"
    else:
            root_scope = next(iter(root_scopes), "UNKNOWN")
    return {"search_input_mode": input_mode, "search_tool_family": executable,
            "search_root_scopes": [root_scope], "search_result_record_category": "UNKNOWN",
            "search_result_scope": root_scope,
            "search_owned_attribution": "OWNED" if root_scope == "WORKSPACE_OWNED" else "UNOWNED" if root_scope == "WORKSPACE_UNOWNED" else "UNRESOLVED",
            "search_bound_to_package_scope": False, "search_bound_to_owned_workspace": False,
            "search_generated_in_current_run": False}


def _search_record_matches(output: str, *, workspace_root: Path | None,
                           owned_files: list[str]) -> tuple[set[str], str]:
    """Parse known file:line framing and compare only complete source lines."""
    if workspace_root is None:
        return set(), "UNKNOWN"
    matches: set[str] = set(); framing = "UNKNOWN"
    for line in output.splitlines():
        for relative in owned_files:
            prefix = relative + ":"
            if not line.startswith(prefix):
                continue
            remainder = line[len(prefix):]
            parts = remainder.split(":", 2)
            if len(parts) == 2 and parts[0].isdigit():
                framing = "RG_FILE_RECORD" if relative else "UNKNOWN"
                source_line = parts[1]
            elif len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                framing = "RG_FILE_RECORD" if relative else "UNKNOWN"
                source_line = parts[2]
            else:
                continue
            try:
                lines = (workspace_root / relative).read_text(encoding="utf-8", errors="strict").splitlines()
            except (OSError, UnicodeError):
                continue
            if source_line in lines:
                matches.add(relative)
    return matches, framing


def _tool_output_provenance(item: Mapping[str, Any], output: str, *,
                            workspace_root: Path | None,
                            owned_files: list[str] | None,
                            run_root: Path | None = None,
                            package_root: Path | None = None,
                            host_runtime_root: Path | None = None,
                            temp_root: Path | None = None,
                            dependency_root: Path | None = None,
                            system_root: Path | None = None,
                            execution_phase: str = "UNKNOWN",
                            task_binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    command_metadata = _command_metadata(item.get("command"), present="command" in item)
    family = command_metadata["command_family"]
    purpose = command_metadata["command_purpose"]
    if family == "git" and purpose == "DIFF":
        source = "GIT_DIFF"
    elif family == "git" and purpose == "STATUS":
        source = "GIT_STATUS"
    elif purpose == "TEST" and family in {"pytest", "python"}:
        source = "TEST_RUNNER"
    elif family == "compiler":
        source = "COMPILER_DIAGNOSTIC"
    elif family == "grep_rg":
        source = "SEARCH_OUTPUT"
    elif family == "shell_builtin":
        source = "SHELL_STATUS"
    elif family == "other_known":
        source = "EXTERNAL_COMMAND_OUTPUT"
    else:
        source = "UNKNOWN"
    if (command_metadata["pipeline_output_attribution"] == "UPSTREAM_SOURCE"
            and command_metadata["pipeline_upstream_source_category"] != "UNKNOWN"):
        source = command_metadata["pipeline_upstream_source_category"]

    owned_paths = _safe_owned_paths(workspace_root, owned_files)
    exact_source: set[str] = set()
    exact_diff: set[str] = set()
    output_lines = output.splitlines()
    finding_lines = [line for line in output_lines if _SECRET.search(line)]
    for relative in owned_paths:
        try:
            source_lines = (workspace_root / relative).read_text(encoding="utf-8", errors="strict").splitlines()  # type: ignore[operator]
        except (OSError, UnicodeError):
            continue
        if set(finding_lines).intersection(source_lines):
            exact_source.add(relative)
        if source == "GIT_DIFF" and any(line[1:] in source_lines for line in finding_lines
                                         if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))):
            exact_diff.add(relative)
    structural_sources = {source} if source != "UNKNOWN" else set()
    if any(line.startswith("Traceback (most recent call last):") for line in output_lines):
        structural_sources.add("PYTHON_TRACEBACK")
    if any(re.fullmatch(r"=+ .+ (passed|failed|error)s? in [0-9.]+s =+", line) for line in output_lines):
        structural_sources.add("TEST_RUNNER")
    if any(re.fullmatch(r"codex-(status|diagnostic|usage)( .*)?", line, re.I) for line in output_lines):
        structural_sources.add("CODEX_TOOL_DIAGNOSTIC")
    if exact_source and source in {"UNKNOWN", "EXTERNAL_COMMAND_OUTPUT"}:
        structural_sources.discard(source)
        structural_sources.add("FILE_CONTENT_ECHO")
    if len(structural_sources) > 1:
        source = "MIXED"
    elif structural_sources:
        source = next(iter(structural_sources))
    paths = sorted(exact_diff or exact_source)
    if exact_diff:
        owned_category = "EXACT_DIFF_LINE"
    elif exact_source:
        owned_category = ("EXACT_TEST_FIXTURE_LINE" if all(
            path == "tests" or path.startswith("tests/") for path in exact_source) else "EXACT_SOURCE_LINE")
    else:
        owned_category = "NONE" if workspace_root is not None else "UNKNOWN"
    if paths:
        assessment = "OWNED_NONCREDENTIAL_ECHO"
        if owned_category == "EXACT_SOURCE_LINE" and _hardcoded_credential_findings(workspace_root, paths):  # type: ignore[arg-type]
            assessment = "CONFIRMED_CONTENT_SECRET"
    elif source == "CODEX_TOOL_DIAGNOSTIC":
        assessment = "TOOL_DIAGNOSTIC_NONCREDENTIAL"
    else:
        assessment = "UNRESOLVED"
    search_metadata = _search_provenance(
        item, workspace_root=workspace_root, owned_files=owned_paths,
        graph=command_metadata, run_root=run_root, package_root=package_root,
        host_runtime_root=host_runtime_root, temp_root=temp_root,
        dependency_root=dependency_root, system_root=system_root,
    )
    for candidate in command_metadata.get("source_candidates", []):
        if candidate.get("source_candidate_purpose") == "SEARCH":
            scopes = search_metadata.get("search_root_scopes", ["UNKNOWN"])
            candidate["source_candidate_scope"] = scopes[0] if len(scopes) == 1 else "UNKNOWN"
    # Project file-source scope onto the canonical graph candidates.  The
    # graph remains the source of node identity; this only enriches each
    # already-selected FILE_CONTENT candidate with bounded scope metadata.
    command_value = item.get("command")
    graph_tokens = _inner_graph_tokens(command_value)
    graph_nodes, _ = _shell_nodes(graph_tokens)
    candidate_index = 0
    for node in graph_nodes:
        file_provenance = _graph_file_provenance(
            node, workspace_root=workspace_root, owned_files=owned_paths,
            run_root=run_root, package_root=package_root,
            host_runtime_root=host_runtime_root, temp_root=temp_root,
            dependency_root=dependency_root, system_root=system_root,
        )
        if file_provenance["scope"] == "UNKNOWN" and file_provenance["origin"] == "UNKNOWN":
            continue
        candidates = command_metadata.get("source_candidates", [])
        while candidate_index < len(candidates) and candidates[candidate_index].get("source_candidate_purpose") != "FILE_READ":
            candidate_index += 1
        if candidate_index < len(candidates):
            candidate = candidates[candidate_index]
            if candidate.get("source_candidate_family") == PurePosixPath(node[0]).name:
                candidate.update({
                    "source_candidate_scope": file_provenance["scope"],
                    "file_source_scope": file_provenance["scope"],
                    "file_source_origin_category": file_provenance["origin"],
                    "file_source_bound_to_package": file_provenance["bound_package"],
                    "file_source_bound_to_worker_output": file_provenance["bound_worker"],
                    "file_source_bound_to_test_fixture": file_provenance["bound_fixture"],
                    "file_source_generated_in_current_run": file_provenance["generated"],
                    "file_provenance_status": file_provenance["status"],
                    "file_scope_context_status": file_provenance["context_status"],
                })
                candidate_index += 1
    if source == "SEARCH_OUTPUT":
        search_matches, framing = _search_record_matches(output, workspace_root=workspace_root, owned_files=owned_paths)
        if search_matches:
            paths = sorted(search_matches)
            owned_category = "EXACT_SOURCE_LINE"
            assessment = "OWNED_NONCREDENTIAL_ECHO"
            search_metadata.update({"search_result_record_category": "FILE_MATCH",
                                    "search_result_scope": "WORKSPACE_OWNED",
                                    "search_owned_attribution": "OWNED",
                                    "search_framing_category": framing,
                                    "search_bound_to_owned_workspace": True})
        elif framing == "UNKNOWN":
            search_metadata.update({"search_result_record_category": "UNKNOWN",
                                    "search_owned_attribution": "UNRESOLVED"})

    bounded_source = _bounded_command_output_source(
        command_metadata, execution_phase, task_binding=task_binding,
    )
    return {
        **command_metadata,
        **search_metadata,
        **bounded_source,
        "tool_output_source_category": source,
        "owned_workspace_match": bool(paths), "owned_relative_paths": paths,
        "owned_source_category": owned_category,
        "credential_exposure_assessment": assessment,
    }


def _bounded_command_output_source(
    command_metadata: Mapping[str, Any], execution_phase: str, *,
    task_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a command-output event to a closed semantic source taxonomy."""
    candidates = command_metadata.get("source_candidates")
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    if candidate_count > 1:
        source_id, source_family = "WORKER_SHELL_EXECUTION", "SHELL"
        resolution = "MULTIPLE"
    elif candidate_count == 1:
        purpose = command_metadata.get("command_purpose")
        family = command_metadata.get("command_family")
        if purpose == "TEST":
            source_id, source_family = "WORKER_TEST_EXECUTION", "TEST"
        elif purpose == "FILE_READ":
            source_id, source_family = "WORKER_FILE_OPERATION", "FILE"
        elif purpose in {"COMPILE", "DIFF", "STATUS"}:
            source_id, source_family = "WORKER_VALIDATION_EXECUTION", "VALIDATION"
        elif family == "unknown" or purpose == "UNKNOWN":
            source_id, source_family = "WORKER_UNKNOWN_EXECUTION", "UNKNOWN"
        elif family in {None, ""}:
            source_id, source_family = "WORKER_OTHER_EXECUTION", "OTHER"
        else:
            source_id, source_family = "WORKER_TOOL_EXECUTION", "TOOL"
        resolution = "EXACT" if source_family != "UNKNOWN" else "UNKNOWN"
    else:
        source_id, source_family, resolution = "WORKER_UNKNOWN_EXECUTION", "UNKNOWN", "UNKNOWN"
    phase = execution_phase if execution_phase in {"STARTED", "COMPLETED", "FAILED"} else "UNKNOWN"
    capability, data_origin, intent = _bounded_tool_semantics(command_metadata, source_id)
    operation_class_id = _registered_operation_class(command_metadata, source_id)
    scope_binding = _bounded_tool_task_scope_binding(
        capability=capability, context=task_binding,
    )
    return {
        "security_command_source_id": source_id,
        "security_command_source_family": source_family,
        "security_command_execution_phase": phase,
        "security_source_resolution": resolution,
        "security_source_candidate_count": candidate_count,
        "security_tool_capability": capability,
        "security_tool_data_origin": data_origin,
        "security_tool_operation_intent": intent,
        "security_operation_class_id": operation_class_id,
        **scope_binding,
    }


def _bounded_tool_semantics(
    command_metadata: Mapping[str, Any], source_id: str,
) -> tuple[str, str, str]:
    """Classify an exact command source without retaining tool identity or arguments."""
    family = command_metadata.get("command_family")
    purpose = command_metadata.get("command_purpose")
    if source_id == "WORKER_SHELL_EXECUTION":
        return "SHELL", "GENERATED_PROCESS_OUTPUT", "EXECUTE"
    if family == "git":
        return "GIT", "REPOSITORY_METADATA", "VALIDATE" if purpose in {"DIFF", "STATUS"} else "READ"
    if purpose == "FILE_READ":
        candidates = command_metadata.get("source_candidates")
        scopes = {item.get("source_candidate_scope") for item in candidates
                  if isinstance(item, Mapping)} if isinstance(candidates, list) else set()
        origin = "PROJECT_FILE" if scopes == {"WORKSPACE_OWNED"} else "UNKNOWN"
        return "FILE_READ", origin, "READ"
    if purpose == "SEARCH":
        return "SEARCH", "PROJECT_FILE" if command_metadata.get("search_owned_attribution") == "OWNED" else "UNKNOWN", "SEARCH"
    if purpose == "TEST":
        return "TEST", "TEST_OUTPUT", "VALIDATE"
    if source_id == "WORKER_TOOL_EXECUTION":
        return "OTHER", "GENERATED_PROCESS_OUTPUT", "EXECUTE"
    if source_id == "WORKER_UNKNOWN_EXECUTION":
        return "UNKNOWN", "UNKNOWN", "UNKNOWN"
    return "OTHER", "OTHER", "OTHER"


def _registered_operation_class(command_metadata: Mapping[str, Any], source_id: str) -> str:
    """Return only registry-backed semantic identities, never executable text."""
    # CLI-native events expose only post-execution command material.  That is
    # not a registration authority and must never mint an authorization ID.
    # Broker requests receive their operation_class_id before execution from
    # the registry-owned request envelope instead.
    return "UNBOUND_OPERATION_CLASS"


_TOOL_CAPABILITIES = frozenset({
    "FILE_READ", "FILE_WRITE", "SEARCH", "SHELL", "TEST", "GIT",
    "NETWORK", "MODEL_TOOL", "OTHER", "UNKNOWN",
})


def _bounded_tool_task_scope_binding(
    *, capability: str, context: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Bind only explicit closed policy declarations; missing bindings stay unknown."""
    bounded = {
        "worker_task_id": "UNKNOWN",
        "worker_action_id": "UNKNOWN",
        "tool_operation_policy_id": "UNBOUND_TOOL_POLICY",
        "tool_operation_requirement_binding": "UNKNOWN",
        "tool_scope_binding": "UNKNOWN",
        "tool_scope_authorization_source": "UNKNOWN",
        "tool_operation_required_for_worker_task": "UNKNOWN",
        "tool_operation_within_approved_scope": "UNKNOWN",
    }
    if not isinstance(context, Mapping):
        return bounded
    for field in ("worker_task_id", "worker_action_id", "tool_operation_policy_id"):
        value = context.get(field)
        if (isinstance(value, str) and _SAFE_EVENT_TYPE.fullmatch(value)
                and not _secret_findings(value.encode("utf-8"))):
            bounded[field] = value
    policy = context.get("policy")
    if not isinstance(policy, Mapping) or capability not in _TOOL_CAPABILITIES:
        return bounded
    declared: dict[str, set[str]] = {}
    for key in ("required", "optional", "unrelated", "in_scope", "out_of_scope", "partial"):
        values = policy.get(key)
        declared[key] = ({item for item in values if isinstance(item, str) and item in _TOOL_CAPABILITIES}
                         if isinstance(values, (list, tuple, set, frozenset)) else set())
    if capability in declared["required"]:
        requirement = "REQUIRED"
    elif capability in declared["optional"]:
        requirement = "OPTIONAL"
    elif capability in declared["unrelated"]:
        requirement = "UNRELATED"
    else:
        requirement = "UNKNOWN"
    if capability in declared["in_scope"]:
        scope = "IN_SCOPE"
    elif capability in declared["out_of_scope"]:
        scope = "OUT_OF_SCOPE"
    elif capability in declared["partial"]:
        scope = "PARTIAL"
    else:
        scope = "UNKNOWN"
    authorization = policy.get("authorization_source")
    if authorization not in {"REQUIREMENT", "PLAN_TASK", "OWNED_FILES", "APPROVAL_RECORD", "POLICY", "MULTIPLE"}:
        authorization = "UNKNOWN"
    bounded.update({
        "tool_operation_requirement_binding": requirement,
        "tool_scope_binding": scope,
        "tool_scope_authorization_source": authorization,
        "tool_operation_required_for_worker_task": "YES" if requirement == "REQUIRED" else "NO" if requirement == "UNRELATED" else "UNKNOWN",
        "tool_operation_within_approved_scope": "YES" if scope == "IN_SCOPE" else "NO" if scope == "OUT_OF_SCOPE" else "UNKNOWN",
    })
    return bounded


def _scan_structured_fields(event_type: str, event: Mapping[str, Any], item_type: str | None, *,
                            workspace_root: Path | None = None,
                            owned_files: list[str] | None = None,
                            task_binding: Mapping[str, Any] | None = None) -> None:
    fields: list[tuple[str, Any]] = []
    if event_type == "error":
        fields.append(("ERROR_CONTENT", event["message"]))
    elif event_type == "turn.failed":
        error = event["error"]
        if not isinstance(error, dict):
            raise StructuredEventError("turn.failed error envelope is invalid")
        _require_exact_fields(error, {"message"})
        fields.append(("ERROR_CONTENT", error["message"]))
    elif item_type is not None:
        item = event["item"]
        common = {"id", "type"}
        contracts: dict[str, tuple[set[str], list[tuple[str, str]]]] = {
            "agent_message": (common | {"text"}, [("AGENT_MESSAGE", "text")]),
            "reasoning": (common | {"text"}, [("REASONING", "text")]),
            "command_execution": (common | {"command", "aggregated_output", "exit_code", "status"},
                                  [("COMMAND", "command"), ("TOOL_OUTPUT", "aggregated_output")]),
            "file_change": (common | {"changes", "status"}, [("FILE_CHANGE", "changes")]),
            "mcp_tool_call": (common | {"server", "tool", "arguments", "result", "error", "status"},
                              [("TOOL_INPUT", "arguments"), ("TOOL_OUTPUT", "result"),
                               ("ERROR_CONTENT", "error")]),
            "collab_tool_call": (common | {"tool", "sender_thread_id", "receiver_thread_ids", "prompt", "agents_states", "status"},
                                 [("TOOL_INPUT", "prompt"), ("OTHER_CONTENT", "agents_states")]),
            "web_search": (common | {"query", "action"}, [("WEB_SEARCH", "query"), ("WEB_SEARCH", "action")]),
            "todo_list": (common | {"items"}, [("CONTENT_TEXT", "items")]),
            "error": (common | {"message"}, [("ERROR_CONTENT", "message")]),
        }
        allowed, categorized = contracts[item_type]
        required = set(common)
        if item_type in {"command_execution", "file_change", "mcp_tool_call", "collab_tool_call"}:
            required.add("status")
        _require_exact_fields(item, required, allowed - required)
        fields.extend((category, item[field]) for category, field in categorized if field in item)
    findings: list[dict[str, Any]] = []
    for category, value in fields:
        for content in _content_strings(value):
            provenance = None
            if (category == "TOOL_OUTPUT" and event_type == "item.completed"
                    and item_type == "command_execution" and isinstance(value, str)):
                provenance = _tool_output_provenance(
                    event["item"], value, workspace_root=workspace_root, owned_files=owned_files,
                    execution_phase=("FAILED" if event["item"].get("status") == "failed"
                                     else "COMPLETED" if event["item"].get("status") == "completed"
                                     else "STARTED" if event_type == "item.started" else "UNKNOWN"),
                    task_binding=task_binding,
                )
            findings.extend(_safe_security_findings(
                content, channel="STRUCTURED_JSONL", category=category,
                event_type=event_type, item_type=item_type, provenance=provenance,
            ))
    if findings:
        raise StructuredContentSecurityError({"structured_security_findings": findings})


def _validate_structural_fields(event_type: str, event: Mapping[str, Any], item_type: str | None) -> None:
    if event_type == "thread.started":
        thread_id = event["thread_id"]
        if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 256 or any(ord(c) < 32 for c in thread_id):
            raise StructuredEventError("thread identity is invalid")
    elif event_type == "turn.completed":
        usage = event["usage"]
        required = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"}
        if not isinstance(usage, dict):
            raise StructuredEventError("turn usage envelope is invalid")
        _require_exact_fields(usage, required, {"cache_write_input_tokens"})
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in usage.values()):
            raise StructuredEventError("turn usage value is invalid")
    elif event_type in {"turn.failed", "error"}:
        message = event["message"] if event_type == "error" else event["error"].get("message") if isinstance(event["error"], dict) else None
        if not isinstance(message, str):
            raise StructuredEventError("structured error content shape is invalid")
    if item_type is None:
        return
    item = event["item"]
    if item_type == "file_change" and "changes" in item:
        changes = item["changes"]
        if not isinstance(changes, list):
            raise StructuredEventError("file change list is invalid")
        for change in changes:
            if not isinstance(change, dict):
                raise StructuredEventError("file change entry is invalid")
            _require_exact_fields(change, {"path", "kind"})
            if not isinstance(change["path"], str) or change["kind"] not in {"add", "delete", "update"}:
                raise StructuredEventError("file change entry is invalid")
    if item_type == "todo_list" and "items" in item:
        if not isinstance(item["items"], list):
            raise StructuredEventError("todo list is invalid")
        for todo in item["items"]:
            if not isinstance(todo, dict):
                raise StructuredEventError("todo item is invalid")
            _require_exact_fields(todo, {"text", "completed"})
            if not isinstance(todo["text"], str) or not isinstance(todo["completed"], bool):
                raise StructuredEventError("todo item is invalid")
    if item_type == "mcp_tool_call":
        for name in ("server", "tool"):
            if name in item and (not isinstance(item[name], str) or len(item[name]) > 256):
                raise StructuredEventError("MCP identity is invalid")
        if isinstance(item.get("result"), dict):
            _require_exact_fields(item["result"], {"content", "structured_content"}, {"_meta"})
        if isinstance(item.get("error"), dict):
            _require_exact_fields(item["error"], {"message"})
    if item_type == "collab_tool_call":
        if item.get("tool") not in {"spawn_agent", "send_input", "wait", "close_agent"}:
            raise StructuredEventError("collab tool enum is invalid")
        if "receiver_thread_ids" in item and not isinstance(item["receiver_thread_ids"], list):
            raise StructuredEventError("collab receiver identities are invalid")


def _failure_stage(message: str) -> str:
    if "invalid JSON" in message or "stdout is empty" in message:
        return "JSON_PARSE"
    if "unknown structured event" in message or "event envelope" in message or "event schema" in message:
        return "TOP_LEVEL_EVENT"
    if "unknown structured item" in message:
        return "ITEM_TYPE"
    if "item status" in message:
        return "ITEM_STATUS"
    if "item" in message and any(token in message for token in ("transition", "duplicate", "subtype")):
        return "ITEM_TRANSITION"
    if ("item identity" in message and "subtype" not in message) or "item envelope" in message:
        return "ITEM_IDENTITY"
    if "terminal" in message or "turn.completed ordering" in message:
        return "TERMINAL"
    if "ordering" in message or "follows terminal" in message:
        return "EVENT_ORDER"
    return "UNKNOWN"


def _parse_structured_jsonl(value: bytes, *, workspace_root: Path | None = None,
                            owned_files: list[str] | None = None,
                            worker_task_id: str | None = None,
                            tool_operation_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "counts": {}, "item_counts": {}, "event_type": "UNKNOWN", "item_type": "UNKNOWN",
    }
    try:
        return _parse_structured_jsonl_impl(
            value, context, workspace_root=workspace_root, owned_files=owned_files,
            worker_task_id=worker_task_id, tool_operation_policy=tool_operation_policy,
        )
    except (StructuredEventError, StructuredContentSecurityError) as exc:
        existing = dict(exc.safe_metadata)
        metadata = _structured_metadata(
            counts=context["counts"], item_counts=context["item_counts"],
            unknown_event_count=int(existing.get("unknown_event_count", 0)),
        )
        metadata.update(existing)
        failure_stage = "SECURITY" if isinstance(exc, StructuredContentSecurityError) else _failure_stage(str(exc))
        metadata.setdefault("structured_failure_stage", failure_stage)
        if failure_stage == "JSON_PARSE":
            metadata["parse_error_count"] = 1
        metadata.setdefault("structured_failure_event_type", context["event_type"])
        metadata.setdefault("structured_failure_item_type", context["item_type"])
        metadata.setdefault("structured_failure_status_category", "UNKNOWN")
        metadata.setdefault("structured_expected_status_category", "UNKNOWN")
        exc.safe_metadata = metadata
        raise


def _parse_structured_jsonl_impl(value: bytes, context: dict[str, Any], *,
                                 workspace_root: Path | None = None,
                                 owned_files: list[str] | None = None,
                                 worker_task_id: str | None = None,
                                 tool_operation_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Parse the bounded Codex JSONL lifecycle without retaining event bodies."""
    if not value:
        raise StructuredEventError("structured stdout is empty")
    types: list[str] = []
    counts: dict[str, int] = {}
    item_counts: dict[str, int] = {}
    context["counts"] = counts
    context["item_counts"] = item_counts
    active_items: dict[str, str] = {}
    terminal_items: set[str] = set()
    state = "START"
    terminal_seen = False
    parse_errors = 0
    for raw_line in value.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except (TypeError, ValueError) as exc:
            parse_errors += 1
            raise StructuredEventError("structured stdout contains invalid JSON") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise StructuredEventError(
                "structured event envelope is invalid",
                safe_metadata={
                    "event_type_counts": dict(sorted(counts.items())),
                    "item_type_counts": dict(sorted(item_counts.items())),
                    "unknown_event_count": 0,
                    "unknown_event_type_category": "INVALID_SAFE_IDENTIFIER",
                },
            )
        event_type = event["type"]
        context["event_type"] = event_type if event_type in _SUPPORTED_STRUCTURED_EVENT_SET else "UNKNOWN"
        context["item_type"] = "UNKNOWN"
        if event_type not in _SUPPORTED_STRUCTURED_EVENT_SET:
            metadata: dict[str, Any] = {
                "event_type_counts": dict(sorted(counts.items())),
                "item_type_counts": dict(sorted(item_counts.items())),
                "unknown_event_count": 1,
            }
            if _SAFE_EVENT_TYPE.fullmatch(event_type) and not _secret_findings(event_type.encode("utf-8")):
                metadata["unknown_event_types"] = [event_type]
            else:
                metadata["unknown_event_type_category"] = "INVALID_SAFE_IDENTIFIER"
            raise StructuredEventError("unknown structured event type", safe_metadata=metadata)
        _require_exact_fields(
            event, {"type", *_REQUIRED_STRUCTURED_FIELDS[event_type]}, {"schema_version"},
        )
        version = event.get("schema_version")
        if version is not None and version not in {1, "1", STRUCTURED_EVENT_CONTRACT_VERSION}:
            raise StructuredEventError("incompatible structured event schema")
        item_identity: tuple[str, str] | None = None
        if event_type in {"item.started", "item.updated", "item.completed"}:
            item_identity = _validated_item(
                event_type, event, counts=counts, item_counts=item_counts,
            )
            context["item_type"] = item_identity[1]
        _validate_structural_fields(
            event_type, event, item_identity[1] if item_identity is not None else None,
        )
        _scan_structured_fields(
            event_type, event, item_identity[1] if item_identity is not None else None,
            workspace_root=workspace_root, owned_files=owned_files,
            task_binding={
                "worker_task_id": worker_task_id,
                "worker_action_id": f"COMMAND_EXECUTION_{item_counts.get('command_execution', 0) + 1}",
                "tool_operation_policy_id": (tool_operation_policy or {}).get("policy_id"),
                "policy": tool_operation_policy,
            } if item_identity is not None and item_identity[1] == "command_execution" else None,
        )
        if terminal_seen:
            raise StructuredEventError("event follows terminal event")
        if event_type == "thread.started":
            if state != "START":
                raise StructuredEventError("thread.started ordering violation")
            state = "THREAD"
        elif event_type == "turn.started":
            if state != "THREAD":
                raise StructuredEventError("turn.started ordering violation")
            state = "TURN"
        elif event_type in {"item.started", "item.updated", "item.completed"}:
            if state != "TURN":
                raise StructuredEventError(f"{event_type} ordering violation")
            assert item_identity is not None
            item_id, item_type = item_identity
            if event_type == "item.started":
                if item_type not in _STARTABLE_ITEM_TYPES:
                    raise StructuredEventError("item subtype cannot emit item.started")
                if item_id in active_items or item_id in terminal_items:
                    raise StructuredEventError("duplicate incompatible item identity")
                active_items[item_id] = item_type
            elif event_type == "item.updated":
                if item_type != "todo_list" or active_items.get(item_id) != item_type:
                    raise StructuredEventError("invalid item.updated transition")
            else:
                if item_id in terminal_items:
                    raise StructuredEventError("duplicate item terminal transition")
                if item_id in active_items:
                    if active_items.pop(item_id) != item_type:
                        raise StructuredEventError("item identity subtype mismatch")
                terminal_items.add(item_id)
            item_counts[item_type] = item_counts.get(item_type, 0) + 1
        elif event_type == "turn.completed":
            if state != "TURN" or active_items:
                raise StructuredEventError("turn.completed ordering violation")
            state = "TERMINAL"
            terminal_seen = True
        elif event_type == "turn.failed":
            if state != "TURN":
                raise StructuredEventError("turn.failed ordering violation")
            counts[event_type] = counts.get(event_type, 0) + 1
            raise StructuredEventError(
                "structured turn failed",
                safe_metadata=_structured_metadata(
                    counts=counts, item_counts=item_counts, terminal_status="FAILED",
                    failure_event_type="turn.failed",
                ),
            )
        elif event_type == "error":
            counts[event_type] = counts.get(event_type, 0) + 1
            raise StructuredEventError(
                "structured event stream failed",
                safe_metadata=_structured_metadata(
                    counts=counts, item_counts=item_counts, terminal_status="FAILED",
                    failure_event_type="error",
                ),
            )
        types.append(event_type)
        counts[event_type] = counts.get(event_type, 0) + 1
    if parse_errors or not types or not terminal_seen:
        raise StructuredEventError("structured event stream has no terminal event")
    return _structured_metadata(
        counts=counts, item_counts=item_counts, terminal_status="SUCCEEDED",
    )


def _validate_final_message(path: Path) -> dict[str, Any]:
    """Validate final-message shape while keeping content out of evidence."""
    if not path.is_file() or path.is_symlink():
        raise ProductionWorkerError("final-message file is missing or unsafe")
    size = path.stat().st_size
    if size <= 0:
        raise ProductionWorkerError("final-message file is empty")
    if size > 1024 * 1024:
        raise ProductionWorkerError("final-message file exceeds size bound")
    raw = path.read_bytes()
    findings = _safe_security_findings(raw, channel="FINAL_MESSAGE", category="CONTENT_TEXT")
    if findings:
        raise StructuredContentSecurityError({"security_findings": findings})
    return {"exists": True, "nonempty": True,
            "size_bucket": "1-255" if size < 256 else "256-65535" if size < 65536 else "64K-1M"}


def _validate_final_message_bytes(value: bytes) -> dict[str, Any]:
    size = len(value)
    if size <= 0:
        raise ProductionWorkerError("final-message response is empty")
    if size > 1024 * 1024:
        raise ProductionWorkerError("final-message response exceeds size bound")
    findings = _safe_security_findings(value, channel="FINAL_MESSAGE", category="CONTENT_TEXT")
    if findings:
        raise StructuredContentSecurityError({"security_findings": findings})
    return {"exists": True, "nonempty": True,
            "size_bucket": "1-255" if size < 256 else "256-65535" if size < 65536 else "64K-1M"}


def _persist_private_final_message(path: Path, value: bytes) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ProductionWorkerError("final-message evidence parent is unsafe")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CodexExecutionAdapter:
    """Backend boundary for Codex process execution and JSONL capture."""

    backend_id = EXECUTOR_ID
    contract_version = ADAPTER_CONTRACT_VERSION
    structured_event_contract_version = STRUCTURED_EVENT_CONTRACT_VERSION
    supported_codex_version = SUPPORTED_CODEX_VERSION

    def __init__(self, executor: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
                 *, strict_jsonl: bool = True) -> None:
        self._executor = executor
        self._strict_jsonl = strict_jsonl

    def argv(self, *, root: Path, last_message: Path) -> list[str]:
        _validate_final_message_target(root, last_message)
        argv = ["codex", "--ask-for-approval", "never", "--sandbox", "workspace-write",
                "--cd", str(root), "exec", "--ephemeral", "--json",
                "--output-last-message", str(last_message), "-"]
        _validate_final_message_argv(argv, last_message)
        return argv

    @classmethod
    def validate_version_output(cls, value: bytes) -> str:
        match = re.fullmatch(rb"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\r?\n?", value)
        if match is None:
            raise StructuredEventError("Codex CLI version contract could not be confirmed")
        version = match.group(1).decode("ascii")
        if version != cls.supported_codex_version:
            raise StructuredEventError("Codex CLI version is outside the supported contract")
        return version

    def probe_version(self, executor: Callable[..., subprocess.CompletedProcess[bytes]] | None = None) -> str:
        run = executor or subprocess.run
        try:
            completed = run(["codex", "--version"], input=b"", stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise StructuredEventError("Codex CLI version contract could not be confirmed") from exc
        if int(completed.returncode) != 0:
            raise StructuredEventError("Codex CLI version contract could not be confirmed")
        return self.validate_version_output(bytes(completed.stdout or b""))

    def run(self, *, root: Path, prompt: bytes, last_message: Path, timeout: int,
            cancel_path: Path) -> tuple[bytes, bytes, dict[str, Any], dict[str, Any]]:
        argv = self.argv(root=root, last_message=last_message)
        if self._executor is None:
            codex_version = self.probe_version()
            stdout, stderr, process = _run_managed_child(
                argv, root=root, prompt=prompt, timeout=timeout, cancel_path=cancel_path
            )
            strict = self._strict_jsonl
        else:
            completed = self._executor(argv, input=prompt, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, check=False, timeout=timeout)
            stdout = bytes(completed.stdout or b"")
            stderr = bytes(completed.stderr or b"")
            process = {
                "schema_version": "orchestration.production-worker-process.v1",
                "pid": None, "process_group_id": None, "started_at": None, "ended_at": None,
                "termination": "EXITED", "requested_signal": None,
                "exit_code": int(completed.returncode), "signal": None,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(), "hard_stop": True,
            }
            strict = self._strict_jsonl
        return stdout, stderr, process, {"contract_version": self.contract_version,
                                         "backend": self.backend_id, "strict": strict,
                                         "structured_event_contract_version": self.structured_event_contract_version,
                                         "codex_version": codex_version if self._executor is None else None}


def _validate_final_message_target(root: Path, target: Path) -> dict[str, Any]:
    """Validate the private artifact write boundary without exposing its path."""
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink()
            or root.resolve() != root or not target.is_absolute()):
        raise ProductionWorkerError("final-message target binding is unsafe")
    try:
        target.relative_to(root)
        target.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ProductionWorkerError("final-message target is outside workspace-write scope") from exc
    parent = target.parent
    if not parent.is_dir() or parent.is_symlink() or not os.access(parent, os.W_OK):
        raise ProductionWorkerError("final-message target parent is missing or unwritable")
    parent_stat = parent.stat()
    if parent_stat.st_uid != os.getuid():
        raise ProductionWorkerError("final-message target parent ownership or mode is unsafe")
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise ProductionWorkerError("final-message target is unsafe")
    return {
        "target_scope": "WORKSPACE", "target_parent_exists": True,
        "target_parent_writable": True, "target_within_workspace": True,
        "target_within_allowed_write_scope": True,
    }


def _validate_final_message_argv(argv: list[str], expected_target: Path) -> None:
    positions = [index for index, value in enumerate(argv) if value == "--output-last-message"]
    if len(positions) != 1:
        raise ProductionWorkerError("final-message flag binding is invalid")
    position = positions[0]
    if position + 1 >= len(argv) or argv[position + 1] != str(expected_target):
        raise ProductionWorkerError("final-message target binding mismatch")
    if "exec" not in argv or position < argv.index("exec") or argv[-1:] != ["-"]:
        raise ProductionWorkerError("final-message argument order is invalid")


def _safe_diff_path(root: Path, value: str) -> str | None:
    """Return a validated repo-relative diff path, never the raw header token."""
    token = value.strip().split("\t", 1)[0].split(" ", 1)[0]
    if token == "/dev/null":
        return None
    if not token or any(ord(char) < 32 for char in token) or token.startswith("/"):
        return None
    if token.startswith(("a/", "b/")):
        token = token[2:]
    candidate = PurePosixPath(token)
    if candidate.is_absolute() or ".." in candidate.parts or "" in candidate.parts:
        return None
    normalized = candidate.as_posix()
    try:
        resolved = (root / Path(*candidate.parts)).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return normalized


def _diff_file_type(path: str | None) -> str:
    if path is None:
        return "DEV_NULL"
    suffix = PurePosixPath(path).suffix.casefold()
    return {".py": "PYTHON", ".json": "JSON", ".md": "MARKDOWN", ".sh": "SHELL"}.get(suffix, "OTHER")


def _parse_unified_diff_lines(text: str, *, workspace_root: Path) -> dict[int, dict[str, Any]]:
    """Parse only standard unified/git diff framing into line-offset metadata."""
    metadata: dict[int, dict[str, Any]] = {}
    old_path: str | None = None; new_path: str | None = None
    old_valid = new_valid = False; hunk = False; hunk_line = 0; state_unknown = False
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n"); record: dict[str, Any] | None = None
        if content.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", content)
            old_path = _safe_diff_path(workspace_root, "a/" + match.group(1)) if match else None
            new_path = _safe_diff_path(workspace_root, "b/" + match.group(2)) if match else None
            old_valid = bool(match and (old_path is not None or match.group(1) == "/dev/null"))
            new_valid = bool(match and (new_path is not None or match.group(2) == "/dev/null"))
            hunk = False; hunk_line = 0; state_unknown = not (old_valid and new_valid)
        elif content.startswith("--- "):
            token = content[4:]
            old_path = _safe_diff_path(workspace_root, token)
            old_valid = old_path is not None or token.strip().split("\t", 1)[0] == "/dev/null"
            hunk = False
        elif content.startswith("+++ "):
            token = content[4:]
            new_path = _safe_diff_path(workspace_root, token)
            new_valid = new_path is not None or token.strip().split("\t", 1)[0] == "/dev/null"
            hunk = False
        elif re.match(r"^@@ .* @@(?:.*)?$", content):
            hunk = bool(old_valid and new_valid and (old_path is not None or new_path is not None))
            hunk_line = 0
            state_unknown = not hunk
        elif hunk and content[:1] in {"+", "-", " "}:
            hunk_line += 1
            if not state_unknown:
                marker = content[:1]
                path = new_path if marker == "+" else old_path if marker == "-" else (new_path or old_path)
                record = {
                    "diff_target_relative_paths": [path] if path else [],
                    "diff_change_category": "ADD" if marker == "+" else "REMOVE" if marker == "-" else "CONTEXT",
                    "diff_file_type": _diff_file_type(path),
                    "diff_hunk_position_bucket": "1-15" if hunk_line < 16 else "16-31" if hunk_line < 32 else "32+",
                }
        if record is not None:
            metadata[offset] = record
        offset += len(line)
    return metadata


def _secret_findings(value: bytes) -> dict[str, int]:
    findings: dict[str, int] = {}
    text = value.decode("utf-8", "replace")
    for match in _SECRET.finditer(text):
        kind = match.group(1).lower().replace("_", "-")
        findings[kind] = findings.get(kind, 0) + 1
    return findings


def _secret_classifications(value: bytes) -> dict[str, dict[str, int]]:
    """Return aggregate, non-sensitive diagnostics for secret-like matches."""
    result: dict[str, dict[str, int]] = {}
    text = value.decode("utf-8", "replace")
    for match in _SECRET.finditer(text):
        kind = match.group(1).lower().replace("_", "-")
        candidate = match.group(2).strip()
        folded = candidate.casefold()
        if folded in {"", "none", "null", "unset", "not-set", "not_set", "missing"}:
            classification = "PLACEHOLDER_LITERAL"
        elif folded in {"redacted", "[redacted]", "<redacted>", "hidden", "masked"} or set(candidate) == {"*"}:
            classification = "REDACTED_LITERAL"
        else:
            length = len(candidate)
            length_bucket = "1-15" if length < 16 else "16-31" if length < 32 else "32+"
            if candidate.isalnum():
                chars = "alnum"
            elif all(char.isalnum() or char in "-_" for char in candidate):
                chars = "mixed"
            else:
                chars = "other"
            classification = f"NON_PLACEHOLDER_{length_bucket}_{chars}"
        by_kind = result.setdefault(kind, {})
        by_kind[classification] = by_kind.get(classification, 0) + 1
    return result


def _literal_length_bucket(value: str | bytes) -> str:
    length = len(value)
    return "1-15" if length < 16 else "16-31" if length < 32 else "32+"


def _credential_identifier_category(identifier: str) -> str | None:
    match = _CREDENTIAL_IDENTIFIER.search(identifier.replace(".", "_"))
    return match.group(1).lower().replace("-", "_") if match else None


def _hardcoded_credential_findings(root: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    """Inspect Python ASTs without retaining literal values or fingerprints."""
    findings: list[dict[str, Any]] = []

    def record(relative: str, node: ast.AST, identifier: str, value: ast.AST | None) -> None:
        category = _credential_identifier_category(identifier)
        if category is None or not isinstance(value, ast.Constant) or not isinstance(value.value, (str, bytes)):
            return
        literal = value.value
        folded = literal.decode("utf-8", "replace").casefold() if isinstance(literal, bytes) else literal.casefold()
        if folded in {"", "none", "null", "unset", "not-set", "not_set", "missing", "redacted", "[redacted]"}:
            return
        findings.append({
            "relative_path": relative,
            "ast_node_category": type(node).__name__,
            "identifier_category": category,
            "literal_length_bucket": _literal_length_bucket(literal),
            "hardcoded": True,
        })

    for relative in sorted(set(changed_files)):
        if not relative.endswith(".py"):
            continue
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8", errors="strict")
            tree = ast.parse(source, filename=relative)
        except (OSError, UnicodeError, SyntaxError):
            findings.append({
                "relative_path": relative, "ast_node_category": "UNPARSEABLE_PYTHON",
                "identifier_category": "UNKNOWN", "literal_length_bucket": "UNKNOWN", "hardcoded": False,
            })
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    record(relative, node, ast.unparse(target), node.value)
            elif isinstance(node, ast.AnnAssign):
                record(relative, node, ast.unparse(node.target), node.value)
            elif isinstance(node, ast.NamedExpr):
                record(relative, node, ast.unparse(node.target), node.value)
            elif isinstance(node, ast.keyword) and node.arg:
                record(relative, node, node.arg, node.value)
            elif isinstance(node, ast.Dict):
                for key, item in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        record(relative, node, key.value, item)
    return findings


def _task_allows_secret_handling(request: WorkerRequest) -> bool:
    capabilities = request.extra_context.get("task_capabilities", [])
    return isinstance(capabilities, list) and "secret_handling" in capabilities


def _secret_origin_classifications(
    value: bytes,
    *,
    channel: str,
    prompt: bytes = b"",
    last_message: bytes = b"",
    prompt_sources: Mapping[str, bytes] | None = None,
    workspace_root: Path | None = None,
    owned_files: list[str] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Classify secret-like matches without retaining values or fingerprints.

    Comparisons happen only in memory.  Environment values are compared as
    exact candidates and neither names nor values (nor hashes) enter evidence.
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}
    prompt_text = prompt.decode("utf-8", "replace")
    last_text = last_message.decode("utf-8", "replace")
    environment_values = tuple(os.environ.values())

    wrapper_chars = " \t\r\n\"'`[](){}<>.,;:"

    def syntax_normalize(item: str) -> str:
        """Canonicalize wrappers only; never use substring or fuzzy matching."""
        normalized = item.strip()
        previous = None
        while normalized != previous:
            previous = normalized
            normalized = re.sub(r"\\([\\\"'`\[\](){}<>.,;:])", r"\1", normalized)
            normalized = normalized.strip(wrapper_chars)
        return normalized

    def finding_in(text: str, kind: str, delimiter: str, candidate: str) -> bool:
        target = syntax_normalize(candidate)
        if not target:
            return False
        for item in _SECRET.finditer(text):
            item_kind = item.group(1).lower().replace("_", "-")
            between = text[item.end(1):item.start(2)]
            item_delimiter = ":" if ":" in between else "=" if "=" in between else ""
            if item_kind == kind and item_delimiter == delimiter and syntax_normalize(item.group(2)) == target:
                return True
        return False

    def ast_value_matches(node: ast.AST | None, candidate: str) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            value = node.value.decode("utf-8", "replace") if isinstance(node.value, bytes) else node.value
        else:
            try:
                value = ast.unparse(node)
            except (ValueError, TypeError):
                return False
        return syntax_normalize(value) == syntax_normalize(candidate)

    def python_source_matches(text: str, kind: str, delimiter: str, candidate: str) -> bool:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return False
        expected = kind.replace("-", "_")
        for node in ast.walk(tree):
            pairs: list[tuple[str, ast.AST | None, str]] = []
            if isinstance(node, ast.Assign):
                pairs.extend((ast.unparse(target), node.value, "=") for target in node.targets)
            elif isinstance(node, ast.AnnAssign):
                pairs.append((ast.unparse(node.target), node.value, "="))
            elif isinstance(node, ast.NamedExpr):
                pairs.append((ast.unparse(node.target), node.value, "="))
            elif isinstance(node, ast.keyword) and node.arg:
                pairs.append((node.arg, node.value, "="))
            elif isinstance(node, ast.Dict):
                for key, item in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        pairs.append((key.value, item, ":"))
            for identifier, item, item_delimiter in pairs:
                if (item_delimiter == delimiter and _credential_identifier_category(identifier) == expected
                        and ast_value_matches(item, candidate)):
                    return True
        return False

    def owned_source_matches(relative: str, text: str, kind: str, delimiter: str, candidate: str) -> bool:
        if relative.endswith(".py"):
            return python_source_matches(text, kind, delimiter, candidate)
        return finding_in(text, kind, delimiter, candidate)

    def line_structure(line: str, match: re.Match[str], delimiter: str, line_start: int) -> dict[str, Any]:
        ansi_present = bool(re.search(r"\x1b\[[0-?]*[ -/]*[@-~]", line))
        plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
        relative_start = max(0, match.start() - line_start)
        relative_end = min(len(line), match.end() - line_start)
        prefix = line[:relative_start].strip()
        suffix = line[relative_end:].strip()
        if not prefix and not suffix:
            scope = "WHOLE_LINE_KEY_VALUE"
        elif prefix and not suffix:
            scope = "PREFIXED_KEY_VALUE"
        elif prefix or suffix:
            scope = "EMBEDDED_KEY_VALUE"
        else:
            scope = "OTHER"
        structure = "PLAIN_KEY_VALUE" if scope == "WHOLE_LINE_KEY_VALUE" else "UNCLASSIFIED"
        known_cli_frame = False
        if plain.startswith("{") and plain.endswith("}"):
            try:
                structure = "JSON_KEY_VALUE" if isinstance(json.loads(plain), dict) else "UNCLASSIFIED"
            except json.JSONDecodeError:
                pass
        elif re.match(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=", plain):
            structure = "SHELL_ASSIGNMENT" if plain.startswith("export ") else "PYTHON_SOURCE_ECHO"
        elif plain.startswith(("+", "-")) and not plain.startswith(("+++", "---")):
            structure = "DIFF_SOURCE_ECHO"
        elif plain.startswith(("```", "`")):
            structure = "MARKDOWN_CODE"
        elif ansi_present:
            structure = "ANSI_STATUS"
        if re.match(r"(?i)^codex-(status|diagnostic|usage)\s+", plain):
            structure = "STRUCTURED_CLI_DIAGNOSTIC"
            known_cli_frame = True
        if relative_start <= len(line) // 4:
            position = "LINE_START"
        elif relative_end >= (len(line) * 3) // 4:
            position = "LINE_END"
        else:
            position = "MIDDLE"
        candidate_token = match.group(2)
        quote = "DOUBLE" if candidate_token.startswith(('"', '\\"')) else "SINGLE" if candidate_token.startswith(("'", "\\'")) else "UNQUOTED"
        if not prefix:
            prefix_structure = "NONE"
        elif re.match(r"(?i)^codex[- ]", prefix):
            prefix_structure = "CLI_FRAME"
        elif prefix.startswith(("+", "-")):
            prefix_structure = "DIFF_PREFIX"
        elif prefix.endswith((">", "]")) or re.search(r"\[[^]]+\]\s*$", prefix):
            prefix_structure = "LOG_PREFIX"
        elif prefix.endswith((":", "=")):
            prefix_structure = "SOURCE_PREFIX"
        else:
            prefix_structure = "OTHER"
        pair_count = len(list(_SECRET.finditer(line)))
        return {
            "structure_category": structure,
            "finding_scope_category": scope,
            "prefix_structure_category": prefix_structure,
            "delimiter_category": "COLON" if delimiter == ":" else "EQUALS",
            "quote_category": quote,
            "ansi_present": ansi_present,
            "match_position_category": position,
            "known_cli_frame": known_cli_frame,
            "whitespace_layout_category": "PREFIX_SPACE" if prefix and line[:relative_start].endswith(" ") else "COMPACT",
            "key_value_pair_count_bucket": "1" if pair_count == 1 else "2-3" if pair_count < 4 else "4+",
            "prefix_length_bucket": "0" if not prefix else "1-15" if len(prefix) < 16 else "16+",
        }

    source_text = {name: data.decode("utf-8", "replace") for name, data in (prompt_sources or {}).items()}
    owned_contents: dict[str, str] = {}
    if workspace_root is not None and owned_files:
        for relative in owned_files:
            path = workspace_root / relative
            try:
                if path.is_file() and not path.is_symlink():
                    owned_contents[relative] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    output_text = value.decode("utf-8", "replace")
    diff_metadata = _parse_unified_diff_lines(output_text, workspace_root=workspace_root or Path.cwd())
    for match in _SECRET.finditer(output_text):
        kind = match.group(1).lower().replace("_", "-")
        candidate = match.group(2).strip()
        between = output_text[match.end(1):match.start(2)]
        delimiter = ":" if ":" in between else "="
        classification = next(iter(_secret_classifications(f"{match.group(1)}={candidate}".encode()).get(kind, {})))
        origin = {
            "secret_env_match": any(candidate == item for item in environment_values),
            "prompt_match": finding_in(prompt_text, kind, delimiter, candidate),
            "last_message_match": finding_in(last_text, kind, delimiter, candidate),
            "stderr_only_unknown": channel == "stderr" and not finding_in(prompt_text, kind, delimiter, candidate)
            and not finding_in(last_text, kind, delimiter, candidate) and not any(candidate == item for item in environment_values),
        }
        prompt_fields = [name for name, text in source_text.items() if finding_in(text, kind, delimiter, candidate)]
        if finding_in(prompt_text, kind, delimiter, candidate) and not prompt_fields:
            prompt_fields = ["static_harness_template"]
        origin["prompt_logical_fields"] = sorted(set(prompt_fields))
        package_sections = {name.split(".", 2)[1] for name in prompt_fields
                            if name.startswith("execution_package.") and len(name.split(".", 2)) > 1}
        origin["package_sections"] = sorted(package_sections)
        owned_paths = [relative for relative, text in owned_contents.items()
                       if owned_source_matches(relative, text, kind, delimiter, candidate)]
        workspace_match = bool(owned_paths)
        origin["owned_workspace_match"] = workspace_match
        origin["owned_relative_paths"] = sorted(owned_paths)
        origin["source_categories"] = ["OWNED_WORKSPACE_CONTENT"] if workspace_match else []
        if workspace_match and workspace_root is not None:
            origin.update(_file_content_provenance(
                workspace_root / owned_paths[0], workspace_root=workspace_root,
                worker_output_bound=False, test_fixture_bound=owned_paths[0].startswith("tests/"),
            ))
        else:
            origin.update(_file_content_provenance("relative/unknown"))
        line_start = output_text.rfind("\n", 0, match.start()) + 1
        line_end = output_text.find("\n", match.end())
        line = output_text[line_start:len(output_text) if line_end < 0 else line_end]
        structural = line_structure(line, match, delimiter, line_start)
        origin.update(structural)
        origin.update(diff_metadata.get(line_start, {
            "diff_target_relative_paths": [], "diff_change_category": "UNKNOWN",
            "diff_file_type": "UNKNOWN", "diff_hunk_position_bucket": "UNKNOWN",
        }))
        producer_category = "UNKNOWN"
        framing_category = "UNFRAMED"
        if re.fullmatch(r"codex-usage\s+token=\d+", line.strip(), re.I):
            producer_category = "CODEX_USAGE_TELEMETRY"; framing_category = "CODEX_USAGE_RECORD"
        elif re.fullmatch(r"codex-status\s+token=[^\s]+", line.strip(), re.I):
            producer_category = "CODEX_CLI_STATUS"; framing_category = "CODEX_STATUS_RECORD"
        elif line.lstrip().lower().startswith("codex-diagnostic "):
            producer_category = "CODEX_CLI_DIAGNOSTIC"; framing_category = "CODEX_DIAGNOSTIC_PREFIX"
        elif line.lstrip().lower().startswith("generated-code "):
            producer_category = "GENERATED_CODE_ECHO"; framing_category = "GENERATED_CODE_PREFIX"
        elif line.lstrip().lower().startswith("tool-output "):
            producer_category = "CHILD_TOOL_OUTPUT"; framing_category = "CHILD_TOOL_PREFIX"
        elif line.lstrip().lower().startswith("harness-wrapper "):
            producer_category = "WRAPPER_OUTPUT"; framing_category = "WRAPPER_PREFIX"
        elif workspace_match:
            echoed_paths = [relative for relative, text in owned_contents.items()
                            if any(syntax_normalize(source_line) == syntax_normalize(line)
                                   for source_line in text.splitlines())]
            if echoed_paths:
                producer_category = "GENERATED_CODE_ECHO"; framing_category = "OWNED_ASSIGNMENT_ECHO"
        origin["producer_category"] = producer_category
        origin["producer_categories"] = [producer_category]
        line_length = len(line)
        origin["line_length_bucket"] = "0-79" if line_length < 80 else "80-255" if line_length < 256 else "256+"
        origin["framing_category"] = framing_category
        if producer_category != "UNKNOWN":
            origin["stderr_only_unknown"] = False
        by_kind = result.setdefault(kind, {})
        entry = by_kind.setdefault(classification, {"count": 0, "origin": {
            "secret_env_match": False, "prompt_match": False,
            "last_message_match": False, "stderr_only_unknown": False,
            "prompt_logical_fields": [], "package_sections": [],
            "owned_workspace_match": False, "owned_relative_paths": [],
            "source_categories": [],
            "file_source_scope": "UNKNOWN", "file_source_origin_category": "UNKNOWN",
            "file_source_bound_to_package": False, "file_source_bound_to_worker_output": False,
            "file_source_bound_to_test_fixture": False, "file_source_generated_in_current_run": False,
            "producer_category": "UNKNOWN", "producer_categories": [],
            "line_length_bucket": [], "framing_category": [], "structure_category": [],
            "finding_scope_category": [], "prefix_structure_category": [],
            "delimiter_category": [], "quote_category": [], "ansi_present": False,
            "match_position_category": [], "known_cli_frame": False,
            "whitespace_layout_category": [], "key_value_pair_count_bucket": [], "prefix_length_bucket": [],
            "diff_target_relative_paths": [], "diff_change_category": [], "diff_file_type": [],
            "diff_hunk_position_bucket": [],
        }})
        entry["count"] += 1
        for field, present in origin.items():
            if field in {"prompt_logical_fields", "package_sections", "owned_relative_paths",
                         "producer_categories", "source_categories"}:
                entry["origin"][field] = sorted(set(entry["origin"][field]) | set(present))
            elif field in {"line_length_bucket", "framing_category", "structure_category",
                           "finding_scope_category", "prefix_structure_category", "delimiter_category",
                           "quote_category", "match_position_category", "whitespace_layout_category",
                           "key_value_pair_count_bucket", "prefix_length_bucket", "diff_change_category",
                           "diff_file_type", "diff_hunk_position_bucket"}:
                entry["origin"][field] = sorted(set(entry["origin"][field]) | {present})
            elif field == "diff_target_relative_paths":
                entry["origin"][field] = sorted(set(entry["origin"][field]) | set(present))
            elif field == "producer_category":
                current = entry["origin"][field]
                entry["origin"][field] = present if current == "UNKNOWN" else current if current == present else "MULTIPLE"
            else:
                entry["origin"][field] = bool(entry["origin"][field] or present)
    return result


def _file_content_provenance(
    source: str | Path,
    *,
    workspace_root: Path | None = None,
    run_root: Path | None = None,
    host_runtime_root: Path | None = None,
    temp_root: Path | None = None,
    dependency_root: Path | None = None,
    system_root: Path | None = None,
    package_bound: bool = False,
    worker_output_bound: bool = False,
    test_fixture_bound: bool = False,
    generated_current_run: bool = False,
) -> dict[str, Any]:
    """Classify file-content provenance using canonical containment only."""
    try:
        candidate = Path(source)
        if not candidate.is_absolute() or candidate.is_symlink():
            return {"file_source_scope": "UNKNOWN", "file_source_origin_category": "UNKNOWN",
                    "file_source_bound_to_package": False, "file_source_bound_to_worker_output": False,
                    "file_source_bound_to_test_fixture": False, "file_source_generated_in_current_run": False}
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return {"file_source_scope": "UNKNOWN", "file_source_origin_category": "UNKNOWN",
                "file_source_bound_to_package": False, "file_source_bound_to_worker_output": False,
                "file_source_bound_to_test_fixture": False, "file_source_generated_in_current_run": False}

    roots = (("WORKSPACE_OWNED", workspace_root), ("RUN_ROOT", run_root),
             ("HOST_RUNTIME", host_runtime_root), ("TEMP", temp_root),
             ("DEPENDENCY", dependency_root), ("SYSTEM", system_root))
    scope = "UNKNOWN"
    for category, root in roots:
        if root is None:
            continue
        try:
            root_resolved = Path(root).resolve(strict=False)
            if resolved == root_resolved or root_resolved in resolved.parents:
                scope = category
                break
        except (OSError, RuntimeError, ValueError):
            continue
    if scope == "UNKNOWN":
        scope = "EXTERNAL" if candidate.is_absolute() else "UNKNOWN"
    if test_fixture_bound:
        origin = "TEST_FIXTURE"
    elif package_bound:
        origin = "PACKAGE_INPUT"
    elif worker_output_bound:
        origin = "WORKER_GENERATED"
    elif generated_current_run:
        origin = "GENERATED_ARTIFACT"
    else:
        origin = "UNKNOWN"
    return {"file_source_scope": scope, "file_source_origin_category": origin,
            "file_source_bound_to_package": bool(package_bound),
            "file_source_bound_to_worker_output": bool(worker_output_bound),
            "file_source_bound_to_test_fixture": bool(test_fixture_bound),
            "file_source_generated_in_current_run": bool(generated_current_run)}


def _redact(value: str) -> str:
    return _SECRET.sub(lambda match: match.group(1) + "=[REDACTED]", value)


def production_executor_manifest() -> dict[str, Any]:
    return {
        "asset_id": EXECUTOR_ID,
        "asset_type": "worker_executor",
        "version": EXECUTOR_VERSION,
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "structured_event_contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
        "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
        "execution_backends": [HOST_GATEWAY, LOCAL_CHILD],
        "production_backend": HOST_GATEWAY,
        "backend": EXECUTOR_ID,
        "production": True,
        "test_double": False,
        "capabilities": ["implement", "test", "checkpoint"],
        "permissions": ["owned-files-write", "project-tests", "local-git-commit"],
        "network_policy": "NO_TASK_NETWORK",
        "secret_policy": "NO_SECRET_ACCESS_OR_OUTPUT",
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _safe_scope(values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ProductionWorkerError("production worker owned scope is missing")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ProductionWorkerError("production worker owned scope is unsafe")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ProductionWorkerError("production worker owned scope is unsafe")
        result.append(value)
    return result


def _is_test_runner(argv: Sequence[str]) -> bool:
    return any(PurePosixPath(str(token)).name in {"pytest", "py.test"} for token in argv) or ("-m" in argv and "pytest" in argv)


def _test_count_bucket(value: int | None) -> str:
    return "UNKNOWN" if value is None else "0" if value == 0 else "1" if value == 1 else "2" if value == 2 else "3+"


def _test_runner_metadata(stdout: bytes, stderr: bytes, exit_code: int) -> dict[str, Any]:
    """Parse only pytest's structured terminal summary; never retain test identity/text."""
    text = (stdout + b"\n" + stderr).decode("utf-8", "replace")
    counts = {"passed": 0, "failed": 0, "error": 0, "collected": None}
    for line in text.splitlines():
        summary = re.match(r"^=+\s*(.*?)\s+in\s+[0-9.]+s\s*=+$", line.strip())
        if summary:
            for number, label in re.findall(r"(\d+)\s+(passed|failed|error|errors|collected)", summary.group(1)):
                key = "error" if label in {"error", "errors"} else label
                counts[key] = int(number)
        collected = re.match(r"^(\d+)\s+items?\s+collected$", line.strip())
        if collected:
            counts["collected"] = int(collected.group(1))
    import_error = any(line.strip().startswith("ImportError while importing test module") for line in text.splitlines())
    if exit_code == 124:
        category, semantics = "TIMEOUT", "INTERRUPTED"
    elif import_error:
        category, semantics = "IMPORT_ERROR", "COLLECTION_FAILED"
    elif counts["failed"]:
        category, semantics = "TEST_FAILURE", "TESTS_FAILED"
    elif counts["error"]:
        category, semantics = "COLLECTION_ERROR", "COLLECTION_FAILED"
    elif counts["collected"] == 0:
        category, semantics = "NO_TESTS_COLLECTED", "NO_TESTS"
    elif exit_code == 0:
        category, semantics = "UNKNOWN", "UNKNOWN"
    elif exit_code == 2:
        category, semantics = "USAGE_ERROR", "USAGE_ERROR"
    else:
        category, semantics = "RUNTIME_ERROR", "INTERNAL_ERROR"
    return {"test_runner_result_category": category,
            "test_passed_count_bucket": _test_count_bucket(counts["passed"]),
            "test_failed_count_bucket": _test_count_bucket(counts["failed"]),
            "test_error_count_bucket": _test_count_bucket(counts["error"]),
            "test_collected_count_bucket": _test_count_bucket(counts["collected"]),
            "test_exit_semantics": semantics}


def _command(root: Path, argv: list[str], timeout: int = 900, *,
             env: Mapping[str, str] | None = None,
             classify_collection: bool = False) -> dict[str, Any]:
    try:
        result = subprocess.run(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=timeout, env=dict(env) if env is not None else None)
        stdout = bytes(result.stdout or b""); stderr = bytes(result.stderr or b"")
        result_meta = _test_runner_metadata(stdout, stderr, result.returncode) if _is_test_runner(argv) else {}
        collection_meta = (_collection_output_classification(stdout, stderr, root)
                           if classify_collection else {})
        return {"command": argv, "exit_code": result.returncode, "timeout": False, **result_meta,
                **collection_meta,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest()}
    except subprocess.TimeoutExpired as exc:
        result_meta = _test_runner_metadata(bytes(exc.stdout or b""), bytes(exc.stderr or b""), 124) if _is_test_runner(argv) else {}
        return {"command": argv, "exit_code": 124, "timeout": True, **result_meta,
                "stdout_sha256": hashlib.sha256(bytes(exc.stdout or b"")).hexdigest(),
                "stderr_sha256": hashlib.sha256(bytes(exc.stderr or b"")).hexdigest()}
    except OSError:
        return {"command": argv, "exit_code": None, "timeout": False, "spawn_error": True,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(b"").hexdigest()}


def _verification_bucket(value: int | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value == 0:
        return "0"
    if value <= 3:
        return "1-3"
    return "4+"


def _independent_verification_metadata(commands: Mapping[str, Any], expected_count: int) -> dict[str, Any]:
    """Bounded diagnostics for independent verification; never includes command text."""
    values = [commands.get(key) for key in (
        "focused_test", "full_regression", "compile_import", "git_diff_check",
    )] if isinstance(commands, Mapping) else []
    nonzero = [item for item in values if not isinstance(item, Mapping) or item.get("exit_code") != 0]
    timed_out = [item for item in values if isinstance(item, Mapping) and item.get("timeout")]
    focused_category = commands.get("focused_test", {}).get("test_runner_result_category") if isinstance(commands.get("focused_test"), Mapping) else None
    full_category = commands.get("full_regression", {}).get("test_runner_result_category") if isinstance(commands.get("full_regression"), Mapping) else None
    relation = "SAME_CATEGORY" if focused_category and focused_category == full_category else "DIFFERENT_CATEGORY" if focused_category and full_category else "ONE_UNKNOWN" if focused_category or full_category else "BOTH_UNKNOWN"
    return {
        "independent_verification_status": "BLOCK" if nonzero or timed_out else "PASS",
        "independent_verification_stage": "EXECUTION" if nonzero or timed_out else "VERDICT",
        "independent_verification_exit_category": "NONZERO" if nonzero else ("UNKNOWN" if timed_out else "ZERO"),
        "independent_test_count_bucket": "UNKNOWN",
        "independent_expected_test_count_bucket": _verification_bucket(expected_count),
        "independent_failure_category": "COMMAND_EXECUTION_NONZERO" if nonzero else ("TOOLCHAIN_UNAVAILABLE" if timed_out else "NONE"),
        "focused_full_failure_relation": relation,
    }


def _independent_verification_steps(commands: Mapping[str, Any]) -> list[dict[str, Any]]:
    categories = {"focused_test": "FOCUSED_TEST", "full_regression": "FULL_TEST",
                  "compile_import": "COMPILE", "git_diff_check": "DIFF_CHECK"}
    ordered = list(categories)
    steps: list[dict[str, Any]] = []
    for index, key in enumerate(ordered):
        value = commands.get(key) if isinstance(commands, Mapping) else None
        category = categories[key]
        if not isinstance(value, Mapping):
            status, exit_category, failure = "NOT_RUN", "NOT_RUN", "UNKNOWN"
        elif value.get("spawn_error"):
            status, exit_category, failure = "BLOCK", "SPAWN_ERROR", "SPAWN"
        elif value.get("timeout"):
            status, exit_category, failure = "BLOCK", "TIMEOUT", "TIMEOUT"
        elif value.get("exit_code") == 0:
            status, exit_category, failure = "PASS", "ZERO", "NONE"
        else:
            status, exit_category, failure = "BLOCK", "NONZERO", "COMMAND_NONZERO"
        order = "FIRST" if index == 0 else "LAST" if index == len(ordered) - 1 else "MIDDLE"
        steps.append({"verification_step_category": category, "verification_step_status": status,
                      "verification_step_exit_category": exit_category,
                      "verification_step_order_bucket": order,
                      "verification_step_test_count_bucket": "UNKNOWN",
                      "verification_step_failure_category": failure,
                      **({key: value[key] for key in ("test_runner_result_category", "test_passed_count_bucket",
                                                      "test_failed_count_bucket", "test_error_count_bucket",
                                                      "test_collected_count_bucket", "test_exit_semantics") if key in value}
                         if category in {"FOCUSED_TEST", "FULL_TEST"} and isinstance(value, Mapping) else {})})
    return steps


def _independent_verification_provenance(commands: Mapping[str, Any]) -> dict[str, str]:
    """Return the first bounded verifier failure without inspecting output text."""
    ordered = ("focused_test", "full_regression", "compile_import", "git_diff_check")
    ids = {"focused_test": "FOCUSED_TEST_EXECUTION", "full_regression": "FULL_TEST_EXECUTION",
           "compile_import": "COMPILE_EXECUTION", "git_diff_check": "DIFF_CHECK_EXECUTION"}
    last_entered = "NONE"; last_successful = "NONE"
    first_failure = "NONE"; category = "NONE"; bucket = "NONE"
    for key in ordered:
        step = ids[key]; last_entered = step
        value = commands.get(key) if isinstance(commands, Mapping) else None
        if not isinstance(value, Mapping):
            if first_failure == "NONE":
                first_failure, category, bucket = step, "RESULT_SCHEMA", "VALIDATION"
            continue
        exit_code = value.get("exit_code"); timed_out = value.get("timeout")
        if value.get("spawn_error") is True:
            if first_failure == "NONE":
                first_failure, category, bucket = step, "SPAWN", "PROCESS"
        elif not isinstance(timed_out, bool) or isinstance(exit_code, bool) or not isinstance(exit_code, int):
            if first_failure == "NONE":
                first_failure, category, bucket = step, "RESULT_SCHEMA", "VALIDATION"
        elif timed_out:
            if first_failure == "NONE":
                first_failure, category, bucket = step, "TIMEOUT", "TIMEOUT"
        elif exit_code != 0:
            if first_failure == "NONE":
                first_failure, category, bucket = step, "NONZERO_EXIT", "PROCESS"
        else:
            last_successful = step
    return {
        "worker_verification_last_entered_step": last_entered,
        "worker_verification_last_successful_step": last_successful,
        "worker_verification_failure_step": first_failure,
        "worker_verification_failure_category": category,
        "worker_verification_exception_bucket": bucket,
    }


def _focused_execution_metadata(result: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Describe the production focused callsite without command, path, env, or output."""
    if not isinstance(result, Mapping):
        exit_class = "UNKNOWN"
    elif result.get("spawn_error") is True:
        exit_class = "SPAWN_ERROR"
    elif result.get("timeout") is True:
        exit_class = "TIMEOUT"
    elif result.get("exit_code") == 0:
        exit_class = "ZERO"
    elif isinstance(result.get("exit_code"), int) and not isinstance(result.get("exit_code"), bool):
        exit_class = "NONZERO"
    else:
        exit_class = "UNKNOWN"
    return {
        "focused_runner_source": "PROJECT_REGISTERED_TOOLCHAIN",
        "focused_runner_kind": "PYTEST_ENTRYPOINT",
        "focused_command_builder_id": "REGISTERED_PYTEST_DIRECT_V1",
        "focused_argv_shape_id": "RUNNER_QUIET_SCOPED_TARGETS",
        "focused_test_scope_source_id": "OWNED_TEST_FILE_PROJECTION",
        "focused_cwd_source_id": "WORKER_PROJECT_ROOT",
        "focused_env_projection_id": "INHERITED_PROCESS_ENV",
        "focused_process_launcher_id": "SUBPROCESS_RUN",
        "focused_process_exit_class": exit_class,
        "prior_fix_callsite_reached": "YES",
        "registered_runner_used": "YES",
        "legacy_module_path_reachable": "NO",
    }


def _collection_output_classification(stdout: bytes, stderr: bytes, root: Path) -> dict[str, str]:
    """Classify a collection failure in memory; never retain the module token."""
    text = (stdout + b"\n" + stderr).decode("utf-8", "replace")
    match = re.search(r"(?:ModuleNotFoundError|ImportError):[^\n]*?(?:named\s+)?['\"]([A-Za-z_][A-Za-z0-9_.]*)['\"]", text)
    if not match:
        return {"collection_failure_phase": "UNKNOWN", "import_failure_family": "UNKNOWN",
                "dependency_presence_class": "UNKNOWN"}
    top = match.group(1).split(".", 1)[0]
    if top == "tests":
        family, phase = "TEST_PACKAGE", "TEST_MODULE_IMPORT"
    elif (root / f"{top}.py").is_file() or (root / top).is_dir():
        family, phase = "PROJECT_LOCAL_MODULE", "PROJECT_MODULE_IMPORT"
    else:
        family, phase = "EXTERNAL_DEPENDENCY", "TEST_MODULE_IMPORT"
    return {"collection_failure_phase": phase, "import_failure_family": family,
            "dependency_presence_class": "MISSING"}


def _bounded_collection_diagnostics(
    root: Path, runner: Path, python: Path, tests: list[str], focused: Mapping[str, Any],
) -> dict[str, str]:
    """Run non-authorizing collection probes and persist enum-only conclusions."""
    try:
        runner_identity = ("PROJECT_VENV" if runner.resolve().is_relative_to((root / ".venv").resolve())
                           else "HOST_ENV")
    except (OSError, ValueError):
        runner_identity = "UNKNOWN"
    targets_resolvable = all((root / item).is_file() for item in tests)
    import_path_probe = _command(
        root, [str(python), "-c", "import pathlib,sys; raise SystemExit(0 if pathlib.Path.cwd().resolve() in [pathlib.Path(p or '.').resolve() for p in sys.path] else 1)"],
    )
    base = {
        "runner_environment_identity": runner_identity,
        "cwd_binding_match": "YES",
        "project_root_import_path_present": "YES" if import_path_probe.get("exit_code") == 0 else "NO",
        "test_targets_resolvable": "YES" if targets_resolvable else "NO",
        "pytest_config_load_status": "UNKNOWN",
        "plugin_load_status": "UNKNOWN",
        "collection_failure_phase": str(focused.get("collection_failure_phase", "UNKNOWN")),
        "import_failure_family": str(focused.get("import_failure_family", "UNKNOWN")),
        "dependency_presence_class": str(focused.get("dependency_presence_class", "UNKNOWN")),
    }
    if not targets_resolvable:
        base["collection_failure_phase"] = "TARGET_RESOLUTION"
        base["import_failure_family"] = "PATH_RESOLUTION"
        return base
    if focused.get("test_exit_semantics") != "COLLECTION_FAILED":
        base["pytest_config_load_status"] = "PASS"
        base["plugin_load_status"] = "PASS"
        return base
    configless = _command(
        root, [str(runner), "--collect-only", "-q", "-c", os.devnull, *tests],
        classify_collection=True,
    )
    plugin_env = dict(os.environ); plugin_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    pluginless = _command(
        root, [str(runner), "--collect-only", "-q", *tests],
        env=plugin_env, classify_collection=True,
    )
    if configless.get("exit_code") == 0:
        base.update({"pytest_config_load_status": "BLOCK", "collection_failure_phase": "CONFIG_LOAD",
                     "import_failure_family": "OTHER", "dependency_presence_class": "PRESENT"})
    elif pluginless.get("exit_code") == 0:
        base.update({"pytest_config_load_status": "PASS", "plugin_load_status": "BLOCK",
                     "collection_failure_phase": "PLUGIN_LOAD", "import_failure_family": "PLUGIN",
                     "dependency_presence_class": "PRESENT"})
    return base


def _independent_verification_failure(commands: Mapping[str, Any]) -> ProductionWorkerError:
    failure = ProductionWorkerError("production worker independent command verification failed")
    for key, value in _independent_verification_provenance(commands).items():
        setattr(failure, key, value)
    return failure


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_managed_child(argv: list[str], *, root: Path, prompt: bytes, timeout: int,
                       cancel_path: Path, grace_period: float = 2.0) -> tuple[bytes, bytes, dict[str, Any]]:
    """Run one child process group and leave deterministic termination evidence."""
    started_at = _utc(); started = time.monotonic()
    process = subprocess.Popen(argv, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    streams: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    def drain(name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            streams[name].append(bytes(chunk))
    readers = [threading.Thread(target=drain, args=(name, getattr(process, name)), daemon=True)
               for name in ("stdout", "stderr")]
    for reader in readers:
        reader.start()
    termination = "EXITED"; requested_signal = None
    try:
        assert process.stdin is not None
        process.stdin.write(prompt); process.stdin.close(); process.stdin = None
        while process.poll() is None:
            cancelled = cancel_path.is_file() and not cancel_path.is_symlink()
            timed_out = time.monotonic() - started >= timeout
            if cancelled or timed_out:
                termination = "CANCELLED" if cancelled else "TIMED_OUT"
                requested_signal = "SIGTERM"
                os.killpg(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + grace_period
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if process.poll() is None:
                    requested_signal = "SIGKILL"
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.02)
        # Reader threads continuously drain both pipes while the parent polls
        # cancellation and timeout state.  Waiting for process exit before
        # reading PIPEs would deadlock a verbose child at OS pipe capacity.
        stdout = b""; stderr = b""
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL); process.wait()
        for reader in readers:
            reader.join(timeout=grace_period + 1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        stdout = b"".join(streams["stdout"])
        stderr = b"".join(streams["stderr"])
    return bytes(stdout or b""), bytes(stderr or b""), {
        "schema_version":"orchestration.production-worker-process.v1", "pid":process.pid,
        "process_group_id":process.pid, "started_at":started_at, "ended_at":_utc(),
        "termination":termination, "requested_signal":requested_signal,
        "exit_code":process.returncode if process.returncode is not None and process.returncode >= 0 else None,
        "signal":-process.returncode if process.returncode is not None and process.returncode < 0 else None,
        "stdout_sha256":hashlib.sha256(bytes(stdout or b"")).hexdigest(),
        "stderr_sha256":hashlib.sha256(bytes(stderr or b"")).hexdigest(), "hard_stop":True,
    }


def _prompt(request: WorkerRequest, baseline: str, owned: list[str]) -> str:
    bounded = ""
    if request.extra_context.get("production_context_request"):
        from .production_context import build_production_context
        context = build_production_context(request.extra_context["production_context_request"])
        bounded = "\nValidated minimal artifact context:\n" + json.dumps(context, sort_keys=True, separators=(",", ":"))
    criteria = "\n".join(f"- {item}" for item in request.task.validation_criteria)
    scope = "\n".join(f"- {item}" for item in owned)
    effect_requirement = str(request.extra_context.get("task_effect_requirement", "UNKNOWN"))
    target_count = request.extra_context.get("change_target_count", 0)
    mutation_contract = (
        f"Task effect requirement: {effect_requirement}. Approved change-target count: {target_count}. "
        "For MUTATION_REQUIRED, a governed WRITE is required unless the target state is independently verified.\n"
    )
    return f"""Execute this sealed production LV implementation in the current repository.
Project/Gate/LV/run/attempt: {request.contract_summary.get('project_id')} / {request.contract_summary.get('gate_id')} / {request.contract_summary.get('lv_id')} / {request.extra_context.get('run_id')} / {request.extra_context.get('attempt')}
Baseline HEAD: {baseline}
Plan SHA-256: {request.contract_summary.get('canonical_plan_sha256')}
Task: {request.task.input}
{mutation_contract}Owned files (do not modify anything else):
{scope}
Completion criteria:
{criteria}
Use the existing project interpreter/environment. Do not use network, packages, secrets, system changes, Git mutation, approval/state changes, review, remediation, or the next Gate. Implement only the canonical Stage task within editable owned files, then return the minimal implementation completion report and exit immediately. Do not run focused/full regression or Harness validation; the deterministic Harness validator owns those checks. Do not manufacture orchestration artifacts; the controller collects evidence independently.{bounded}
"""


def execute_production_worker(request: WorkerRequest, *,
                              executor: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
                              timeout: int = 1800,
                              execution_backend: str | None = None,
                              gateway_transport: Callable[..., Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Run the registered Codex executor and independently collect product evidence."""
    root = Path(request.project_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise ProductionWorkerError("production worker project root is unsafe")
    if request.extra_context.get("execution_mode") != "production":
        raise ProductionWorkerError("production executor requires production mode")
    owned = _safe_scope(request.task.editable_scope)
    baseline = str(request.extra_context.get("source_snapshot", {}).get("source_head") or request.state_snapshot.get("head", ""))
    baseline_status = _git(root, "status", "--porcelain=v1", "-uall").stdout
    current_before = _git(root, "rev-parse", "HEAD").stdout.strip()
    adoption = current_before != baseline
    if adoption:
        ancestor = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", baseline, current_before], check=False)
        if ancestor.returncode != 0:
            raise ProductionWorkerError("production worker baseline is dirty or drifted")
        adopted_changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", current_before).stdout.splitlines()
        if not adopted_changed or any(path not in owned for path in adopted_changed):
            raise ProductionWorkerError("production worker adoption scope violation")
    prompt = _prompt(request, baseline, owned)
    prompt_bytes = prompt.encode()
    # Runtime instructions are authoritative evidence and must never carry
    # secret-like material into the child process or persisted artifacts.
    if _secret_findings(prompt_bytes):
        raise ProductionWorkerError("production executor prompt contains secret-like material")
    output = Path(request.task.output_dir); output.mkdir(parents=True, exist_ok=True)
    prompt_path = output / "executor.prompt.txt"
    prompt_sha_path = output / "executor.prompt.sha256"
    prompt_path.write_bytes(prompt_bytes)
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()
    prompt_sha_path.write_text(prompt_sha, encoding="ascii")
    last = output / "executor.last-message.txt"
    # The real subprocess backend is always strict.  Injected callables are
    # retained as an explicit legacy test seam; production never selects it.
    configured_backend = execution_backend or request.extra_context.get("execution_backend")
    # Injected executors are an explicit unit-test seam.  Real production calls
    # must select a backend in the request; no environment-driven fallback exists.
    if configured_backend is None and executor is not None:
        configured_backend = LOCAL_CHILD
    if configured_backend is None and executor is None and not request.extra_context.get("run_root"):
        # Direct legacy fixtures lack the orchestrator's durable run binding.
        # The production gate always supplies run_root and an explicit backend.
        configured_backend = LOCAL_CHILD
    if configured_backend not in {LOCAL_CHILD, HOST_GATEWAY}:
        raise ProductionWorkerError("EXECUTION_BACKEND_REQUIRED")
    legacy_fixture = not request.extra_context.get("run_root")
    if configured_backend == LOCAL_CHILD and request.extra_context.get("execution_mode") == "production" and not legacy_fixture:
        raise ProductionWorkerError("LOCAL_CHILD_PRODUCTION_DISABLED")
    workspace_identity = {
        "project_id": request.contract_summary.get("project_id", ""),
        "workspace_kind": "project_root",
        "branch": request.state_snapshot.get("branch", ""),
    }
    if configured_backend == LOCAL_CHILD and (executor is not None or legacy_fixture):
        # Legacy injected executor seam: it predates the durable host request
        # contract and is never selected by the production orchestrator.
        gateway_request = {"execution_backend": LOCAL_CHILD, "execution_request_id": "local-test-seam",
                           "request_digest": "", "gateway_contract_version": GATEWAY_CONTRACT_VERSION}
    else:
        try:
            socket_endpoint = str(request.extra_context.get("gateway_socket_relative", "runtime/host-gateway.sock"))
            gateway_request = build_gateway_request(
                project_id=str(request.contract_summary.get("project_id", "")),
                run_id=str(request.extra_context.get("run_id", "")),
                gate_id=str(request.contract_summary.get("gate_id", request.extra_context.get("gate_id", ""))),
                lv_id=str(request.contract_summary.get("lv_id", request.extra_context.get("lv_id", ""))),
                attempt=int(request.extra_context.get("attempt", 1)), workspace_identity=workspace_identity,
                package_manifest_sha256=str(request.extra_context.get("package_manifest_sha256", "")),
                preflight_evidence_sha256=str(request.extra_context.get("preflight_evidence_sha256", "")),
                runtime_prompt_artifact={"kind": "worker_runtime_prompt", "name": "executor.prompt.txt"},
                runtime_prompt_sha256=prompt_sha, adapter_contract_version=ADAPTER_CONTRACT_VERSION,
                structured_event_contract_version=STRUCTURED_EVENT_CONTRACT_VERSION,
                execution_backend=str(configured_backend),
                transport_endpoint=socket_endpoint,
                execution_request_id=request.extra_context.get("execution_request_id"),
                active_tool_authorization_contracts=list(
                    request.extra_context.get("active_tool_authorization_contracts", [])
                ),
                owned_files=owned,
                canonical_plan_sha256=str(request.contract_summary.get("canonical_plan_sha256", "")),
                requirement_digest=str(request.extra_context.get("requirement_digest", "")),
                tool_authorization_projection=dict(
                    request.extra_context.get("tool_authorization_projection", {})
                ),
                tool_authorization_projection_sha256=str(
                    request.extra_context.get("tool_authorization_projection_sha256", "")
                ),
                canonical_authority_binding=dict(
                    request.extra_context.get("canonical_authority_binding", {})
                ),
                canonical_authority_binding_digest=str(
                    request.extra_context.get("canonical_authority_binding_digest", "")
                ),
            )
            gateway_request = _validate_production_gateway_request(
                gateway_request,
                configured_backend=str(configured_backend),
            )

        except GatewayError as exc:
            raise ProductionWorkerError(str(exc)) from exc
    execution_last = last
    staging_parent: Path | None = None
    if configured_backend == HOST_GATEWAY:
        staging_id = str(gateway_request["execution_request_id"])
        if (not staging_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                                  for char in staging_id)):
            raise ProductionWorkerError("final-message staging binding is invalid")
        staging_parent = root / ".harness-runtime" / staging_id
        if staging_parent.exists():
            if staging_parent.is_symlink() or not staging_parent.is_dir() or any(staging_parent.iterdir()):
                raise ProductionWorkerError("stale or unsafe final-message staging target")
        else:
            staging_parent.mkdir(parents=True, mode=0o700)
        os.chmod(staging_parent, 0o700)
        execution_last = staging_parent / "final-message"
        final_message_target_metadata = {
            "target_scope": "RUN_ROOT", "codex_writable": False,
            "host_writable": True, "harness_writable": True,
            "staging_binding": "WORKSPACE_RELATIVE_EXACT",
        }
    else:
        final_message_target_metadata = _validate_final_message_target(root, execution_last)
    argv = CodexExecutionAdapter().argv(root=root, last_message=execution_last)
    pending_paths = [line[3:] for line in baseline_status.splitlines() if len(line) > 3]
    if pending_paths and any(not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in owned) for path in pending_paths):
        raise ProductionWorkerError("production worker changed files outside owned scope")
    cancel_path = output / "cancel.request"
    if adoption:
        stdout = stderr = b""
        worker_exit = 0; timed_out = False
        process_evidence = {"schema_version":"orchestration.production-worker-process.v1","pid":None,"process_group_id":None,
                            "started_at":None,"ended_at":None,"termination":"ADOPTED_CHECKPOINT","requested_signal":None,
                            "exit_code":0,"signal":None,"stdout_sha256":hashlib.sha256(b"").hexdigest(),
                            "stderr_sha256":hashlib.sha256(b"").hexdigest(),"secret_like_output_detected":False,"hard_stop":True}
    elif pending_paths:
        stdout = stderr = b""
        worker_exit = 0; timed_out = False
        process_evidence = {"schema_version":"orchestration.production-worker-process.v1","pid":None,"process_group_id":None,
                            "started_at":None,"ended_at":None,"termination":"RESUMED_PENDING_CHECKPOINT","requested_signal":None,
                            "exit_code":0,"signal":None,"stdout_sha256":hashlib.sha256(b"").hexdigest(),
                            "stderr_sha256":hashlib.sha256(b"").hexdigest(),"secret_like_output_detected":False,"hard_stop":True}
    else:
        if configured_backend == HOST_GATEWAY:
            try:
                if gateway_transport is None:
                    endpoint = gateway_request.get("transport_endpoint", "runtime/host-gateway.sock")
                    try:
                        endpoint_path = resolve_gateway_socket_path(root, str(endpoint))
                    except GatewayError as exc:
                        raise ProductionWorkerError("unsafe HOST_GATEWAY socket endpoint") from exc
                    gateway_transport = UnixSocketGatewayTransport(endpoint_path, workspace_root=root)
                execution = _production_host_execution_gateway(gateway_transport).execute(
                    gateway_request, prompt=prompt_bytes, last_message=execution_last,
                    timeout=timeout, cancel_path=cancel_path,
                )
            except GatewayError as exc:
                raise ProductionWorkerError(str(exc)) from exc
            stdout, stderr = execution.stdout, execution.stderr
            process_evidence, adapter_evidence = execution.process_evidence, execution.adapter_evidence
            process_evidence.setdefault("backend", HOST_GATEWAY)
            if adapter_evidence.get("final_message_target_binding") != "WORKSPACE_RELATIVE_EXACT":
                raise ProductionWorkerError("final-message runner result path binding mismatch")
            host_final_metadata = _validate_final_message_bytes(execution.final_message)
            _persist_private_final_message(last, execution.final_message)
            # Broker-native gateway returns the validated final message as a
            # bounded response payload; it does not materialize the worker
            # staging target.  The response bytes were already shape- and
            # security-validated above, so requiring a second filesystem
            # artifact would reject the canonical broker transport.
            if staging_parent is None:
                raise ProductionWorkerError("final-message staging acceptance is incomplete")
            if execution_last.is_file() and not execution_last.is_symlink():
                execution_last.unlink()
            try:
                staging_parent.rmdir()
                staging_parent.parent.rmdir()
            except OSError:
                pass
            final_message_target_metadata.update(host_final_metadata)
        else:
            adapter = CodexExecutionAdapter(executor=executor, strict_jsonl=executor is None)
            stdout, stderr, process_evidence, adapter_evidence = adapter.run(
                root=root, prompt=prompt_bytes, last_message=last, timeout=timeout,
                cancel_path=cancel_path,
            )
        worker_exit = int(process_evidence["exit_code"] if process_evidence["exit_code"] is not None else 128 + int(process_evidence["signal"] or 0))
        timed_out = process_evidence["termination"] == "TIMED_OUT"
        process_evidence["adapter_contract_version"] = adapter_evidence["contract_version"]
        process_evidence["backend"] = adapter_evidence["backend"]
        process_evidence["structured_event_contract_version"] = STRUCTURED_EVENT_CONTRACT_VERSION
        process_evidence["structured_strict"] = adapter_evidence["strict"]
        if process_evidence["structured_strict"]:
            if adapter_evidence.get("structured_event_contract_version") != STRUCTURED_EVENT_CONTRACT_VERSION:
                raise StructuredEventError("structured event contract version mismatch")
            if adapter_evidence.get("codex_version") != SUPPORTED_CODEX_VERSION:
                raise StructuredEventError("Codex CLI version is outside the supported contract")
            process_evidence["codex_version"] = adapter_evidence["codex_version"]
    process_evidence["execution_backend"] = configured_backend
    process_evidence["gateway_contract_version"] = GATEWAY_CONTRACT_VERSION
    process_evidence["execution_request_id"] = gateway_request["execution_request_id"]
    process_evidence["request_digest"] = gateway_request["request_digest"]
    process_evidence["final_message_target"] = final_message_target_metadata
    process_path = output / "executor.process.json"
    final_message_metadata: dict[str, Any] = {"exists": False, "nonempty": False, "size_bucket": "0"}
    structured_strict = bool(process_evidence.get("structured_strict"))
    stdout_findings = {} if structured_strict and worker_exit == 0 else _secret_findings(stdout)
    stderr_findings = {} if structured_strict and worker_exit == 0 else _secret_findings(stderr)
    process_evidence.setdefault("adapter_contract_version", ADAPTER_CONTRACT_VERSION)
    process_evidence.setdefault("backend", EXECUTOR_ID)
    process_evidence.setdefault("structured_event_contract_version", STRUCTURED_EVENT_CONTRACT_VERSION)
    process_evidence.setdefault("structured_strict", False)
    if not process_evidence.get("structured_strict"):
        process_evidence.setdefault("structured_events", {
            "contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
            "event_type_counts": {}, "event_type_sequence_category": "TEST_INJECTED_LEGACY",
            "unknown_event_count": 0, "parse_error_count": 0,
            "terminal_event_present": False,
        })
    if process_evidence.get("structured_strict") and worker_exit == 0:
        try:
            process_evidence["structured_events"] = _parse_structured_jsonl(
                stdout, workspace_root=root, owned_files=owned,
                worker_task_id=request.task.thread_id,
                tool_operation_policy=request.extra_context.get("tool_operation_policy"),
            )
            process_evidence["security_stage_status"] = {
                "JSONL_VALID": "PASS", "STDERR_SECURITY": "NOT_EVALUATED",
                "FINAL_MESSAGE": "NOT_EVALUATED",
            }
            stderr_findings = _secret_findings(stderr)
        except (StructuredEventError, StructuredContentSecurityError) as exc:
            structured_events = {
                "contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
                "event_type_counts": {}, "event_type_sequence_category": "INVALID",
                "unknown_event_count": 0,
                "parse_error_count": 1 if "invalid JSON" in str(exc) else 0,
                "terminal_event_present": False,
            }
            if isinstance(exc, (StructuredEventError, StructuredContentSecurityError)):
                structured_events.update(exc.safe_metadata)
            process_evidence["structured_events"] = structured_events
            if isinstance(exc, StructuredContentSecurityError):
                process_evidence.update(_bounded_structured_security_provenance(exc))
            process_evidence["security_stage_status"] = {
                "JSONL_VALID": "BLOCK", "STDERR_SECURITY": "NOT_EVALUATED",
                "FINAL_MESSAGE": "NOT_EVALUATED",
            }
            process_path.write_bytes(canonical_json_bytes(process_evidence))
            raise
    if process_evidence.get("structured_strict") and worker_exit == 0:
        process_evidence["structured_events"] = process_evidence.get("structured_events", {
            "contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
            "event_type_counts": {}, "event_type_sequence_category": "INVALID",
            "unknown_event_count": 0, "parse_error_count": 0,
            "terminal_event_present": False,
        })
        process_evidence["security_stage_status"]["STDERR_SECURITY"] = "BLOCK" if stderr_findings else "PASS"
        if stderr_findings:
            process_evidence["security_stage_status"]["FINAL_MESSAGE"] = "NOT_EVALUATED"
        else:
            try:
                final_message_metadata = _validate_final_message(last)
                process_evidence["security_stage_status"]["FINAL_MESSAGE"] = "PASS"
            except ProductionWorkerError as exc:
                process_evidence["security_stage_status"]["FINAL_MESSAGE"] = "BLOCK"
                if isinstance(exc, StructuredContentSecurityError):
                    process_evidence.update(exc.safe_metadata)
                process_evidence["final_message"] = final_message_metadata
                process_path.write_bytes(canonical_json_bytes(process_evidence))
                raise
    # The CLI may materialize a last-message artifact.  Preserve its
    # existence/contract while removing any secret-like assignment before it
    # can become durable evidence.  The original bytes are used only for the
    # in-memory origin comparison below.
    last_message_raw = b""
    if last.is_file() and not last.is_symlink():
        try:
            last_message_raw = last.read_bytes()
            redacted_last = _redact(last_message_raw.decode("utf-8", "replace")).encode("utf-8")
            if redacted_last != last_message_raw:
                last.write_bytes(redacted_last)
        except (OSError, UnicodeError):
            last_message_raw = b""
    secret_like_output_detected = bool(stdout_findings or stderr_findings)
    process_evidence["secret_like_output_detected"] = secret_like_output_detected
    process_evidence["secret_like_output_channels"] = [channel for channel, findings in
                                                        (("stdout", stdout_findings), ("stderr", stderr_findings)) if findings]
    process_evidence["secret_like_output_kinds"] = {"stdout": stdout_findings, "stderr": stderr_findings}
    process_evidence["secret_like_output_classifications"] = {
        "stdout": _secret_classifications(stdout),
        "stderr": _secret_classifications(stderr),
    }
    prompt_sources: dict[str, bytes] = {
        "execution_package.task_context.input": str(request.task.input).encode("utf-8"),
        "execution_package.task_context.validation_criteria": canonical_json_bytes(list(request.task.validation_criteria)),
        "execution_package.task_context.owned_files": canonical_json_bytes(owned),
        "execution_package.contract_summary": canonical_json_bytes(request.contract_summary),
        "execution_package.runtime_identity": canonical_json_bytes({
            "baseline": baseline, "run_id": request.extra_context.get("run_id"),
            "attempt": request.extra_context.get("attempt"),
        }),
    }
    context_marker = b"\nValidated minimal artifact context:\n"
    if context_marker in prompt_bytes:
        prompt_sources["generated_runtime_metadata.validated_artifact_context"] = prompt_bytes.split(context_marker, 1)[1]
    process_evidence["secret_like_output_origins"] = {
        "stdout": _secret_origin_classifications(stdout, channel="stdout", prompt=prompt_bytes,
                                                   last_message=last_message_raw, prompt_sources=prompt_sources,
                                                   workspace_root=root, owned_files=owned),
        "stderr": _secret_origin_classifications(stderr, channel="stderr", prompt=prompt_bytes,
                                                   last_message=last_message_raw, prompt_sources=prompt_sources,
                                                   workspace_root=root, owned_files=owned),
    }
    process_evidence["security_findings"] = (
        (_safe_security_findings(stdout, channel="UNKNOWN", category="UNKNOWN") if stdout_findings else [])
        + (_safe_security_findings(stderr, channel="STDERR", category="UNKNOWN") if stderr_findings else [])
    )
    process_evidence["observability"] = ["CHILD_STARTED", "CHILD_EXITED" if process_evidence.get("termination") == "EXITED" else process_evidence.get("termination", "CHILD_EXITED")]
    process_path.write_bytes(canonical_json_bytes(process_evidence))
    if worker_exit != 0 or timed_out or process_evidence["termination"] not in {"EXITED", "RESUMED_PENDING_CHECKPOINT", "ADOPTED_CHECKPOINT"}:
        if process_evidence["termination"] == "TIMED_OUT":
            raise ProductionWorkerError("WORKER_TIMEOUT: production executor failed or timed out")
        if process_evidence["termination"] == "CANCELLED":
            raise ProductionWorkerError("WORKER_CANCELLED: production executor was cancelled")
        raise ProductionWorkerError("WORKER_PROCESS_FAILURE: production executor failed or timed out")
    if secret_like_output_detected:
        raise ProductionWorkerError("production executor emitted secret-like output")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    if head == baseline:
        lines = _git(root, "status", "--porcelain=v1", "-uall").stdout.splitlines()
        changed = [line[3:] for line in lines if len(line) > 3]
    else:
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).stdout.splitlines()
    if not changed:
        diagnostic = _redact(last.read_text(encoding="utf-8", errors="replace")[:500]) if last.is_file() else "no final message"
        raise ProductionWorkerError(f"production executor produced no product changes: {diagnostic}")
    outside = [path for path in changed if not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in owned)]
    if outside:
        raise ProductionWorkerError(f"production executor changed files outside owned scope: {outside}")
    hardcoded_findings = _hardcoded_credential_findings(root, changed)
    secret_handling_allowed = _task_allows_secret_handling(request)
    process_evidence["owned_diff_security_validation"] = {
        "status": "BLOCK" if hardcoded_findings and not secret_handling_allowed else "PASS",
        "task_secret_handling_allowed": secret_handling_allowed,
        "findings": hardcoded_findings,
    }
    process_path.write_bytes(canonical_json_bytes(process_evidence))
    if hardcoded_findings and not secret_handling_allowed:
        raise ProductionWorkerError("OWNED_DIFF_HARDCODED_CREDENTIAL: production worker security validation failed")
    tests = [path for path in owned if path.startswith("tests/") and path.endswith(".py")]
    if not tests:
        raise ProductionWorkerError("production worker focused test scope is missing")
    python = root / ".venv" / "bin" / "python"; pytest = root / ".venv" / "bin" / "pytest"
    if not python.is_file() or not pytest.is_file():
        raise ProductionWorkerError("registered project interpreter is unavailable")
    process_evidence.update(_focused_execution_metadata())
    process_path.write_bytes(canonical_json_bytes(process_evidence))
    commands = {
        "worker": {"command": argv, "exit_code": worker_exit, "timeout": timed_out,
                   "stdout_sha256": hashlib.sha256(stdout).hexdigest(), "stderr_sha256": hashlib.sha256(stderr).hexdigest()},
        "focused_test": _command(root, [str(pytest), "-q", *tests], classify_collection=True),
        "full_regression": _command(root, [str(pytest), "-q"]),
        "compile_import": _command(root, [str(python), "-m", "compileall", "-q", *owned]),
        "git_diff_check": _command(root, ["git", "diff", "--check"] if head == baseline else ["git", "diff", "--check", f"{baseline}..{head}"]),
    }
    process_evidence.update(_focused_execution_metadata(commands.get("focused_test")))
    process_evidence.update(_bounded_collection_diagnostics(
        root, pytest, python, tests, commands["focused_test"],
    ))
    process_evidence.update(_independent_verification_metadata(commands, len(request.task.validation_criteria)))
    process_evidence["independent_verification_steps"] = _independent_verification_steps(commands)
    process_evidence.update(_independent_verification_provenance(commands))
    process_path.write_bytes(canonical_json_bytes(process_evidence))
    validation_events = ["VALIDATION_STARTED"]
    validation_events.append("FOCUSED_TEST_COMPLETED")
    validation_events.append("FULL_REGRESSION_COMPLETED")
    verification = _independent_verification_provenance(commands)
    if verification["worker_verification_failure_step"] != "NONE":
        raise _independent_verification_failure(commands)
    if head == baseline:
        expected_changed = sorted(changed)
        added = _git(root, "add", "--", *changed)
        if added.returncode != 0:
            raise ProductionWorkerError("production checkpoint staging failed")
        committed = _git(
            root,
            "-c", f"user.name={CHECKPOINT_GIT_USER_NAME}",
            "-c", f"user.email={CHECKPOINT_GIT_USER_EMAIL}",
            "-c", "commit.gpgSign=false",
            "-c", "core.hooksPath=/dev/null",
            "commit", "-m", f"feat({request.contract_summary['lv_id']}): production machine checkpoint",
        )
        if committed.returncode != 0:
            diagnostic = (committed.stderr or "").lower()
            category = ("CHECKPOINT_IDENTITY_FAILURE"
                        if "identity" in diagnostic or "user.name" in diagnostic or "user.email" in diagnostic
                        else "CHECKPOINT_COMMIT_FAILURE")
            raise ProductionWorkerError(f"{category}: production checkpoint commit failed")
        head = _git(root, "rev-parse", "HEAD").stdout.strip()
        changed = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).stdout.splitlines()
        if sorted(changed) != expected_changed:
            raise ProductionWorkerError("CHECKPOINT_COMMIT_FAILURE: checkpoint changed-file set mismatch")
    status = _git(root, "status", "--porcelain=v1").stdout
    if status:
        raise ProductionWorkerError("production worker did not leave a clean repository")
    tree = _git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    baseline_tree = _git(root, "rev-parse", f"{baseline}^{{tree}}").stdout.strip()
    ids = {"project_id": request.contract_summary["project_id"], "gate_id": request.contract_summary["gate_id"],
           "lv_id": request.contract_summary["lv_id"], "run_id": request.extra_context["run_id"],
           "approval_event_id": request.extra_context["approval_event_id"],
           "plan_sha256": request.contract_summary["canonical_plan_sha256"]}
    evidence = {**ids, "schema_version":"orchestration.product-completion-evidence.v1",
        "status":"completed", "tests":list(request.task.validation_criteria),
        "attempt":int(request.extra_context["attempt"]), "completion_mode":"CODE_CHANGE", "owned_files":owned,
        "changed_files":changed, "baseline_head":baseline, "baseline_tree":baseline_tree,
        "current_head":head, "current_tree":tree, "checkpoint_commit":head, "commands":commands,
        "staged_changes":False, "unstaged_changes":False, "review_verdict":"PASS",
        "executor":{"identity":EXECUTOR_ID,"version":EXECUTOR_VERSION},
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "structured_event_contract_version": STRUCTURED_EVENT_CONTRACT_VERSION,
        "structured_event_summary": process_evidence.get("structured_events", {}),
        "governed_effect_evidence": list(
            process_evidence.get("governed_effect_evidence", [])
        ),
        "package_sha256":request.extra_context["package_manifest_sha256"],
        "preflight_evidence_sha256":request.extra_context.get("preflight_evidence_sha256", ""),
        "validation_events": validation_events + ["WORKER_RESULT_SEALED"],
        **{key: process_evidence[key] for key in (
            "independent_verification_status", "independent_verification_stage",
            "independent_verification_exit_category", "independent_test_count_bucket",
            "independent_expected_test_count_bucket", "independent_failure_category",
            "focused_full_failure_relation",
        ) if key in process_evidence},
        "independent_verification_steps": process_evidence.get("independent_verification_steps", []),
        "runtime_prompt_sha256": prompt_sha,
        "runtime_prompt_artifact": str(prompt_path),
        "final_message": final_message_metadata,
        "artifact_sha_chain":{"request":hashlib.sha256(canonical_json_bytes(request.to_dict())).hexdigest(),
                              "executor_output":hashlib.sha256(stdout+b"\0"+stderr).hexdigest(),
                              "process_evidence":hashlib.sha256(process_path.read_bytes()).hexdigest()}, "hard_stop":True}
    evidence["evidence_sha256"] = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    return evidence

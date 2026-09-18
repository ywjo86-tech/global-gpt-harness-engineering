"""Provider-neutral ACTION proposal generation with governed Broker effects."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from .codex_dynamic_transport import ToolRequestEnvelope
from .production_tool_transport import ProductionToolTransport
from .provider_router import RouterDecisionV2
from .schemas import WorkerRequest

PROPOSAL_SCHEMA_V1 = "orchestration.provider-action-proposal.v1"
PROVIDER_ACTION_BACKEND = "PROVIDER_ACTION"
MAX_PROPOSAL_WRITES = 64
MAX_WRITE_BYTES = 256 * 1024
MAX_PROPOSAL_BYTES = 1024 * 1024
MAX_PROPOSAL_GENERATION_ATTEMPTS = 2
_CONTEXT_EXTENSIONS = frozenset({".py", ".md", ".json", ".toml", ".yaml", ".yml", ".txt"})
_CONTEXT_EXCLUDED = frozenset({".git", ".venv", "node_modules", "_workspace", "dist", "build"})
_CONTEXT_EXCLUDED_PREFIXES = ("docs/history/",)
_TOKEN = re.compile(r"[a-z0-9_]{4,}")


class ProviderActionExecutionError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _extract_json_object(text: str) -> Mapping[str, Any]:
    raw = str(text).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, Mapping):
        return value
    if value is not None:
        raise ProviderActionExecutionError("provider ACTION proposal must be an object")

    fenced: list[Mapping[str, Any]] = []
    for block in re.findall(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", raw, flags=re.DOTALL | re.IGNORECASE):
        try:
            candidate = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, Mapping):
            fenced.append(candidate)
    schema_fenced = [item for item in fenced if item.get("schema_version") == PROPOSAL_SCHEMA_V1]
    if len(schema_fenced) == 1:
        return schema_fenced[0]
    if len(schema_fenced) > 1:
        raise ProviderActionExecutionError("provider ACTION proposal is ambiguous")
    if len(fenced) == 1:
        return fenced[0]

    decoder = json.JSONDecoder()
    embedded: list[Mapping[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            candidate, end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, Mapping) or (index, end) in seen_spans:
            continue
        seen_spans.add((index, end))
        if candidate.get("schema_version") == PROPOSAL_SCHEMA_V1:
            embedded.append(candidate)
    if len(embedded) == 1:
        return embedded[0]
    if len(embedded) > 1:
        raise ProviderActionExecutionError("provider ACTION proposal is ambiguous")
    raise ProviderActionExecutionError("provider ACTION proposal is not valid JSON")


def _owned_map(owned: list[str]) -> dict[str, str]:
    return {f"OWNED_{index:04d}": path for index, path in enumerate(owned, 1)}


def validate_action_proposal(
    payload: Mapping[str, Any], *, request: WorkerRequest,
    decision: RouterDecisionV2, baseline: str, owned: list[str],
) -> dict[str, Any]:
    expected = {"schema_version", "project_id", "run_id", "gate_id", "lv_id",
                "plan_sha256", "source_head", "writes", "summary"}
    if set(payload) != expected or payload.get("schema_version") != PROPOSAL_SCHEMA_V1:
        raise ProviderActionExecutionError("provider ACTION proposal schema mismatch")
    identities = {
        "project_id": request.contract_summary.get("project_id"),
        "run_id": request.extra_context.get("run_id"),
        "gate_id": request.contract_summary.get("gate_id"),
        "lv_id": request.contract_summary.get("lv_id"),
        "plan_sha256": request.contract_summary.get("canonical_plan_sha256"),
        "source_head": baseline,
    }
    if any(payload.get(key) != value for key, value in identities.items()):
        raise ProviderActionExecutionError("provider ACTION proposal identity mismatch")
    writes = payload.get("writes")
    if not isinstance(writes, list) or not writes or len(writes) > MAX_PROPOSAL_WRITES:
        raise ProviderActionExecutionError("provider ACTION proposal write set is invalid")
    bindings = _owned_map(owned)
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    total = 0
    for item in writes:
        if not isinstance(item, Mapping) or set(item) != {"owned_file_id", "relative_path", "content"}:
            raise ProviderActionExecutionError("provider ACTION write schema mismatch")
        file_id = str(item.get("owned_file_id", ""))
        relative_path = str(item.get("relative_path", ""))
        content = item.get("content")
        if file_id not in bindings or not isinstance(content, str):
            raise ProviderActionExecutionError("provider ACTION write binding is invalid")
        directory_scope = bindings[file_id].endswith("/")
        if directory_scope == (not relative_path):
            raise ProviderActionExecutionError("provider ACTION relative path binding is invalid")
        key = (file_id, relative_path)
        if key in seen:
            raise ProviderActionExecutionError("provider ACTION write target is duplicated")
        seen.add(key)
        size = len(content.encode("utf-8"))
        total += size
        if size > MAX_WRITE_BYTES or total > MAX_PROPOSAL_BYTES:
            raise ProviderActionExecutionError("provider ACTION proposal exceeds size limit")
        normalized.append({"owned_file_id": file_id, "relative_path": relative_path, "content": content})
    summary = str(payload.get("summary", "")).strip()
    if not summary or len(summary) > 2048:
        raise ProviderActionExecutionError("provider ACTION proposal summary is invalid")
    return {**dict(payload), "writes": normalized, "summary": summary,
            "provider_ref": decision.provider_ref, "model_ref": decision.model_ref}


def _context_tokens(request: WorkerRequest, owned: list[str]) -> set[str]:
    text = " ".join([request.task.input, *request.task.validation_criteria, *owned]).lower()
    stop = {"task", "test", "tests", "file", "files", "with", "from", "that", "this",
            "required", "validation", "implementation", "runtime", "owned", "cover", "including"}
    return {item for item in _TOKEN.findall(text) if item not in stop}


def select_action_context_files(project_root: Path, request: WorkerRequest, owned: list[str]) -> list[str]:
    """Select a bounded deterministic read context; it never expands write scope."""
    root = project_root.resolve()
    tokens = _context_tokens(request, owned)
    priority = [str(item) for item in request.task.input_files if str(item).strip()]
    priority.extend(path for path in owned if not path.endswith("/") and (root / path).is_file())
    candidates: dict[str, int] = {}
    for relative in priority:
        path = root / relative
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in _CONTEXT_EXTENSIONS:
            candidates[relative] = 100000
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in _CONTEXT_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        parts = relative.split("/")
        if (any(part in _CONTEXT_EXCLUDED or part.startswith(".env") for part in parts)
                or any(relative.startswith(prefix) for prefix in _CONTEXT_EXCLUDED_PREFIXES)):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > 16 * 1024:
            continue
        lower_path = relative.lower()
        score = sum(30 for token in tokens if token in lower_path)
        try:
            preview = path.read_text(encoding="utf-8", errors="replace")[:4096].lower()
        except OSError:
            continue
        score += sum(2 for token in tokens if token in preview)
        for owned_path in owned:
            owned_name = Path(owned_path.rstrip("/")).stem.lower()
            prefix = "_".join(part for part in owned_name.split("_")[:3] if part)
            if prefix and prefix in lower_path:
                score += 40
        if score:
            candidates[relative] = max(candidates.get(relative, 0), score)
    selected: list[str] = []
    total = 0
    for relative, _score in sorted(candidates.items(), key=lambda item: (-item[1], item[0])):
        path = root / relative
        size = path.stat().st_size
        if len(selected) >= 8 or total + size > 60 * 1024:
            continue
        selected.append(relative)
        total += size
        if len(selected) == 8:
            break
    return selected


def build_action_proposal_prompt(request: WorkerRequest, *, baseline: str, owned: list[str]) -> str:
    owned_rows = [{"owned_file_id": file_id, "path": path} for file_id, path in _owned_map(owned).items()]
    identity = {
        "project_id": request.contract_summary.get("project_id"), "run_id": request.extra_context.get("run_id"),
        "gate_id": request.contract_summary.get("gate_id"), "lv_id": request.contract_summary.get("lv_id"),
        "plan_sha256": request.contract_summary.get("canonical_plan_sha256"), "source_head": baseline,
    }
    criteria = list(request.task.validation_criteria)
    return (
        "Generate a governed ACTION change proposal only. Do not claim to have modified files, run shell, Git, tests, "
        "network, approvals, or state transitions. The Harness Execution Backend applies approved writes and validates them.\n"
        f"Task: {request.task.input}\nCompletion criteria: {json.dumps(criteria, ensure_ascii=False)}\n"
        f"Owned file mapping: {json.dumps(owned_rows, ensure_ascii=False)}\n"
        "Use the supplied read-only context files to match the existing codebase. For exact-file owned scopes set relative_path "
        "to an empty string. For directory scopes, provide a safe child relative_path. Each write content must be the COMPLETE "
        "target file content, not a diff. Do not write outside the owned mapping.\n"
        "Return exactly one JSON object and no prose or Markdown fences. Required shape:\n"
        f"{{\"schema_version\":\"{PROPOSAL_SCHEMA_V1}\",\"project_id\":{json.dumps(identity['project_id'])},"
        f"\"run_id\":{json.dumps(identity['run_id'])},\"gate_id\":{json.dumps(identity['gate_id'])},"
        f"\"lv_id\":{json.dumps(identity['lv_id'])},\"plan_sha256\":{json.dumps(identity['plan_sha256'])},"
        f"\"source_head\":{json.dumps(identity['source_head'])},"
        "\"writes\":[{\"owned_file_id\":\"OWNED_0001\",\"relative_path\":\"\",\"content\":\"complete content\"}],"
        "\"summary\":\"bounded implementation summary\"}"
    )


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical(payload)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())


def _retryable_output_contract_error(exc: ProviderActionExecutionError) -> bool:
    message = str(exc)
    return message in {
        "provider ACTION proposal is not valid JSON",
        "provider ACTION proposal must be an object",
        "provider ACTION proposal is ambiguous",
        "provider ACTION proposal schema mismatch",
        "provider ACTION proposal write set is invalid",
        "provider ACTION write schema mismatch",
        "provider ACTION proposal summary is invalid",
    }


def _correction_prompt(base_prompt: str) -> str:
    return (
        base_prompt
        + "\nCORRECTION RETRY: The previous response did not satisfy the required JSON output contract. "
          "Do not repeat analysis or prose. Return exactly one JSON object matching the required shape. "
          "Do not change project/run/Gate/LV/plan/source identity or owned-file scope."
    )


def execute_provider_action_proposal(
    request: WorkerRequest, *, decision: RouterDecisionV2, baseline: str,
    owned: list[str], output_dir: Path, provider_runner: Callable[..., Mapping[str, Any]],
    security_scan: Callable[[bytes], bool], timeout: int,
) -> dict[str, Any]:
    if not decision.eligible or decision.stage != "ACTION" or not decision.provider_ref or not decision.model_ref:
        raise ProviderActionExecutionError("provider ACTION route is not eligible")
    context_files = select_action_context_files(Path(request.project_root), request, owned)
    prompt = build_action_proposal_prompt(request, baseline=baseline, owned=owned)
    result: Mapping[str, Any] = {}
    proposal: dict[str, Any] | None = None
    generation_attempts = 0
    for generation_attempt in range(1, MAX_PROPOSAL_GENERATION_ATTEMPTS + 1):
        generation_attempts = generation_attempt
        result = provider_runner(
            prompt=prompt if generation_attempt == 1 else _correction_prompt(prompt),
            project_root=request.project_root, input_files=context_files,
            model=decision.model_ref, require_explicit_model=True,
            fallback_models=decision.model_fallback_refs, json_mode=True,
            timeout_seconds=float(min(timeout, 180)), max_tokens=8192,
        )
        if result.get("status") != "completed":
            error = str(result.get("provider_error_class", "provider_failure"))
            raise ProviderActionExecutionError(f"provider ACTION generation failed:{error}")
        try:
            proposal = validate_action_proposal(
                _extract_json_object(str(result.get("summary", ""))), request=request,
                decision=decision, baseline=baseline, owned=owned,
            )
            break
        except ProviderActionExecutionError as exc:
            if generation_attempt >= MAX_PROPOSAL_GENERATION_ATTEMPTS or not _retryable_output_contract_error(exc):
                raise
    if proposal is None:
        raise ProviderActionExecutionError("provider ACTION proposal validation did not complete")
    proposal_digest = _digest({key: value for key, value in proposal.items()
                               if key not in {"provider_ref", "model_ref"}})
    # Provider output is untrusted until the existing production security scan
    # accepts the complete proposal.  Never persist raw rejected content.
    if not security_scan(_canonical(proposal)):
        raise ProviderActionExecutionError("provider ACTION proposal failed security validation")
    proposal_path = output_dir / "provider-action-proposal.json"
    _write_private_json(proposal_path, proposal)
    broker_request = {
        "project_id": request.contract_summary.get("project_id"),
        "run_id": request.extra_context.get("run_id"),
        "gate_id": request.contract_summary.get("gate_id"),
        "lv_id": request.contract_summary.get("lv_id"),
        "attempt": request.extra_context.get("attempt", 1),
        "canonical_plan_sha256": request.contract_summary.get("canonical_plan_sha256"),
        "requirement_digest": request.extra_context.get("requirement_digest", ""),
        "owned_files": list(owned),
        "active_tool_authorization_contracts": list(request.extra_context.get("active_tool_authorization_contracts", [])),
        "tool_authorization_projection": dict(request.extra_context.get("tool_authorization_projection", {})),
    }
    projection = broker_request["tool_authorization_projection"]
    worker_task_id = projection.get("worker_task_id") if isinstance(projection, Mapping) else None
    if not isinstance(worker_task_id, str) or not worker_task_id:
        raise ProviderActionExecutionError("provider ACTION worker task authority is missing")
    transport = ProductionToolTransport(
        request=broker_request, workspace_root=Path(request.project_root),
        journal_root=output_dir / "provider-action-effects", security_scan=security_scan,
        operation_callsite_id="PROVIDER_ACTION_PROPOSAL_V1",
    )
    results: list[dict[str, Any]] = []
    for index, write in enumerate(proposal["writes"], 1):
        arguments = {"owned_file_id": write["owned_file_id"], "content": write["content"]}
        if write["relative_path"]:
            arguments["relative_path"] = write["relative_path"]
        response = transport.handle(ToolRequestEnvelope(
            "PROJECT_OWNED_FILE_WRITE", worker_task_id, f"PROVIDER_ACTION_{index:04d}",
            arguments, f"{decision.provider_ref}-{proposal_digest[:24]}-{index:04d}",
        ))
        if response.status != "COMPLETED" or response.security_status != "PASS":
            raise ProviderActionExecutionError("provider ACTION Broker effect was not completed")
        results.append({"status": response.status, "security_status": response.security_status})
    return {
        "provider": decision.provider_ref,
        "routed_model": decision.model_ref,
        "actual_model": str(result.get("model", decision.model_ref)),
        "router_decision_digest": decision.decision_digest,
        "provider_attempts": int(result.get("provider_attempts", 0)),
        "proposal_generation_attempts": generation_attempts,
        "model_failover_used": bool(result.get("model_failover_used", False)),
        "proposal_digest": proposal_digest,
        "proposal_path": str(proposal_path),
        "proposal_summary": proposal["summary"],
        "context_files": context_files,
        "context_metadata": dict(result.get("context_metadata") or {}),
        "write_results": results,
        "governed_effect_evidence": [item.canonical_projection() for item in transport.governed_effect_evidence()],
    }

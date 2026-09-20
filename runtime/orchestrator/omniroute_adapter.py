from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .context_sanitizer import ContextSanitizationError, sanitize_context
from .provider_candidate_inventory import ProviderCandidateRecordV1

OMNIROUTE_BASE_URL = "http://127.0.0.1:20128/v1"


class OmniRouteAdapterError(ValueError):
    pass


def _header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value).strip()
    return ""


def validate_target_binding(headers: Mapping[str, Any], *, expected_provider: str, expected_model: str) -> None:
    provider = _header(headers, "X-OmniRoute-Provider")
    model = _header(headers, "X-OmniRoute-Model")
    fallback_raw = _header(headers, "X-OmniRoute-Fallback-Attempts") or "0"
    try:
        fallback_attempts = int(fallback_raw)
    except ValueError as exc:
        raise OmniRouteAdapterError("target binding mismatch") from exc
    if provider != expected_provider or model != expected_model or fallback_attempts != 0:
        raise OmniRouteAdapterError("target binding mismatch")


def normalize_omniroute_result(*, expected_provider: str, expected_model: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    headers = raw.get("headers", {})
    payload = raw.get("payload", {})
    if not isinstance(headers, Mapping) or not isinstance(payload, Mapping):
        raise OmniRouteAdapterError("invalid OmniRoute response")
    validate_target_binding(headers, expected_provider=expected_provider, expected_model=expected_model)
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OmniRouteAdapterError("invalid OmniRoute response") from exc
    if not isinstance(content, str) or not content.strip():
        raise OmniRouteAdapterError("invalid OmniRoute response")
    return {
        "status": "completed",
        "mode": "omniroute",
        "provider": expected_provider,
        "model": expected_model,
        "routed_model": expected_model,
        "model_failover_used": False,
        "model_failover_trace": [],
        "provider_attempts": 1,
        "summary": content,
        "findings": [], "warnings": [], "errors": [],
    }


def _load_api_key(secret_file: str | Path | None = None) -> str:
    env = os.environ.get("OMNIROUTE_API_KEY", "").strip()
    if env:
        return env
    path = Path(secret_file or Path.home() / ".config/gch/omniroute.env").expanduser()
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OmniRouteAdapterError("OmniRoute secret source is unsafe")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("OMNIROUTE_API_KEY="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise OmniRouteAdapterError("OmniRoute API key unavailable")


def run_omniroute_provider(
    *, prompt: str, provider: str, model: str, project_root: str = ".",
    input_files: list[str] | tuple[str, ...] | None = None,
    connection_id: str = "", api_key: str | None = None,
    require_explicit_model: bool = True, fallback_models: list[str] | tuple[str, ...] | None = None,
    timeout_seconds: float = 30.0, max_retries: int = 0, max_tokens: int = 2048,
    json_mode: bool = False, opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    provider = str(provider).strip().lower(); model = str(model).strip()
    fallbacks = tuple(str(x).strip() for x in (fallback_models or ()) if str(x).strip())
    if not provider or not model or model.lower() == "auto" or model.lower().endswith(":auto"):
        raise OmniRouteAdapterError("explicit provider/model target required")
    if fallbacks or int(max_retries) != 0:
        raise OmniRouteAdapterError("nested provider/model fallback is forbidden")
    key = (api_key or _load_api_key()).strip()
    if not key:
        raise OmniRouteAdapterError("OmniRoute API key unavailable")
    try:
        context = sanitize_context(prompt, input_files or (), project_root, known_secret_values=(key,))
    except ContextSanitizationError as exc:
        return {"status": "provider_failed", "provider": provider, "model": model,
                "provider_error_class": "context_security_rejected", "errors": [str(exc)], "provider_attempts": 0}
    messages = [{"role": "user", "content": context.prompt}]
    messages.extend({"role": "user", "content": f"File: {f['path']}\n{f['content']}"} for f in context.files)
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0, "stream": False, "max_tokens": int(max_tokens)}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if connection_id:
        headers["X-OmniRoute-Connection"] = connection_id
    req = urllib.request.Request(OMNIROUTE_BASE_URL + "/chat/completions", data=json.dumps(body).encode(), headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=float(timeout_seconds)) as response:
            payload = json.loads(response.read().decode("utf-8"))
            raw_headers = dict(response.headers.items()) if hasattr(response.headers, "items") else dict(response.headers)
        result = normalize_omniroute_result(expected_provider=provider, expected_model=model, raw={"headers": raw_headers, "payload": payload})
        result["context_metadata"] = context.metadata
        return result
    except OmniRouteAdapterError:
        raise
    except urllib.error.HTTPError as exc:
        cls = "omniroute_auth_error" if exc.code in {401, 403} else "omniroute_rate_limit" if exc.code == 429 else "omniroute_http_error"
    except (TimeoutError, urllib.error.URLError):
        cls = "omniroute_network_error"
    except (json.JSONDecodeError, UnicodeError, TypeError, KeyError, IndexError, ValueError):
        cls = "omniroute_invalid_response"
    return {"status": "provider_failed", "provider": provider, "model": model,
            "provider_error_class": cls, "errors": [cls], "provider_attempts": 1}


def make_omniroute_runner(record: ProviderCandidateRecordV1, *, api_key: str | None = None,
                          opener: Callable[..., Any] | None = None) -> Callable[..., Mapping[str, Any]]:
    if record.state != "ACTIVE":
        raise OmniRouteAdapterError("ACTIVE candidate required")
    bound_model = record.model_refs[0]
    def runner(**kwargs: Any) -> Mapping[str, Any]:
        requested_model = str(kwargs.get("model", "")).strip()
        if requested_model != bound_model:
            return {"status": "provider_failed", "provider": record.provider_id, "model": requested_model,
                    "provider_error_class": "omniroute_target_binding_error", "errors": ["omniroute_target_binding_error"], "provider_attempts": 0}
        try:
            return run_omniroute_provider(
                prompt=str(kwargs.get("prompt", "")), provider=record.provider_id, model=requested_model,
                project_root=str(kwargs.get("project_root", ".")), input_files=kwargs.get("input_files") or (),
                connection_id=record.connection_id, api_key=api_key, require_explicit_model=True,
                fallback_models=kwargs.get("fallback_models") or (), timeout_seconds=float(kwargs.get("timeout_seconds", 30.0)),
                max_retries=int(kwargs.get("max_retries", 0)), max_tokens=int(kwargs.get("max_tokens", 2048)),
                json_mode=bool(kwargs.get("json_mode", False)), opener=opener,
            )
        except OmniRouteAdapterError as exc:
            return {"status": "provider_failed", "provider": record.provider_id, "model": requested_model,
                    "provider_error_class": "omniroute_target_binding_error", "errors": [str(exc)], "provider_attempts": 0}
    return runner


def make_omniroute_task_adapter(record: ProviderCandidateRecordV1, *, api_key: str | None = None,
                                opener: Callable[..., Any] | None = None):
    runner = make_omniroute_runner(record, api_key=api_key, opener=opener)
    def adapter(task: Any, decision: Any, project_root: str) -> Mapping[str, Any]:
        return runner(prompt=task.input, project_root=project_root, input_files=task.input_files,
                      model=decision.model_ref, require_explicit_model=True,
                      fallback_models=decision.model_fallback_refs, max_retries=0)
    return adapter

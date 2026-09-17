from __future__ import annotations

import json
import math
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .context_sanitizer import ContextSanitizationError, sanitize_context


DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_TOKENS = 2048


def _failure(error_class: str, *, model: str = "", attempts: int = 0) -> dict[str, Any]:
    return {
        "status": "provider_failed",
        "mode": "nvidia",
        "provider": "nvidia",
        **({"model": model} if model else {}),
        "provider_error_class": error_class,
        "errors": [error_class],
        "provider_attempts": attempts,
    }


def _float_config(name: str, override: float | None, default: float) -> float:
    value = override if override is not None else os.environ.get(name, str(default))
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(name)
    return parsed


def _int_config(name: str, override: int | None, default: int, *, minimum: int) -> int:
    value = override if override is not None else os.environ.get(name, str(default))
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError(name)
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(name)
    return parsed


def run_nvidia_reasoning_task(
    *,
    prompt: str,
    output_dir: str = "",
    project_root: str = ".",
    input_files: list[str] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: float | None = None,
    max_tokens: int | None = None,
    require_explicit_model: bool = False,
    urlopen: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    try:
        context = sanitize_context(prompt, input_files or [], project_root)
    except ContextSanitizationError as exc:
        return _failure("context_security_rejected")

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    selected_model = ((model if require_explicit_model else (model or os.environ.get("NVIDIA_MODEL", ""))) or "").strip()
    endpoint_base = (base_url or os.environ.get("NVIDIA_ENDPOINT", DEFAULT_BASE_URL)).strip().rstrip("/")
    try:
        configured_timeout = _float_config("NVIDIA_TIMEOUT_SECONDS", timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
        configured_retries = _int_config("NVIDIA_MAX_RETRIES", max_retries, DEFAULT_MAX_RETRIES, minimum=0)
        configured_backoff = _float_config(
            "NVIDIA_RETRY_BACKOFF_SECONDS", retry_backoff_seconds, DEFAULT_RETRY_BACKOFF_SECONDS
        )
        configured_max_tokens = _int_config("NVIDIA_MAX_TOKENS", max_tokens, DEFAULT_MAX_TOKENS, minimum=1)
    except (TypeError, ValueError, OverflowError):
        return _failure("nvidia_config_error", model=selected_model)
    if not api_key or not selected_model or not endpoint_base.startswith("https://"):
        return _failure("nvidia_config_error", model=selected_model)
    endpoint = endpoint_base + "/chat/completions"

    messages = [{"role": "user", "content": context.prompt}]
    for item in context.files:
        messages.append({"role": "user", "content": f"File: {item['path']}\n{item['content']}"})
    body = json.dumps(
        {
            "model": selected_model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "max_tokens": configured_max_tokens,
        }
    ).encode("utf-8")
    opener = urlopen or urllib.request.urlopen
    last_error = "nvidia_network_error"
    attempts = 1 + configured_retries
    attempts_used = 0
    for attempt in range(1, attempts + 1):
        attempts_used = attempt
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener(req, timeout=configured_timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty provider content")
            return {
                "status": "completed",
                "mode": "nvidia",
                "provider": "nvidia",
                "model": selected_model,
                "route_reason": "nvidia_read_only",
                "summary": str(content),
                "findings": [],
                "warnings": [],
                "errors": [],
                "provider_attempts": attempt,
                "context_metadata": context.metadata,
            }
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                last_error = "nvidia_auth_error"
            elif exc.code == 408:
                last_error = "nvidia_timeout"
            elif exc.code == 429:
                last_error = "nvidia_rate_limit"
            elif 500 <= exc.code <= 599:
                last_error = "nvidia_server_error"
            else:
                last_error = "nvidia_client_error"
            if exc.code not in {408, 429} and not 500 <= exc.code <= 599:
                break
        except (TimeoutError, socket.timeout):
            last_error = "nvidia_timeout"
        except urllib.error.URLError as exc:
            last_error = "nvidia_timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "nvidia_network_error"
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            last_error = "nvidia_invalid_response"
            break
        if attempt < attempts:
            time.sleep(configured_backoff * (2 ** (attempt - 1)))
    return _failure(last_error, model=selected_model, attempts=attempts_used)

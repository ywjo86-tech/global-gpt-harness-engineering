from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_MAX_FILES = 8
DEFAULT_MAX_FILE_BYTES = 16 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|password|secret|token)\s*[:=]\s*([^\s]+)"
)
FORBIDDEN_PARTS = {".env", ".git", ".ssh", ".gnupg"}


class ContextSanitizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SanitizedContext:
    prompt: str
    files: tuple[dict[str, str], ...]
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _redact(text: str, known_secret_values: Iterable[str]) -> str:
    redacted = SECRET_PATTERN.sub(lambda m: f"{m.group(1)}=[REDACTED_SECRET]", text)
    for value in known_secret_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED_SECRET]")
    return redacted


def _safe_relative_path(project_root: Path, rel_path: str) -> Path:
    if not rel_path or Path(rel_path).is_absolute():
        raise ContextSanitizationError("input_path_not_relative")
    candidate = (project_root / rel_path).resolve()
    root = project_root.resolve()
    if root not in candidate.parents and candidate != root:
        raise ContextSanitizationError("input_path_outside_project")
    if any(part in FORBIDDEN_PARTS or part.startswith(".env") for part in candidate.parts):
        raise ContextSanitizationError("input_path_forbidden")
    return candidate


def sanitize_context(
    prompt: str,
    input_files: Iterable[str] | None,
    project_root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    known_secret_values: Iterable[str] | None = None,
) -> SanitizedContext:
    root = Path(project_root).resolve()
    file_list = [str(item) for item in (input_files or []) if str(item).strip()]
    if len(file_list) > max_files:
        raise ContextSanitizationError("too_many_input_files")

    secrets = list(known_secret_values or [])
    env_secret = os.environ.get("NVIDIA_API_KEY", "")
    if env_secret:
        secrets.append(env_secret)
    safe_prompt = _redact(str(prompt), secrets)
    safe_files: list[dict[str, str]] = []
    total_bytes = 0
    for rel in file_list:
        path = _safe_relative_path(root, rel)
        if not path.is_file():
            raise ContextSanitizationError("input_file_missing")
        data = path.read_bytes()
        if len(data) > max_file_bytes:
            raise ContextSanitizationError("input_file_too_large")
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise ContextSanitizationError("total_context_too_large")
        text = data.decode("utf-8", errors="replace")
        safe_files.append({"path": rel, "content": _redact(text, secrets)})

    combined = safe_prompt + "\n".join(item["content"] for item in safe_files)
    if any(secret and secret in combined for secret in secrets):
        raise ContextSanitizationError("secret_post_scan_failed")
    return SanitizedContext(
        prompt=safe_prompt,
        files=tuple(safe_files),
        metadata={"file_count": len(safe_files), "total_file_bytes": total_bytes, "redaction_applied": "[REDACTED_SECRET]" in combined},
    )

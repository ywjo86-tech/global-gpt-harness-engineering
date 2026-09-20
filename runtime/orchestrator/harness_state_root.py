"""Stable durable state-root helpers for Full Plan runtime evidence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Any, Iterable

STATE_ROOT_ENV = "GCH_STATE_ROOT"


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor) if path.anchor else Path()
    for part in path.parts[1:] if path.anchor else path.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("harness state root contains a symlink component")


def resolve_harness_state_root(
    *, project_root: str | Path, environ: Mapping[str, str] | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    explicit = str(env.get(STATE_ROOT_ENV) or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().absolute()
    else:
        xdg = str(env.get("XDG_STATE_HOME") or "").strip()
        base = Path(xdg).expanduser().absolute() if xdg else (Path.home() / ".local" / "state").absolute()
        candidate = base / "global-gpt-harness"
    _reject_symlink_components(candidate)
    root = candidate.resolve(strict=False)
    project = Path(project_root).expanduser().resolve()
    if root == project or project in root.parents:
        raise ValueError("harness state root must be independent of project worktree")
    return root


def job_state_root(job: Mapping[str, Any]) -> Path:
    value = job.get("harness_state_root") or job.get("harness_root")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("job durable state root is missing")
    return Path(value).expanduser().resolve()


def discovery_roots(search_root: str | Path, legacy_roots: Iterable[str | Path] = ()) -> tuple[Path, ...]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    for value in (search_root, *tuple(legacy_roots)):
        root = Path(value).expanduser().resolve()
        if root in seen:
            continue
        seen.add(root); ordered.append(root)
    return tuple(ordered)


def job_dedupe_key(job: Mapping[str, Any], *, source_path: str | Path | None = None) -> tuple[str, str, str]:
    project_id = str(job.get("project_id") or "")
    run_id = str(job.get("run_id") or "")
    authority = str(job.get("authority_core_sha256") or "")
    if not authority:
        fallback = str(job.get("harness_state_root") or job.get("harness_root") or source_path or "")
        authority = f"LEGACY:{Path(fallback).expanduser().resolve() if fallback else ''}"
    return project_id, run_id, authority

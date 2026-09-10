"""Canonical, identity-bound artifact namespaces for production lifecycle."""
from pathlib import Path, PurePosixPath
import re

_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

def canonical_run_root(harness_root: str | Path, *, run_id: str, lv_id: str) -> Path:
    """Canonical hctl/production run root for one RUN_ID/LV binding."""
    if not all(isinstance(v, str) and _IDENTITY.fullmatch(v) for v in (run_id, lv_id)):
        raise ValueError("invalid canonical run identity")
    return Path(harness_root).resolve() / "_workspace" / "orchestration-runs" / run_id / lv_id

def canonical_lv_path(harness_root: str | Path, *, project_id: str, run_id: str,
                      gate_id: str, lv_id: str, attempt: int | None = None,
                      recovery_id: str | None = None) -> Path:
    values = (project_id, run_id, gate_id, lv_id)
    if not all(isinstance(v, str) and _IDENTITY.fullmatch(v) for v in values):
        raise ValueError("invalid canonical artifact identity")
    if attempt is not None and (isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0):
        raise ValueError("invalid canonical attempt")
    if recovery_id is not None and (not isinstance(recovery_id, str) or not _IDENTITY.fullmatch(recovery_id)):
        raise ValueError("invalid canonical recovery identity")
    root = Path(harness_root).resolve()
    path = root / "_workspace" / "orchestration-runs" / run_id / lv_id
    if attempt is not None:
        path = path / f"attempt-{attempt:02d}"
    if recovery_id is not None:
        path = path / recovery_id
    return path

"""Filesystem and freshness safeguards for diagnostic analyzers."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .contracts import SourceSnapshotBinding


class DiagnosticStaleError(RuntimeError):
    pass


class DiagnosticSecurityError(ValueError):
    pass


_EXCLUDED_PARTS = frozenset({
    ".git", "_workspace", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
})
_SECRET_TOKENS = (".env", "secret", "credential", "token", "apikey", "api_key", "private_key", "id_rsa")


def _excluded(relative: Path) -> bool:
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    lowered = relative.as_posix().lower()
    return any(token in lowered for token in _SECRET_TOKENS)


def _listed_files(root: Path) -> list[Path]:
    command = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
    if completed.returncode != 0:
        raise DiagnosticSecurityError("unable to enumerate source snapshot")
    return [Path(raw.decode("utf-8", "surrogateescape")) for raw in completed.stdout.split(b"\0") if raw]

def assert_binding_current(binding: SourceSnapshotBinding, project_root: str | Path) -> None:
    current = SourceSnapshotBinding.capture(
        project_root, project_id=binding.project_id, owned_paths=binding.owned_paths,
    )
    if (
        current.git_head_sha != binding.git_head_sha
        or current.workspace_tree_digest != binding.workspace_tree_digest
        or current.owned_scope_digest != binding.owned_scope_digest
    ):
        raise DiagnosticStaleError("CODE_INTELLIGENCE_STALE")


def prepare_source_snapshot(
    project_root: str | Path,
    analysis_root: str | Path,
    binding: SourceSnapshotBinding,
) -> Path:
    root = Path(project_root).resolve()
    destination_root = Path(analysis_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise DiagnosticSecurityError("source root is unsafe")
    assert_binding_current(binding, root)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / "source-snapshot"
    temporary = destination_root / f"source-snapshot.new-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)

    try:
        for relative in _listed_files(root):
            if relative.is_absolute() or ".." in relative.parts or _excluded(relative):
                continue
            source = root / relative
            if not source.is_file() or source.is_symlink():
                continue
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        assert_binding_current(binding, root)
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise DiagnosticSecurityError("snapshot destination is unsafe")
            shutil.rmtree(destination)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

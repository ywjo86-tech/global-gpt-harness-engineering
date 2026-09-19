"""Git ancestry helpers that preserve historical touched-path provenance."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitProvenanceError(ValueError):
    pass


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise GitProvenanceError("git provenance verification failed")
    return completed.stdout


def is_ancestor(root: str | Path, baseline: str, current: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(Path(root)), "merge-base", "--is-ancestor", baseline, current],
        capture_output=True, text=True, check=False, timeout=30,
    )
    return completed.returncode == 0


def touched_paths_between(root: str | Path, baseline: str, current: str) -> tuple[str, ...]:
    """Return the union of paths touched by every commit in baseline..current.

    This intentionally records historical touches even when a later commit
    reverts the final tree back to its baseline content.
    """
    repo = Path(root)
    if baseline == current:
        return ()
    if not is_ancestor(repo, baseline, current):
        raise GitProvenanceError("baseline is not an ancestor of current HEAD")
    commits = [item for item in _run(repo, "rev-list", "--reverse", f"{baseline}..{current}").splitlines() if item]
    touched: set[str] = set()
    for commit in commits:
        names = _run(repo, "diff-tree", "-m", "--root", "--no-commit-id", "--name-only", "-r", commit)
        touched.update(path for path in names.splitlines() if path)
    return tuple(sorted(touched))

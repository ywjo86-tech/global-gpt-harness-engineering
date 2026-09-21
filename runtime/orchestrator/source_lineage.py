"""Git source-lineage verification for approved AUTO continuation."""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

from .gate_continuation_contract import GateContinuationContract

_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class SourceLineageError(ValueError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=20)
    if check and completed.returncode != 0:
        raise SourceLineageError((completed.stderr or completed.stdout or "Git lineage verification failed").strip())
    return completed.stdout.strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True, text=True, check=False, timeout=20,
    ).returncode == 0


def _paths_digest(paths: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(paths).encode("utf-8")).hexdigest()


def _path_allowed(path: str, contract: GateContinuationContract) -> bool:
    if any(path == value.rstrip("/") or path.startswith(value) for value in contract.forbidden_paths):
        return False
    return any(path == value.rstrip("/") or path.startswith(value) for value in contract.allowed_write_paths)


@dataclass(frozen=True, slots=True)
class SourceLineageEvidence:
    approved_base_head: str
    lineage_anchor_head: str
    current_head: str
    current_tree_sha256: str
    changed_paths: tuple[str, ...]
    changed_paths_sha256: str
    source_lineage_policy: str
    previous_receipt_source_head: str = ""


def verify_source_lineage(
    contract: GateContinuationContract, repo_root: str | Path, *,
    previous_receipt: Mapping[str, Any] | None = None, current_head: str | None = None,
) -> SourceLineageEvidence:
    root = Path(repo_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise SourceLineageError("repository root is invalid")
    current = str(current_head or _git(root, "rev-parse", "HEAD"))
    if not _SHA.fullmatch(current):
        raise SourceLineageError("current source head is invalid")
    base = contract.approved_base_head
    previous = ""
    anchor = base
    if contract.source_lineage_policy == "EXACT_BASE":
        if current != base:
            raise SourceLineageError("EXACT_BASE requires the approved base head")
    elif contract.source_lineage_policy == "APPROVED_DESCENDANT_CHAIN":
        if not _is_ancestor(root, base, current):
            raise SourceLineageError("current head is not a descendant of approved base")
        if previous_receipt is not None:
            if str(previous_receipt.get("schema_version") or "") != "orchestration.operator-plan-receipt.v2":
                raise SourceLineageError("previous receipt lineage requires v2 receipt")
            previous = str(previous_receipt.get("source_head") or "")
            if not _SHA.fullmatch(previous) or not _is_ancestor(root, base, previous) or not _is_ancestor(root, previous, current):
                raise SourceLineageError("previous receipt lineage mismatch")
            anchor = previous
    else:
        raise SourceLineageError("unsupported source lineage policy")
    tree = _git(root, "rev-parse", f"{current}^{{tree}}")
    if anchor == current:
        paths: tuple[str, ...] = ()
    else:
        output = _git(root, "diff", "--name-only", f"{anchor}..{current}")
        paths = tuple(sorted(line for line in output.splitlines() if line))
    outside = tuple(path for path in paths if not _path_allowed(path, contract))
    if outside:
        raise SourceLineageError("changed paths exceed approved Gate scope: " + ",".join(outside))
    return SourceLineageEvidence(
        approved_base_head=base, lineage_anchor_head=anchor, current_head=current,
        current_tree_sha256=tree, changed_paths=paths, changed_paths_sha256=_paths_digest(paths),
        source_lineage_policy=contract.source_lineage_policy, previous_receipt_source_head=previous,
    )

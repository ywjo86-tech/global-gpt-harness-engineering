"""Strict evidence-only adoption of an already completed Full Plan LV prefix.

This module never selects a provider, executes an action, or changes Gate authority.
It only verifies historical Git checkpoints and sealed validation evidence so a
canonical Gate lifecycle can resume after an explicitly adopted ordered prefix.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "orchestration.full-plan-prefix-adoption.v1"
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class PrefixAdoptionError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False, timeout=20)
    if completed.returncode != 0:
        raise PrefixAdoptionError("prefix adoption Git verification failed")
    return completed.stdout.strip()


def _paths(value: object, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise PrefixAdoptionError(f"{label} is missing")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw or "\\" in raw:
            raise PrefixAdoptionError(f"{label} is unsafe")
        is_dir = raw.endswith("/")
        normalized = raw.rstrip("/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != normalized:
            raise PrefixAdoptionError(f"{label} is unsafe")
        result.append(normalized + ("/" if is_dir else ""))
    if len(result) != len(set(result)):
        raise PrefixAdoptionError(f"{label} contains duplicates")
    return result


def _within(path: str, scopes: Sequence[str]) -> bool:
    return any(path == scope.rstrip("/") or (scope.endswith("/") and path.startswith(scope)) for scope in scopes)


def _validate_validation_results(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise PrefixAdoptionError("prefix adoption validation evidence is missing")
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"command", "exit_code", "stdout_sha256", "stderr_sha256"}:
            raise PrefixAdoptionError("prefix adoption validation evidence schema mismatch")
        command = item.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise PrefixAdoptionError("prefix adoption validation command is invalid")
        if item.get("exit_code") != 0:
            raise PrefixAdoptionError("prefix adoption validation did not pass")
        if not _SHA64.fullmatch(str(item.get("stdout_sha256", ""))) or not _SHA64.fullmatch(str(item.get("stderr_sha256", ""))):
            raise PrefixAdoptionError("prefix adoption validation digest is invalid")


def validate_prefix_adoption(
    project_root: str | Path,
    evidence: Mapping[str, Any],
    *,
    project_id: str,
    gate_id: str,
    plan_sha256: str,
    branch: str,
    approval_head: str,
    lv_order: Sequence[str],
    owned_files_by_lv: Mapping[str, Sequence[str]],
    validation_ids_by_lv: Mapping[str, Sequence[str]],
    require_adoption_head: bool,
) -> dict[str, Any]:
    """Validate a sealed ordered-prefix adoption record and return LV evidence digests."""
    root = Path(project_root).resolve()
    if not root.is_dir() or root.is_symlink() or not isinstance(evidence, Mapping):
        raise PrefixAdoptionError("prefix adoption input is invalid")
    required = {"schema_version", "project_id", "gate_id", "plan_sha256", "branch", "approval_head",
                "adopted_lvs", "adoption_head", "entries", "record_sha256"}
    if set(evidence) != required or evidence.get("schema_version") != SCHEMA_VERSION:
        raise PrefixAdoptionError("prefix adoption record schema mismatch")
    unsigned = {k: v for k, v in evidence.items() if k != "record_sha256"}
    if evidence.get("record_sha256") != _digest(unsigned):
        raise PrefixAdoptionError("prefix adoption record digest mismatch")
    expected = {"project_id": project_id, "gate_id": gate_id, "plan_sha256": plan_sha256,
                "branch": branch, "approval_head": approval_head}
    if any(evidence.get(k) != v for k, v in expected.items()):
        raise PrefixAdoptionError("prefix adoption authority binding mismatch")
    adopted = evidence.get("adopted_lvs")
    if not isinstance(adopted, list) or not adopted or len(adopted) >= len(lv_order) or adopted != list(lv_order[:len(adopted)]):
        raise PrefixAdoptionError("adopted LVs must be a strict ordered Gate prefix")
    entries = evidence.get("entries")
    if not isinstance(entries, list) or len(entries) != len(adopted):
        raise PrefixAdoptionError("prefix adoption entry coverage mismatch")
    current_branch = _git(root, "branch", "--show-current")
    current_head = _git(root, "rev-parse", "HEAD")
    adoption_head = evidence.get("adoption_head")
    if current_branch != branch or not isinstance(adoption_head, str) or not _SHA40.fullmatch(adoption_head):
        raise PrefixAdoptionError("prefix adoption branch/head binding mismatch")
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", approval_head, adoption_head], check=False).returncode != 0:
        raise PrefixAdoptionError("approval head is not an ancestor of adoption head")
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", adoption_head, current_head], check=False).returncode != 0:
        raise PrefixAdoptionError("adoption head is not an ancestor of current HEAD")
    if require_adoption_head and current_head != adoption_head:
        raise PrefixAdoptionError("initial prefix adoption requires exact adoption HEAD")
    if _git(root, "status", "--porcelain=v1", "-uall"):
        raise PrefixAdoptionError("prefix adoption requires a clean worktree")

    adopted_scopes: list[str] = []
    for lv_id in adopted:
        adopted_scopes.extend(list(owned_files_by_lv.get(lv_id, ())))
    previous_checkpoint: str | None = None
    evidence_by_lv: dict[str, str] = {}
    for index, (lv_id, entry) in enumerate(zip(adopted, entries)):
        if not isinstance(entry, Mapping):
            raise PrefixAdoptionError("prefix adoption entry is invalid")
        entry_required = {"lv_id", "checkpoint_commit", "checkpoint_parent", "owned_files", "changed_files",
                          "validation_ids", "validation_results", "review_verdict", "evidence_sha256"}
        if set(entry) != entry_required or entry.get("lv_id") != lv_id:
            raise PrefixAdoptionError("prefix adoption entry schema/order mismatch")
        entry_unsigned = {k: v for k, v in entry.items() if k != "evidence_sha256"}
        if entry.get("evidence_sha256") != _digest(entry_unsigned):
            raise PrefixAdoptionError("prefix adoption entry digest mismatch")
        checkpoint = entry.get("checkpoint_commit")
        parent = entry.get("checkpoint_parent")
        if not isinstance(checkpoint, str) or not _SHA40.fullmatch(checkpoint) or not isinstance(parent, str) or not _SHA40.fullmatch(parent):
            raise PrefixAdoptionError("prefix adoption checkpoint is invalid")
        if _git(root, "rev-parse", f"{checkpoint}^") != parent:
            raise PrefixAdoptionError("prefix adoption checkpoint parent mismatch")
        if previous_checkpoint is not None and parent != previous_checkpoint:
            raise PrefixAdoptionError("prefix adoption checkpoints are not contiguous")
        if previous_checkpoint is None:
            if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", approval_head, parent], check=False).returncode != 0:
                raise PrefixAdoptionError("first adopted checkpoint is outside approved ancestry")
            prelude = [p for p in _git(root, "diff", "--name-only", f"{approval_head}..{parent}").splitlines() if p]
            if any(_within(path, adopted_scopes) for path in prelude):
                raise PrefixAdoptionError("pre-adoption governance commits modified adopted scope")
        expected_owned = list(owned_files_by_lv.get(lv_id, ()))
        owned = _paths(entry.get("owned_files"), label="adopted owned scope")
        if owned != expected_owned:
            raise PrefixAdoptionError("prefix adoption owned scope mismatch")
        changed = _paths(entry.get("changed_files"), label="adopted changed files")
        actual_changed = sorted(p for p in _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint).splitlines() if p)
        if sorted(changed) != actual_changed or any(not _within(path, owned) for path in changed):
            raise PrefixAdoptionError("adopted checkpoint changed-file scope mismatch")
        expected_validation_ids = list(validation_ids_by_lv.get(lv_id, ()))
        if entry.get("validation_ids") != expected_validation_ids or not expected_validation_ids:
            raise PrefixAdoptionError("prefix adoption validation ID mismatch")
        _validate_validation_results(entry.get("validation_results"))
        if entry.get("review_verdict") != "PASS":
            raise PrefixAdoptionError("prefix adoption independent review did not pass")
        evidence_by_lv[lv_id] = str(entry["evidence_sha256"])
        previous_checkpoint = checkpoint

    assert previous_checkpoint is not None
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", previous_checkpoint, adoption_head], check=False).returncode != 0:
        raise PrefixAdoptionError("last adopted checkpoint is not an ancestor of adoption head")
    post_prefix = [p for p in _git(root, "diff", "--name-only", f"{previous_checkpoint}..{adoption_head}").splitlines() if p]
    if any(_within(path, adopted_scopes) for path in post_prefix):
        raise PrefixAdoptionError("unadopted changes modified the adopted prefix before adoption seal")
    return {"adopted_lvs": list(adopted), "evidence_by_lv": evidence_by_lv,
            "adoption_head": adoption_head, "record_sha256": evidence["record_sha256"]}

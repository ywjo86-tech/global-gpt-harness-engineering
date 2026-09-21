"""Validation/closure/publication identity proof for Harness releases."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Iterable


EXECUTABLE_SURFACES = ("runtime", "tests", "scripts")
DOCS_ONLY_PREFIXES = ("docs/",)


class PublicationIdentityError(ValueError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        check=False, timeout=30,
    )
    if check and completed.returncode != 0:
        raise PublicationIdentityError("Git publication identity verification failed")
    return completed


def _resolve_commit(repo: Path, value: str, label: str) -> str:
    completed = _git(repo, "rev-parse", f"{value}^{{commit}}")
    head = completed.stdout.strip()
    if not head:
        raise PublicationIdentityError(f"{label} is not a commit")
    return head


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def _changed_paths(repo: Path, start: str, end: str, paths: Iterable[str] = ()) -> tuple[str, ...]:
    args = ["diff", "--name-only", f"{start}..{end}"]
    selected = tuple(paths)
    if selected:
        args.extend(("--", *selected))
    output = _git(repo, *args).stdout
    return tuple(sorted(line.strip() for line in output.splitlines() if line.strip()))


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicationIdentity:
    validated_code_head: str
    closure_head: str
    publication_head: str
    executable_surfaces: tuple[str, ...]
    executable_changed_paths: tuple[str, ...]
    closure_changed_paths: tuple[str, ...]
    executable_diff_sha256: str
    closure_diff_sha256: str
    eligible: bool
    reason: str
    identity_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _result(
    *, validated: str, closure: str, publication: str,
    executable_changed: tuple[str, ...], closure_changed: tuple[str, ...],
    eligible: bool, reason: str,
) -> PublicationIdentity:
    unsigned = {
        "validated_code_head": validated,
        "closure_head": closure,
        "publication_head": publication,
        "executable_surfaces": EXECUTABLE_SURFACES,
        "executable_changed_paths": executable_changed,
        "closure_changed_paths": closure_changed,
        "executable_diff_sha256": _digest(list(executable_changed)),
        "closure_diff_sha256": _digest(list(closure_changed)),
        "eligible": eligible,
        "reason": reason,
    }
    return PublicationIdentity(**unsigned, identity_sha256=_digest(unsigned))


def verify_publication_identity(
    repo: str | Path, validated_code_head: str, closure_head: str, publication_head: str,
) -> PublicationIdentity:
    root = Path(repo).resolve()
    if root.is_symlink() or not root.is_dir():
        raise PublicationIdentityError("publication repository is unsafe")

    validated = _resolve_commit(root, validated_code_head, "validated_code_head")
    closure = _resolve_commit(root, closure_head, "closure_head")
    publication = _resolve_commit(root, publication_head, "publication_head")

    closure_changed = _changed_paths(root, validated, closure)
    executable_changed = _changed_paths(root, validated, publication, EXECUTABLE_SURFACES)

    if not _is_ancestor(root, validated, closure):
        return _result(
            validated=validated, closure=closure, publication=publication,
            executable_changed=executable_changed, closure_changed=closure_changed,
            eligible=False, reason="CLOSURE_NOT_DESCENDANT_OF_VALIDATED_CODE",
        )
    if not _is_ancestor(root, closure, publication):
        return _result(
            validated=validated, closure=closure, publication=publication,
            executable_changed=executable_changed, closure_changed=closure_changed,
            eligible=False, reason="PUBLICATION_NOT_DESCENDANT_OF_CLOSURE",
        )
    if any(not path.startswith(DOCS_ONLY_PREFIXES) for path in closure_changed):
        return _result(
            validated=validated, closure=closure, publication=publication,
            executable_changed=executable_changed, closure_changed=closure_changed,
            eligible=False, reason="CLOSURE_NOT_DOCS_ONLY",
        )
    if executable_changed:
        return _result(
            validated=validated, closure=closure, publication=publication,
            executable_changed=executable_changed, closure_changed=closure_changed,
            eligible=False, reason="EXECUTABLE_SURFACE_DRIFT",
        )
    return _result(
        validated=validated, closure=closure, publication=publication,
        executable_changed=(), closure_changed=closure_changed,
        eligible=True, reason="PUBLICATION_IDENTITY_VERIFIED",
    )

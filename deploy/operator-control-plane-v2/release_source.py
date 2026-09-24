#!/usr/bin/env python3
"""Fail-closed OCPv2 successor release-source authority helpers.

The repository default branch is not an OCP deployment authority.  A successor release
may only be derived from a merged pull request whose base branch matches the canonical
branch declared by ``docs/harness/ocpv2-current-operations.md``.
"""
from __future__ import annotations

import re
from typing import Any, Mapping


_SCHEMA_VERSION = "ocpv2.release-source-authority.v1"
_CANONICAL_BRANCH_RE = re.compile(
    r"^-\s*Canonical branch:\s*`([^`]+)`\s*$",
    re.MULTILINE,
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseSourceError(ValueError):
    """Raised when release-source evidence is missing, ambiguous, or inconsistent."""


def parse_canonical_branch(operations_text: str) -> str:
    """Return the single canonical OCP branch declared by current operations."""
    matches = [match.strip() for match in _CANONICAL_BRANCH_RE.findall(operations_text)]
    if len(matches) != 1 or not matches[0]:
        raise ReleaseSourceError("canonical branch declaration must exist exactly once")
    return matches[0]


def _require_sha40(value: object, *, field: str) -> str:
    candidate = value if isinstance(value, str) else ""
    if not _SHA40_RE.fullmatch(candidate):
        raise ReleaseSourceError(f"{field} must be an exact 40-character lowercase git sha")
    return candidate


def build_release_authority(
    pr_metadata: Mapping[str, Any],
    *,
    operations_text: str,
    tree_sha: str,
) -> dict[str, object]:
    """Build exact immutable release authority from merged-PR and operations evidence."""
    canonical_branch = parse_canonical_branch(operations_text)

    if pr_metadata.get("state") != "MERGED" or not pr_metadata.get("mergedAt"):
        raise ReleaseSourceError("release authority requires a merged pull request")

    base_branch = pr_metadata.get("baseRefName")
    if base_branch != canonical_branch:
        raise ReleaseSourceError(
            "pull request base does not match the declared canonical branch"
        )

    merge_commit = pr_metadata.get("mergeCommit")
    if not isinstance(merge_commit, Mapping):
        raise ReleaseSourceError("merged pull request is missing merge commit evidence")

    merge_sha = _require_sha40(merge_commit.get("oid"), field="merge commit")
    canonical_tree = _require_sha40(tree_sha, field="tree sha")

    pr_number = pr_metadata.get("number")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ReleaseSourceError("pull request number must be a positive integer")

    return {
        "schema_version": _SCHEMA_VERSION,
        "pr_number": pr_number,
        "canonical_branch": canonical_branch,
        "canonical_head": merge_sha,
        "canonical_tree": canonical_tree,
    }

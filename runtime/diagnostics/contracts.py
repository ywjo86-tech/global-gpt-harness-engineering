"""Authority-free contracts for diagnostic code intelligence evidence."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class DiagnosticContractError(ValueError):
    pass


_STATUSES = frozenset({"CURRENT", "STALE", "PARTIAL", "DEGRADED", "CONFLICT", "FAILED"})
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_NAMES = (".env", "secret", "credential", "token", "apikey", "api_key", "private_key")
_EXCLUDED_TOP = frozenset({"_workspace", ".git", ".venv", "venv", "node_modules", "__pycache__"})


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()

def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True,
        text=not binary, check=False, timeout=20,
    )
    if completed.returncode != 0:
        raise DiagnosticContractError("Git source binding verification failed")
    return completed.stdout


def _safe_relative(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or not value or "\\" in value:
        raise DiagnosticContractError("owned path must be safe and relative")
    return candidate.as_posix()


def _secret_name(path: str) -> bool:
    lowered = path.lower()
    return any(part in lowered for part in _SECRET_NAMES)


def _workspace_digest(root: Path) -> str:
    tree = str(_git(root, "rev-parse", "HEAD^{tree}")).strip()
    tracked_diff = _git(root, "diff", "--binary", "HEAD", binary=True)
    digest = hashlib.sha256()
    digest.update(tree.encode("ascii")); digest.update(b"\0"); digest.update(tracked_diff)
    raw = str(_git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    for rel in sorted(x for x in raw.split("\0") if x):
        path = Path(rel)
        if path.parts and path.parts[0] in _EXCLUDED_TOP:
            continue
        full = root / path
        digest.update(rel.encode("utf-8", "surrogateescape")); digest.update(b"\0")
        if _secret_name(rel):
            digest.update(b"<SECRET-CONTENT-REDACTED>")
        elif full.is_file() and not full.is_symlink():
            digest.update(hashlib.sha256(full.read_bytes()).digest())
    return digest.hexdigest()

@dataclass(frozen=True, slots=True)
class SourceSnapshotBinding:
    project_id: str
    source_root_id: str
    git_head_sha: str
    workspace_tree_digest: str
    owned_paths: tuple[str, ...]
    owned_scope_digest: str
    captured_at: str

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise DiagnosticContractError("project_id is required")
        if not _SHA40.fullmatch(self.git_head_sha):
            raise DiagnosticContractError("git_head_sha must be a 40-character Git SHA")
        if not _SHA64.fullmatch(self.workspace_tree_digest):
            raise DiagnosticContractError("workspace_tree_digest must be sha256")
        if not _SHA64.fullmatch(self.owned_scope_digest):
            raise DiagnosticContractError("owned_scope_digest must be sha256")
        for item in self.owned_paths:
            _safe_relative(item)

    @classmethod
    def capture(cls, project_root: str | Path, *, project_id: str,
                owned_paths: Iterable[str] = ()) -> "SourceSnapshotBinding":
        root = Path(project_root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise DiagnosticContractError("project root is unsafe")
        head = str(_git(root, "rev-parse", "HEAD")).strip()
        owned = tuple(sorted({_safe_relative(str(item)) for item in owned_paths}))
        return cls(
            project_id=project_id,
            source_root_id=hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
            git_head_sha=head,
            workspace_tree_digest=_workspace_digest(root),
            owned_paths=owned,
            owned_scope_digest=_digest(owned),
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    kind: str
    query: str
    source_binding: SourceSnapshotBinding
    owned_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.project_id != self.source_binding.project_id:
            raise DiagnosticContractError("analysis request project binding mismatch")
        if not all(str(v).strip() for v in (self.run_id, self.gate_id, self.task_id, self.kind, self.query)):
            raise DiagnosticContractError("analysis request fields are required")
        normalized = tuple(sorted({_safe_relative(str(x)) for x in self.owned_paths}))
        object.__setattr__(self, "owned_paths", normalized)


@dataclass(frozen=True, slots=True)
class AnalysisEvidenceEnvelope:
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    analyzer: str
    analyzer_version: str
    analysis_mode: str
    status: str
    source_binding: SourceSnapshotBinding
    result_digest: str
    raw_evidence_ref: str
    result: Any
    max_result_bytes: int = field(default=262144, repr=False, compare=False)
    control_authority: str = field(default="NONE", init=False)
    mutation_authority: str = field(default="NONE", init=False)
    recovery_authority: str = field(default="NONE", init=False)
    completion_authority: str = field(default="NONE", init=False)
    notification_authority: str = field(default="NONE", init=False)

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise DiagnosticContractError("unsupported diagnostic evidence status")
        if not all(str(v).strip() for v in (
            self.project_id, self.run_id, self.gate_id, self.task_id,
            self.analyzer, self.analyzer_version, self.analysis_mode,
        )):
            raise DiagnosticContractError("diagnostic evidence identity is incomplete")
        if self.project_id != self.source_binding.project_id:
            raise DiagnosticContractError("diagnostic evidence project binding mismatch")
        if not _SHA64.fullmatch(self.result_digest):
            raise DiagnosticContractError("result_digest must be sha256")
        if self.max_result_bytes <= 0:
            raise DiagnosticContractError("max_result_bytes must be positive")
        if len(_canonical_bytes(self.result)) > self.max_result_bytes:
            raise DiagnosticContractError("diagnostic result exceeds configured byte cap")


@dataclass(frozen=True, slots=True)
class DiagnosticContextPack:
    status: str
    source_binding: SourceSnapshotBinding
    evidence_refs: tuple[str, ...] = ()
    candidate_files: tuple[str, ...] = ()
    related_tests: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    advisory_text: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise DiagnosticContractError("unsupported diagnostic context status")
        object.__setattr__(self, "evidence_refs", tuple(sorted(set(self.evidence_refs))))
        object.__setattr__(self, "candidate_files", tuple(sorted(set(self.candidate_files))))
        object.__setattr__(self, "related_tests", tuple(sorted(set(self.related_tests))))
        object.__setattr__(self, "conflicts", tuple(sorted(set(self.conflicts))))

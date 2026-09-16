from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Sequence

from .path_policy import PathPolicyError, WorkspacePathPolicy

MAX_DIFF_BYTES = 1024 * 1024
_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@{}^~:+-]{0,255}\Z")


class GitServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


class GitService:
    def __init__(self, workspace_root: str | Path, path_policy: WorkspacePathPolicy) -> None:
        root = Path(workspace_root)
        if not root.is_absolute() or root.resolve(strict=True) != root or root != path_policy.workspace_root:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git root must equal canonical execution workspace")
        self.root = root; self.path_policy = path_policy
        top = self._run(["rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(top).resolve(strict=True) != self.root:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "repository top differs from execution workspace")

    def _run(self, args: Sequence[str], *, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
        if not args or any(not isinstance(v, str) or not v for v in args):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "git arguments are invalid")
        env = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"}
        try:
            result = subprocess.run(["git", *args], cwd=self.root, text=True, encoding="utf-8", errors="strict",
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, shell=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git command failed to execute safely") from exc
        if result.returncode != 0 and not allow_nonzero:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git command was rejected")
        return result

    def _pathspecs(self, paths: Sequence[str], *, mutable: bool = False) -> list[str]:
        if isinstance(paths, (str, bytes)):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "paths must be a list")
        out: list[str] = []
        for path in paths:
            try:
                if mutable: self.path_policy.resolve_mutable(path)
                else: self.path_policy.resolve_read(path)
            except PathPolicyError as exc:
                raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git path is outside approved scope") from exc
            out.append(path)
        return out

    def _resolve_ref(self, ref: str) -> str:
        if not isinstance(ref, str) or ref.startswith("-") or not _SAFE_REF.fullmatch(ref):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "git ref is invalid")
        result = self._run(["rev-parse", "--verify", f"{ref}^{{commit}}"])
        sha = result.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git ref did not resolve locally")
        return sha

    def _head(self) -> str: return self._resolve_ref("HEAD")

    def branch(self) -> dict[str, object]:
        head = self._head()
        branch = self._run(["symbolic-ref", "--short", "-q", "HEAD"], allow_nonzero=True)
        name = branch.stdout.strip() if branch.returncode == 0 else None
        return {"branch": name or None, "head_sha": head, "detached": name is None}

    def status(self, paths: Sequence[str] = ()) -> dict[str, object]:
        specs = self._pathspecs(paths)
        args = ["status", "--porcelain=v1", "--untracked-files=all"]
        if specs: args += ["--", *specs]
        result = self._run(args)
        entries: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            if len(line) < 3: continue
            xy, body = line[:2], line[3:]
            orig: str | None = None; path = body
            if " -> " in body:
                orig, path = body.split(" -> ", 1)
            entries.append({"xy": xy, "path": path, "orig_path": orig})
        branch = self.branch()
        return {"branch": branch["branch"], "head_sha": branch["head_sha"], "clean": not entries, "entries": entries}

    def diff(self, paths: Sequence[str] = (), *, base_ref: str | None = None, target_ref: str | None = None,
             cached: bool = False, context_lines: int = 3, max_bytes: int = MAX_DIFF_BYTES) -> dict[str, object]:
        specs = self._pathspecs(paths)
        if not isinstance(cached, bool) or not isinstance(context_lines, int) or context_lines < 0 or context_lines > 100:
            raise GitServiceError("INPUT_SCHEMA_INVALID", "diff options are invalid")
        if not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_DIFF_BYTES:
            raise GitServiceError("INPUT_SCHEMA_INVALID", "diff max_bytes is invalid")
        args = ["diff", "--no-ext-diff", "--no-textconv", f"--unified={context_lines}"]
        if cached: args.append("--cached")
        if base_ref is not None and target_ref is not None:
            args += [self._resolve_ref(base_ref), self._resolve_ref(target_ref)]
        elif base_ref is not None:
            args.append(self._resolve_ref(base_ref))
        elif target_ref is not None:
            args += [self._head(), self._resolve_ref(target_ref)]
        if specs: args += ["--", *specs]
        result = self._run(args)
        raw = result.stdout.encode("utf-8")
        if len(raw) > max_bytes:
            raise GitServiceError("OUTPUT_LIMIT_EXCEEDED", "diff exceeds approved bound")
        return {"diff": result.stdout, "diff_sha256": _sha(raw), "bytes": len(raw)}

    def _tree_digest(self) -> str:
        status = self._run(["status", "--porcelain=v1", "-z", "--untracked-files=all"]).stdout.encode()
        diff = self._run(["diff", "--binary", "--no-ext-diff"]).stdout.encode()
        return _sha(status + b"\0" + diff)

    def restore(self, paths: Sequence[str], *, source_ref: str) -> dict[str, object]:
        specs = self._pathspecs(paths, mutable=True)
        if not specs: raise GitServiceError("INPUT_SCHEMA_INVALID", "restore paths must be non-empty")
        source_sha = self._resolve_ref(source_ref); before = self._tree_digest()
        self._run(["restore", f"--source={source_sha}", "--worktree", "--", *specs])
        after = self._tree_digest()
        return {"restored_paths": specs, "source_sha": source_sha, "before_tree_digest": before, "after_tree_digest": after}

    def _index_sha(self) -> str:
        raw_path = self._run(["rev-parse", "--git-path", "index"]).stdout.strip()
        index_path = Path(raw_path) if Path(raw_path).is_absolute() else self.root / raw_path
        try:
            info = os.lstat(index_path)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise GitServiceError("GIT_BOUNDARY_VIOLATION", "git index is unsafe")
            return _sha(index_path.read_bytes())
        except FileNotFoundError:
            return _sha(b"")

    def prepare_commit(self, paths: Sequence[str], *, subject: str) -> dict[str, object]:
        if not isinstance(subject, str) or not 1 <= len(subject) <= 120 or "\n" in subject or "\r" in subject:
            raise GitServiceError("INPUT_SCHEMA_INVALID", "commit subject is invalid")
        specs = self._pathspecs(paths)
        if not specs:
            specs = [entry["path"] for entry in self.status()["entries"] if isinstance(entry.get("path"), str)]
            specs = self._pathspecs(specs)
        before_index = self._index_sha(); head = self._head()
        diff = self.diff(specs)
        if self._index_sha() != before_index or self._head() != head:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "commit preparation mutated repository authority")
        return {"candidate_paths": specs, "diff_sha256": diff["diff_sha256"], "subject": subject,
                "index_sha256_before": before_index, "head_sha": head}

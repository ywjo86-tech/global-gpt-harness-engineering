from __future__ import annotations

import hashlib
import json
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
        result = {"candidate_paths": specs, "diff_sha256": diff["diff_sha256"], "subject": subject,
                  "index_sha256_before": before_index, "head_sha": head}
        try:
            result["publication_preview"] = self.publication_preview(specs)
        except GitServiceError:
            # Existing read-only prepare semantics are preserved for non-publication scopes.
            pass
        return result

    def repository_identity_digest(self) -> str:
        git_dir_raw = self._run(["rev-parse", "--git-dir"]).stdout.strip()
        git_dir = Path(git_dir_raw) if Path(git_dir_raw).is_absolute() else self.root / git_dir_raw
        payload = {"workspace_root": self.root.as_posix(), "git_dir": git_dir.resolve().as_posix()}
        return _sha(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def remote_url_fingerprint(self, remote: str) -> str:
        if not isinstance(remote, str) or remote.startswith("-") or not _SAFE_REF.fullmatch(remote):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "remote name is invalid")
        url = self._run(["remote", "get-url", remote]).stdout.strip()
        if not url:
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "remote URL is missing")
        return _sha(url.encode("utf-8"))

    def _staged_paths(self) -> list[str]:
        raw = self._run(["diff", "--cached", "--name-only", "-z"]).stdout
        return [item for item in raw.split("\0") if item]

    def _staged_diff_digest(self) -> str:
        raw = self._run(["diff", "--cached", "--binary", "--no-ext-diff"]).stdout.encode("utf-8")
        return _sha(raw)

    def publication_staged_paths(self) -> list[str]:
        return list(self._staged_paths())

    def publication_staged_diff_digest(self) -> str:
        return self._staged_diff_digest()

    def publication_index_digest(self) -> str:
        return self._index_sha()

    def publication_preview(self, paths: Sequence[str]) -> dict[str, object]:
        specs = self._pathspecs(paths, mutable=True)
        if not specs:
            raise GitServiceError("INPUT_SCHEMA_INVALID", "publication paths must be non-empty")
        if len(specs) != len(set(specs)):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "publication paths contain duplicates")
        status_raw = self._run(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *specs]).stdout.encode("utf-8")
        changed: set[str] = set()
        for entry in self.status(specs)["entries"]:
            path = entry.get("path")
            if isinstance(path, str): changed.add(path)
        if changed != set(specs):
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "publication path set must exactly match changed paths")
        diff_raw = self._run(["diff", "--binary", "--no-ext-diff", "--", *specs]).stdout.encode("utf-8")
        untracked_parts: list[bytes] = []
        for spec in sorted(specs):
            target = self.root / spec
            tracked = self._run(["ls-files", "--error-unmatch", "--", spec], allow_nonzero=True).returncode == 0
            if not tracked and target.exists():
                try:
                    info = os.lstat(target)
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                        raise GitServiceError("GIT_BOUNDARY_VIOLATION", "untracked publication target is unsafe")
                    untracked_parts.append(spec.encode("utf-8") + b"\0" + target.read_bytes())
                except OSError as exc:
                    raise GitServiceError("GIT_BOUNDARY_VIOLATION", "publication target could not be read safely") from exc
        candidate_material = diff_raw + b"\0" + b"\0".join(untracked_parts)
        worktree_material = status_raw + b"\0" + candidate_material
        return {
            "paths": specs, "head_sha": self._head(),
            "worktree_digest": _sha(worktree_material),
            "candidate_diff_digest": _sha(candidate_material),
            "index_digest": self._index_sha(),
        }

    def stage_publication(self, paths: Sequence[str], *, expected_worktree_digest: str, expected_head: str,
                          candidate_diff_digest: str) -> dict[str, object]:
        specs = self._pathspecs(paths, mutable=True)
        if self._staged_paths():
            raise GitServiceError("GIT_INDEX_NOT_CLEAN", "publication stage requires an empty index delta")
        preview = self.publication_preview(specs)
        if preview["head_sha"] != expected_head:
            raise GitServiceError("GIT_HEAD_DRIFT", "HEAD changed since publication preview")
        if preview["worktree_digest"] != expected_worktree_digest:
            raise GitServiceError("GIT_WORKTREE_DRIFT", "worktree changed since publication preview")
        if preview["candidate_diff_digest"] != candidate_diff_digest:
            raise GitServiceError("GIT_CANDIDATE_DRIFT", "candidate diff changed since publication preview")
        before_index = self._index_sha()
        self._run(["add", "--", *specs])
        staged = self._staged_paths()
        if set(staged) != set(specs):
            self._run(["restore", "--staged", "--", *specs], allow_nonzero=True)
            raise GitServiceError("GIT_BOUNDARY_VIOLATION", "staged path set differs from approved publication scope")
        return {
            "staged_paths": sorted(staged),
            "index_digest_before": before_index,
            "index_digest_after": self._index_sha(),
            "staged_diff_digest": self._staged_diff_digest(),
            "head_sha": self._head(),
        }

    def commit_publication(self, *, expected_staged_diff_digest: str, expected_index_digest: str,
                            expected_head: str, expected_parent: str, subject: str) -> dict[str, object]:
        if not isinstance(subject, str) or not 1 <= len(subject) <= 120 or "\n" in subject or "\r" in subject:
            raise GitServiceError("INPUT_SCHEMA_INVALID", "commit subject is invalid")
        if expected_head != expected_parent or self._head() != expected_head:
            raise GitServiceError("GIT_HEAD_DRIFT", "commit parent/HEAD binding changed")
        if self._index_sha() != expected_index_digest:
            raise GitServiceError("GIT_INDEX_DRIFT", "git index changed since stage evidence")
        staged = self._staged_paths()
        if not staged:
            raise GitServiceError("GIT_INDEX_NOT_CLEAN", "commit requires staged publication content")
        self._pathspecs(staged, mutable=True)
        if self._staged_diff_digest() != expected_staged_diff_digest:
            raise GitServiceError("GIT_INDEX_DRIFT", "staged diff changed since stage evidence")
        self._run(["-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", subject])
        commit_sha = self._head()
        parent_sha = self._run(["rev-parse", f"{commit_sha}^{{commit}}^1"]).stdout.strip()
        if parent_sha != expected_parent:
            raise GitServiceError("ACTION_SIDE_EFFECT_AMBIGUOUS", "created commit parent differs from approved parent")
        tree_sha = self._run(["rev-parse", f"{commit_sha}^{{tree}}"]).stdout.strip()
        committed = self._run(["diff", "--binary", "--no-ext-diff", parent_sha, commit_sha]).stdout.encode("utf-8")
        return {
            "commit_sha": commit_sha, "tree_sha": tree_sha, "parent_sha": parent_sha,
            "committed_diff_digest": _sha(committed), "subject": subject,
        }

    def remote_head(self, remote: str, branch: str) -> str:
        if not isinstance(remote, str) or remote.startswith("-") or not _SAFE_REF.fullmatch(remote):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "remote name is invalid")
        if not isinstance(branch, str) or branch.startswith("-") or not _SAFE_REF.fullmatch(branch):
            raise GitServiceError("INPUT_SCHEMA_INVALID", "branch name is invalid")
        result = self._run(["ls-remote", "--exit-code", remote, f"refs/heads/{branch}"], allow_nonzero=True)
        if result.returncode != 0:
            raise GitServiceError("GIT_REMOTE_HEAD_UNAVAILABLE", "approved remote branch head is unavailable")
        fields = result.stdout.strip().split()
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{40,64}", fields[0]):
            raise GitServiceError("GIT_REMOTE_HEAD_UNAVAILABLE", "remote head response is invalid")
        return fields[0]

    def push_publication(self, *, remote: str, branch: str, local_commit_sha: str, expected_remote_head: str) -> dict[str, object]:
        current = self.branch()
        if current["detached"] or current["branch"] != branch:
            raise GitServiceError("GIT_BRANCH_MISMATCH", "current branch differs from approved branch")
        if self._head() != local_commit_sha or self._resolve_ref(branch) != local_commit_sha:
            raise GitServiceError("GIT_HEAD_DRIFT", "local branch tip differs from approved commit")
        pre_remote = self.remote_head(remote, branch)
        if pre_remote != expected_remote_head:
            raise GitServiceError("GIT_REMOTE_STALE", "remote head differs from approved freshness binding")
        try:
            self._resolve_ref(expected_remote_head)
        except GitServiceError as exc:
            raise GitServiceError("GIT_NON_FAST_FORWARD", "expected remote head is not locally provable") from exc
        ff = self._run(["merge-base", "--is-ancestor", expected_remote_head, local_commit_sha], allow_nonzero=True)
        if ff.returncode != 0:
            raise GitServiceError("GIT_NON_FAST_FORWARD", "approved push is not fast-forward")
        refspec = f"{local_commit_sha}:refs/heads/{branch}"
        pushed = self._run(["push", "--porcelain", "--no-verify", remote, refspec], allow_nonzero=True)
        try:
            post_remote = self.remote_head(remote, branch)
        except GitServiceError as exc:
            raise GitServiceError("ACTION_SIDE_EFFECT_AMBIGUOUS", "remote state cannot be reconciled after push") from exc
        if post_remote == local_commit_sha:
            return {
                "remote": remote, "branch": branch, "pre_remote_head": pre_remote,
                "post_remote_head": post_remote, "local_commit_sha": local_commit_sha,
                "push_status": "CONFIRMED", "reconciliation_state": "CONFIRMED",
            }
        if pushed.returncode != 0 and post_remote == pre_remote:
            raise GitServiceError("GIT_PUSH_REJECTED", "push failed and remote is unchanged")
        raise GitServiceError("ACTION_SIDE_EFFECT_AMBIGUOUS", "push outcome is ambiguous after reconciliation")

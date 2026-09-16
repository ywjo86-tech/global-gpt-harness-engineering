from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

from .path_policy import PathPolicyError, WorkspacePathPolicy

MAX_FILE_BYTES = 1024 * 1024


class FilesystemServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_file(path: Path) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise FilesystemServiceError("PATH_POLICY_VIOLATION", "target cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode):
        raise FilesystemServiceError("SYMLINK_VIOLATION", "symlink target is forbidden")
    if not stat.S_ISREG(info.st_mode):
        raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "target must be a regular file")
    return info


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


class FilesystemService:
    def __init__(self, policy: WorkspacePathPolicy) -> None:
        self.policy = policy

    def read(self, path: str, *, encoding: str = "utf-8", max_bytes: int = MAX_FILE_BYTES) -> dict[str, object]:
        if encoding != "utf-8" or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_FILE_BYTES:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid read arguments")
        try:
            target = self.policy.resolve_read(path)
        except PathPolicyError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "read path rejected") from exc
        info = _regular_file(target)
        if info.st_size > max_bytes:
            raise FilesystemServiceError("OUTPUT_LIMIT_EXCEEDED", "file exceeds max_bytes")
        try:
            raw = target.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "file is not valid UTF-8") from exc
        return {"path": path, "size": len(raw), "sha256": _sha256_bytes(raw), "encoding": "utf-8", "text": text}

    def write(self, path: str, content: str, *, expected_absent: bool = False,
              expected_sha256: str | None = None) -> dict[str, object]:
        if not isinstance(content, str) or not isinstance(expected_absent, bool):
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid write arguments")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "expected_sha256 is invalid")
        if expected_absent and expected_sha256 is not None:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "write preconditions conflict")
        try:
            target = self.policy.resolve_mutable(path)
        except PathPolicyError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "write path rejected") from exc
        parent = target.parent
        try:
            pinfo = os.lstat(parent)
        except OSError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "write parent must already exist") from exc
        if stat.S_ISLNK(pinfo.st_mode) or not stat.S_ISDIR(pinfo.st_mode):
            raise FilesystemServiceError("SYMLINK_VIOLATION", "unsafe write parent")
        before_sha: str | None = None
        if target.exists() or target.is_symlink():
            _regular_file(target)
            before_sha = _sha256_bytes(target.read_bytes())
            if expected_absent:
                raise FilesystemServiceError("PATCH_CONFLICT", "target was expected to be absent")
            if expected_sha256 is None:
                raise FilesystemServiceError("PATCH_CONFLICT", "replacement requires expected_sha256")
            if before_sha != expected_sha256:
                raise FilesystemServiceError("PATCH_CONFLICT", "replacement precondition failed")
        elif expected_sha256 is not None:
            raise FilesystemServiceError("PATCH_CONFLICT", "expected replacement target is absent")
        raw = content.encode("utf-8")
        descriptor, temp_name = tempfile.mkstemp(prefix=".full-mcp-write-", dir=parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, target)
            directory = os.open(parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if temp.exists(): temp.unlink()
        return {"path": path, "before_sha256": before_sha, "after_sha256": _sha256_bytes(raw), "bytes_written": len(raw)}

    def patch(self, path: str, *, base_sha256: str, edits: Sequence[Mapping[str, object]],
              final_newline: bool | None = None) -> dict[str, object]:
        if not isinstance(base_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", base_sha256):
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "base_sha256 is invalid")
        if isinstance(edits, (str, bytes)) or not edits or final_newline not in (True, False, None):
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "patch arguments are invalid")
        try:
            target = self.policy.resolve_mutable(path)
        except PathPolicyError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "patch path rejected") from exc
        _regular_file(target)
        raw = target.read_bytes()
        if _sha256_bytes(raw) != base_sha256:
            raise FilesystemServiceError("PATCH_CONFLICT", "patch base hash is stale")
        try:
            original = raw.decode("utf-8")
        except UnicodeError as exc:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "patch target is not UTF-8") from exc
        lines = original.splitlines()
        parsed: list[tuple[int, int, str]] = []
        last_end = 0
        for edit in edits:
            if not isinstance(edit, Mapping) or set(edit) != {"start_line", "end_line", "replacement"}:
                raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid LineEdit")
            start, end, replacement = edit["start_line"], edit["end_line"], edit["replacement"]
            if not isinstance(start, int) or not isinstance(end, int) or not isinstance(replacement, str) or start < 1 or end < start:
                raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid LineEdit range")
            if start <= last_end or end > len(lines):
                raise FilesystemServiceError("PATCH_CONFLICT", "LineEdits overlap or exceed target")
            parsed.append((start, end, replacement)); last_end = end
        out: list[str] = []
        cursor = 1
        for start, end, replacement in parsed:
            out.extend(lines[cursor-1:start-1])
            out.extend(replacement.splitlines())
            cursor = end + 1
        out.extend(lines[cursor-1:])
        keep_final = original.endswith("\n") if final_newline is None else final_newline
        updated = "\n".join(out) + ("\n" if keep_final else "")
        result = self.write(path, updated, expected_sha256=base_sha256)
        result["changed_line_count"] = sum(end - start + 1 for start, end, _ in parsed)
        result.pop("bytes_written"); result.pop("path")
        return {"path": path, "before_sha256": base_sha256, "after_sha256": result["after_sha256"],
                "changed_line_count": result["changed_line_count"]}

    def search(self, *, root: str = ".", query: str, mode: str = "LITERAL", glob: str = "**/*",
               max_matches: int = 200, max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, object]:
        if not isinstance(query, str) or not query or mode not in {"LITERAL", "REGEX"}:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid search query")
        if not isinstance(glob, str) or not glob or not isinstance(max_matches, int) or not 1 <= max_matches <= 200:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid search bounds")
        if not isinstance(max_file_bytes, int) or not 1 <= max_file_bytes <= MAX_FILE_BYTES:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "invalid search file bound")
        try:
            base = self.policy.resolve_read(root)
        except PathPolicyError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "search root rejected") from exc
        if not base.is_dir() or base.is_symlink():
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "search root must be a directory")
        try:
            regex = re.compile(query) if mode == "REGEX" else None
        except re.error as exc:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "search regex is invalid") from exc
        matches: list[dict[str, object]] = []
        for candidate in sorted(base.glob(glob)):
            if len(matches) >= max_matches: break
            rel = _relative(self.policy.workspace_root, candidate)
            try:
                safe = self.policy.resolve_read(rel)
                info = os.lstat(safe)
            except (PathPolicyError, OSError):
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > max_file_bytes:
                continue
            try: text = safe.read_text(encoding="utf-8")
            except (OSError, UnicodeError): continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if mode == "LITERAL":
                    positions = [] if query not in line else [line.index(query)]
                else:
                    positions = [m.start() for m in regex.finditer(line)] if regex is not None else []
                for column in positions:
                    matches.append({"path": rel, "line": line_no, "column": column + 1, "text": line})
                    if len(matches) >= max_matches: break
                if len(matches) >= max_matches: break
        return {"matches": matches, "match_count": len(matches)}

    def metadata(self, path: str, *, include_sha256: bool = True) -> dict[str, object]:
        if not isinstance(include_sha256, bool):
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "include_sha256 must be boolean")
        try:
            target = self.policy.resolve_read(path)
            info = os.lstat(target)
        except PathPolicyError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "metadata path rejected") from exc
        except OSError as exc:
            raise FilesystemServiceError("PATH_POLICY_VIOLATION", "metadata target unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise FilesystemServiceError("SYMLINK_VIOLATION", "symlink metadata is forbidden")
        if stat.S_ISREG(info.st_mode):
            kind = "REGULAR_FILE"
            digest = _sha256_bytes(target.read_bytes()) if include_sha256 else None
        elif stat.S_ISDIR(info.st_mode):
            kind, digest = "DIRECTORY", None
        else:
            raise FilesystemServiceError("INPUT_SCHEMA_INVALID", "unsupported metadata target kind")
        return {"path": path, "kind": kind, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                "mode_octal": format(stat.S_IMODE(info.st_mode), "04o"), "sha256": digest, "symlink": False}

"""Read-only client for the independently hosted AI Office Owner anchor."""
from __future__ import annotations

import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "orchestration.ai-office-owner-audit-anchor-request.v1"
RESPONSE_SCHEMA = "orchestration.ai-office-owner-audit-anchor-response.v1"
GLOBAL_SCHEMA = "orchestration.ai-office-owner-authority-anchor.v1"
PROJECT_SCHEMA = "orchestration.project-owner-binding-anchor.v2"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REQUEST_BYTES = 2048
_MAX_RESPONSE_BYTES = 4096


class OwnerAuditAnchorError(ValueError):
    """The independent Owner anchor could not be read or validated."""


class OwnerAuditAnchorClient:
    """Read the current global Owner and project Owner-binding heads over UDS.

    This client intentionally has no write operation. A failed or malformed
    response is an authorization failure for callers that require Owner proof.
    """

    def __init__(self, socket_path: str | Path, *, timeout_seconds: float = 2.5) -> None:
        path = Path(socket_path)
        parent_stat = path.parent.stat() if path.parent.exists() else None
        socket_stat = path.lstat() if path.exists() or path.is_symlink() else None
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.parent.is_dir()
            or path.parent.is_symlink()
            or path.parent.resolve(strict=True) != path.parent
            or parent_stat is None
            or parent_stat.st_mode & 0o022
            or parent_stat.st_uid == os.geteuid()
            or socket_stat is None
            or not stat.S_ISSOCK(socket_stat.st_mode)
            or socket_stat.st_mode & 0o007
            or socket_stat.st_uid == os.geteuid()
            or socket_stat.st_uid != parent_stat.st_uid
            or len(str(path).encode()) >= 104
        ):
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_SOCKET_UNSAFE")
        if not (0.1 <= float(timeout_seconds) <= 10):
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_TIMEOUT_INVALID")
        self.socket_path = path
        self.timeout_seconds = float(timeout_seconds)

    @staticmethod
    def _validate_identifier(value: object) -> str:
        text = str(value or "")
        if not _IDENTIFIER.fullmatch(text) or ".." in text:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_PROJECT_INVALID")
        return text

    def _query(self, operation: str, *, project_id: str | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {"schema_version": REQUEST_SCHEMA, "operation": operation}
        if operation == "READ_PROJECT_OWNER_BINDING_HEAD":
            request["project_id"] = self._validate_identifier(project_id)
        elif operation != "READ_GLOBAL_OWNER_HEAD":
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_OPERATION_INVALID")
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > _MAX_REQUEST_BYTES:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_REQUEST_TOO_LARGE")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self.timeout_seconds)
        try:
            client.connect(str(self.socket_path))
            client.sendall(encoded)
            client.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = client.recv(min(1024, _MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_RESPONSE_TOO_LARGE")
                chunks.append(chunk)
        except (OSError, TimeoutError) as exc:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_UNAVAILABLE") from exc
        finally:
            client.close()
        raw = b"".join(chunks)
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_RESPONSE_INVALID")
        try:
            response = json.loads(raw[:-1].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_RESPONSE_INVALID") from exc
        if (
            not isinstance(response, dict)
            or set(response) != {"schema_version", "status", "anchor"}
            or response.get("schema_version") != RESPONSE_SCHEMA
            or response.get("status") != "OK"
            or not isinstance(response.get("anchor"), dict)
        ):
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_UNAVAILABLE")
        anchor = response["anchor"]
        if operation == "READ_GLOBAL_OWNER_HEAD":
            if (
                set(anchor) != {"schema_version", "generation", "change_id", "event_sha256"}
                or anchor.get("schema_version") != GLOBAL_SCHEMA
            ):
                raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_GLOBAL_HEAD_INVALID")
        else:
            if (
                set(anchor) != {"schema_version", "project_id", "generation", "change_id", "event_sha256"}
                or anchor.get("schema_version") != PROJECT_SCHEMA
                or anchor.get("project_id") != project_id
            ):
                raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_PROJECT_HEAD_INVALID")
        if (
            type(anchor.get("generation")) is not int
            or anchor["generation"] < 1
            or not _IDENTIFIER.fullmatch(str(anchor.get("change_id") or ""))
            or not _SHA256.fullmatch(str(anchor.get("event_sha256") or ""))
        ):
            raise OwnerAuditAnchorError("OWNER_AUDIT_ANCHOR_HEAD_INVALID")
        return dict(anchor)

    def read_owner_authority(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Return validated read-only heads, or raise if either head is unavailable."""
        project_id = self._validate_identifier(project_id)
        global_head = self._query("READ_GLOBAL_OWNER_HEAD")
        project_head = self._query("READ_PROJECT_OWNER_BINDING_HEAD", project_id=project_id)
        return {
            "global_owner_head": global_head,
            "project_owner_binding_head": project_head,
        }

"""Private GitHub PR-comment transport for OCPv2 control envelopes.

The adapter only converts verified comments to transport-neutral raw envelopes and
publishes bounded result projections. It owns no canonical execution state. A bounded
durable delivery-ack ledger suppresses only an exact control-comment fingerprint after
a result projection was successfully published; edited comments are delivered again.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from runtime.orchestrator.remote_operator_transport import RawControlEnvelope

from .github_rest_client import (
    PUBLIC_SOURCE_REPOSITORY_ID,
    GitHubRESTClient,
    GitHubRESTClientError,
)


CONTROL_PREFIX = "OCPV2_CONTROL_V2\n"
RESULT_PREFIX = "OCPV2_RESULT_V1\n"
_DELIVERY_ACK_SCHEMA = "ocpv2.github-delivery-ack.v1"
_DELIVERY_PENDING_SCHEMA = "ocpv2.github-delivery-pending.v1"


class GitHubControlAdapterError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubControlConfig:
    allowed_repository_id: int
    control_pr_number: int
    allowed_actor_ids: frozenset[str]
    api_base: str = "https://api.github.com"
    max_comment_bytes: int = 65536
    poll_limit: int = 16
    delivery_ack_limit: int = 1024

    def __post_init__(self) -> None:
        if isinstance(self.allowed_repository_id, bool) or self.allowed_repository_id <= 0:
            raise GitHubControlAdapterError("allowed repository ID must be positive")
        if self.allowed_repository_id == PUBLIC_SOURCE_REPOSITORY_ID:
            raise GitHubControlAdapterError("public source repository cannot be used as control transport")
        if isinstance(self.control_pr_number, bool) or self.control_pr_number <= 0:
            raise GitHubControlAdapterError("control PR number must be positive")
        if not self.allowed_actor_ids or any(not str(item) for item in self.allowed_actor_ids):
            raise GitHubControlAdapterError("actor allowlist must not be empty")
        if isinstance(self.max_comment_bytes, bool) or self.max_comment_bytes <= 0:
            raise GitHubControlAdapterError("max comment bytes must be positive")
        if isinstance(self.poll_limit, bool) or self.poll_limit <= 0:
            raise GitHubControlAdapterError("poll limit must be positive")
        if isinstance(self.delivery_ack_limit, bool) or self.delivery_ack_limit <= 0:
            raise GitHubControlAdapterError("delivery ack limit must be positive")
        if not str(self.api_base).startswith("https://"):
            raise GitHubControlAdapterError("API base must use https")


@dataclass(frozen=True, slots=True)
class _PendingDelivery:
    source_message_id: str
    message_id: str
    content_sha256: str


class GitHubControlAdapter:
    def __init__(
        self,
        *,
        config: GitHubControlConfig,
        rest_client: GitHubRESTClient,
        secret_scan: Callable[[bytes], Mapping[str, int]],
        delivery_ack_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.rest_client = rest_client
        self.secret_scan = secret_scan
        configured_ack_path: str | Path | None = delivery_ack_path
        if configured_ack_path is None:
            state_root = str(os.environ.get("OCP_STATE_ROOT") or "").strip()
            if state_root:
                configured_ack_path = Path(state_root) / "transport" / "github-delivery-acks.json"
        self.delivery_ack_path = None if configured_ack_path is None else Path(configured_ack_path).absolute()
        self.delivery_pending_path = (
            None
            if self.delivery_ack_path is None
            else self.delivery_ack_path.with_name(self.delivery_ack_path.name + ".pending")
        )
        for path in (self.delivery_ack_path, self.delivery_pending_path):
            if path is not None and path.is_symlink():
                raise GitHubControlAdapterError("delivery state path must not be a symlink")
        self._acknowledged: set[str] = set()
        self._pending: dict[str, list[_PendingDelivery]] = {}
        for pending in self._load_delivery_pending():
            self._pending.setdefault(pending.message_id, []).append(pending)

    def _verified_repository_id(self) -> int:
        if getattr(self.rest_client, "repository_id", None) != self.config.allowed_repository_id:
            raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: repository client binding mismatch")
        if getattr(self.rest_client, "control_pr_number", None) != self.config.control_pr_number:
            raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: PR channel binding mismatch")
        try:
            repository = self.rest_client.verify_repository()
        except GitHubRESTClientError as exc:
            raise GitHubControlAdapterError(f"SOURCE_NOT_ALLOWED: {exc}") from exc
        if repository.repository_id != self.config.allowed_repository_id or repository.private is not True:
            raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: verified repository mismatch")
        return repository.repository_id

    @staticmethod
    def _canonical_object_bytes(value: Mapping[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _content_sha256(canonical: bytes) -> str:
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _validate_delivery_entry(entry: object, *, label: str) -> dict[str, str]:
        if not isinstance(entry, Mapping) or set(entry) != {
            "source_message_id",
            "message_id",
            "content_sha256",
        }:
            raise GitHubControlAdapterError(f"{label} entry is invalid")
        source_message_id = str(entry.get("source_message_id") or "")
        message_id = str(entry.get("message_id") or "")
        content_sha256 = str(entry.get("content_sha256") or "")
        if (
            not source_message_id
            or not message_id
            or len(content_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in content_sha256)
        ):
            raise GitHubControlAdapterError(f"{label} entry is invalid")
        return {
            "source_message_id": source_message_id,
            "message_id": message_id,
            "content_sha256": content_sha256,
        }

    @staticmethod
    def _save_delivery_state(path: Path, schema_version: str, entries: list[dict[str, str]]) -> None:
        parent = path.parent
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise GitHubControlAdapterError("delivery state root is unsafe")
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or path.is_symlink():
            raise GitHubControlAdapterError("delivery state is unsafe")
        payload = {"schema_version": schema_version, "entries": entries}
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise GitHubControlAdapterError("delivery state write failed") from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load_delivery_acks(self) -> list[dict[str, str]]:
        path = self.delivery_ack_path
        if path is None or not path.exists():
            return []
        if path.is_symlink() or not path.is_file():
            raise GitHubControlAdapterError("delivery ack state is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GitHubControlAdapterError("delivery ack state is invalid") from exc
        if not isinstance(value, Mapping) or value.get("schema_version") != _DELIVERY_ACK_SCHEMA:
            raise GitHubControlAdapterError("delivery ack schema mismatch")
        entries = value.get("entries")
        if not isinstance(entries, list):
            raise GitHubControlAdapterError("delivery ack entries are invalid")
        result = [self._validate_delivery_entry(entry, label="delivery ack") for entry in entries]
        if len(result) > self.config.delivery_ack_limit:
            raise GitHubControlAdapterError("delivery ack state exceeds configured limit")
        return result

    def _save_delivery_acks(self, entries: list[dict[str, str]]) -> None:
        path = self.delivery_ack_path
        if path is None:
            return
        bounded = entries[-self.config.delivery_ack_limit:]
        self._save_delivery_state(path, _DELIVERY_ACK_SCHEMA, bounded)

    def _load_delivery_pending(self) -> list[_PendingDelivery]:
        path = self.delivery_pending_path
        if path is None or not path.exists():
            return []
        if path.is_symlink() or not path.is_file():
            raise GitHubControlAdapterError("delivery pending state is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GitHubControlAdapterError("delivery pending state is invalid") from exc
        if not isinstance(value, Mapping) or value.get("schema_version") != _DELIVERY_PENDING_SCHEMA:
            raise GitHubControlAdapterError("delivery pending schema mismatch")
        entries = value.get("entries")
        if not isinstance(entries, list):
            raise GitHubControlAdapterError("delivery pending entries are invalid")
        parsed = [self._validate_delivery_entry(entry, label="delivery pending") for entry in entries]
        if len(parsed) > self.config.delivery_ack_limit:
            raise GitHubControlAdapterError("delivery pending state exceeds configured limit")
        return [_PendingDelivery(**entry) for entry in parsed]

    def _save_delivery_pending(self) -> None:
        path = self.delivery_pending_path
        if path is None:
            return
        entries: list[dict[str, str]] = []
        for queue in self._pending.values():
            for pending in queue:
                entries.append({
                    "source_message_id": pending.source_message_id,
                    "message_id": pending.message_id,
                    "content_sha256": pending.content_sha256,
                })
        if not entries:
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise GitHubControlAdapterError("delivery pending state is unsafe")
                try:
                    path.unlink()
                except OSError as exc:
                    raise GitHubControlAdapterError("delivery pending cleanup failed") from exc
            return
        bounded = entries[-self.config.delivery_ack_limit:]
        self._save_delivery_state(path, _DELIVERY_PENDING_SCHEMA, bounded)

    def _is_durably_acknowledged(self, source_message_id: str, content_sha256: str) -> bool:
        return any(
            entry["source_message_id"] == source_message_id
            and entry["content_sha256"] == content_sha256
            for entry in self._load_delivery_acks()
        )

    def has_durable_ack(
        self,
        message_id: str,
        *,
        source_message_id: str = "",
        content_sha256: str = "",
    ) -> bool:
        """Read only durable result-ack state; canonical completion is not inferred here."""
        message = str(message_id or "")
        source = str(source_message_id or "")
        digest = str(content_sha256 or "")
        if not message:
            return False
        if bool(source) != bool(digest):
            raise GitHubControlAdapterError("durable ack exact binding must be paired")
        for entry in self._load_delivery_acks():
            if entry["message_id"] != message:
                continue
            if source and (
                entry["source_message_id"] != source
                or entry["content_sha256"] != digest
            ):
                continue
            return True
        return False

    def prepare_recovery_delivery(
        self,
        *,
        source_message_id: str,
        message_id: str,
        content_sha256: str,
    ) -> None:
        """Re-arm exact transport ack bookkeeping for an outbox recovery publish.

        The caller must derive these values from a previously durable execution binding.
        This method grants no execution authority; it only lets `publish_projection()`
        persist the same exact delivery fingerprint that normal receive/publish uses.
        """
        source = str(source_message_id or "")
        message = str(message_id or "")
        digest = str(content_sha256 or "")
        if not source or not message:
            raise GitHubControlAdapterError("recovery delivery identity is required")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise GitHubControlAdapterError("recovery delivery content digest is invalid")
        pending = _PendingDelivery(source_message_id=source, message_id=message, content_sha256=digest)
        queue = self._pending.setdefault(message, [])
        if pending not in queue:
            queue.append(pending)
            self._save_delivery_pending()

    def _remember_pending(self, *, source_message_id: str, parsed: Mapping[str, Any], canonical: bytes) -> None:
        message_id = parsed.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            return
        pending = _PendingDelivery(
            source_message_id=source_message_id,
            message_id=message_id,
            content_sha256=self._content_sha256(canonical),
        )
        queue = self._pending.setdefault(message_id, [])
        if pending not in queue:
            queue.append(pending)
            self._save_delivery_pending()

    def _discard_pending(self, pending: _PendingDelivery) -> None:
        queue = self._pending.get(pending.message_id, [])
        remaining = [item for item in queue if item != pending]
        if remaining:
            self._pending[pending.message_id] = remaining
        else:
            self._pending.pop(pending.message_id, None)
        self._save_delivery_pending()

    def _persist_successful_publish(self, message_id: object) -> None:
        value = str(message_id or "")
        queue = self._pending.get(value)
        if not value or not queue:
            return
        pending = queue[0]
        entries = self._load_delivery_acks()
        entries = [entry for entry in entries if entry["source_message_id"] != pending.source_message_id]
        entries.append({
            "source_message_id": pending.source_message_id,
            "message_id": pending.message_id,
            "content_sha256": pending.content_sha256,
        })
        # Commit the exact durable ACK before removing the pending fingerprint. If the
        # process dies after this write, the next process suppresses duplicate publish
        # and only finishes pending-ledger cleanup.
        self._save_delivery_acks(entries)
        self._discard_pending(pending)

    def _receive_controls(
        self,
        *,
        limit: int = 16,
        request_kind: str | None = None,
    ) -> tuple[RawControlEnvelope, ...]:
        repository_id = self._verified_repository_id()
        bounded_limit = min(int(limit), self.config.poll_limit)
        if bounded_limit <= 0:
            return ()
        try:
            comments = self.rest_client.list_comments()
        except GitHubRESTClientError as exc:
            raise GitHubControlAdapterError(f"SOURCE_NOT_ALLOWED: {exc}") from exc

        result: list[RawControlEnvelope] = []
        first_rejection: GitHubControlAdapterError | None = None
        for comment in comments:
            body = comment.get("body")
            if not isinstance(body, str):
                continue
            if body.startswith(RESULT_PREFIX):
                continue
            if not body.startswith(CONTROL_PREFIX):
                continue
            if len(body.encode("utf-8")) > self.config.max_comment_bytes:
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError(
                        "SOURCE_NOT_ALLOWED: control comment exceeds byte limit"
                    )
                continue

            user = comment.get("user")
            actor_id = str(user.get("id")) if isinstance(user, Mapping) and user.get("id") is not None else ""
            if actor_id not in self.config.allowed_actor_ids:
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError("ACTOR_NOT_ALLOWED")
                continue
            comment_id = comment.get("id")
            if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError("SOURCE_NOT_ALLOWED: comment identity invalid")
                continue
            source_message_id = str(comment_id)
            created_at = comment.get("created_at")
            if not isinstance(created_at, str) or not created_at:
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError("SOURCE_NOT_ALLOWED: comment timestamp missing")
                continue

            raw_payload = body[len(CONTROL_PREFIX):]
            try:
                parsed = json.loads(raw_payload)
            except Exception:
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError("SOURCE_NOT_ALLOWED: control payload is not JSON")
                continue
            if not isinstance(parsed, Mapping):
                if first_rejection is None:
                    first_rejection = GitHubControlAdapterError("SOURCE_NOT_ALLOWED: control payload must be an object")
                continue
            if (
                request_kind is not None
                and str(parsed.get("request_kind") or "") != request_kind
            ):
                continue
            canonical = self._canonical_object_bytes(parsed)
            fingerprint = self._content_sha256(canonical)
            if self._is_durably_acknowledged(source_message_id, fingerprint):
                for pending in tuple(self._pending.get(str(parsed.get("message_id") or ""), [])):
                    if (
                        pending.source_message_id == source_message_id
                        and pending.content_sha256 == fingerprint
                    ):
                        self._discard_pending(pending)
                continue
            # Persist the exact transport fingerprint before exposing the raw control to
            # the service. A later outbox recovery can therefore publish and ACK without
            # re-running the inspection/activation side effect after process restart.
            self._remember_pending(source_message_id=source_message_id, parsed=parsed, canonical=canonical)
            result.append(
                RawControlEnvelope(
                    source_repository_id=repository_id,
                    source_channel_id=f"PR:{self.config.control_pr_number}",
                    source_actor_id=actor_id,
                    source_message_id=source_message_id,
                    content=canonical,
                    received_at=created_at,
                )
            )
            if len(result) >= bounded_limit:
                break
        if result:
            return tuple(result)
        if first_rejection is not None:
            raise first_rejection
        return ()


    def receive(self, *, limit: int = 16) -> tuple[RawControlEnvelope, ...]:
        return self._receive_controls(limit=limit)

    def receive_request_kind(
        self,
        request_kind: str,
        *,
        limit: int = 16,
    ) -> tuple[RawControlEnvelope, ...]:
        kind = str(request_kind or "").strip()
        if not kind:
            raise GitHubControlAdapterError("request kind is required")
        return self._receive_controls(limit=limit, request_kind=kind)

    def acknowledge_delivery(self, message_id: str) -> None:
        value = str(message_id or "")
        if not value:
            raise GitHubControlAdapterError("message ID is required")
        self._acknowledged.add(value)

    def publish_projection(self, projection: Mapping[str, Any]) -> None:
        if not isinstance(projection, Mapping):
            raise GitHubControlAdapterError("projection must be an object")
        canonical = self._canonical_object_bytes(projection)
        findings = self.secret_scan(canonical)
        if findings:
            raise GitHubControlAdapterError("SECRET_LIKE_PROJECTION")
        body_bytes = RESULT_PREFIX.encode("utf-8") + canonical
        if len(body_bytes) > self.config.max_comment_bytes:
            raise GitHubControlAdapterError("projection exceeds configured byte limit")
        self._verified_repository_id()

        message_id = str(projection.get("message_id") or "")
        queue = self._pending.get(message_id, [])
        if queue:
            pending = queue[0]
            if self.has_durable_ack(
                pending.message_id,
                source_message_id=pending.source_message_id,
                content_sha256=pending.content_sha256,
            ):
                # A previous process committed the durable ACK but died before pending
                # cleanup. Do not republish remotely; just complete local reconciliation.
                self._discard_pending(pending)
                return

        try:
            self.rest_client.publish_comment(body_bytes.decode("utf-8"))
        except GitHubRESTClientError as exc:
            raise GitHubControlAdapterError(f"projection publish failed: {exc}") from exc
        self._persist_successful_publish(message_id)

"""Private GitHub PR-comment transport for OCPv2 control envelopes.

The adapter only converts verified comments to transport-neutral raw envelopes and
publishes bounded result projections.  It owns no canonical execution state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from runtime.orchestrator.remote_operator_transport import RawControlEnvelope

from .github_rest_client import (
    PUBLIC_SOURCE_REPOSITORY_ID,
    GitHubRESTClient,
    GitHubRESTClientError,
)


CONTROL_PREFIX = "OCPV2_CONTROL_V2\n"
RESULT_PREFIX = "OCPV2_RESULT_V1\n"


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
        if not str(self.api_base).startswith("https://"):
            raise GitHubControlAdapterError("API base must use https")


class GitHubControlAdapter:
    def __init__(
        self,
        *,
        config: GitHubControlConfig,
        rest_client: GitHubRESTClient,
        secret_scan: Callable[[bytes], Mapping[str, int]],
    ) -> None:
        self.config = config
        self.rest_client = rest_client
        self.secret_scan = secret_scan
        self._acknowledged: set[str] = set()

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

    def receive(self, *, limit: int = 16) -> tuple[RawControlEnvelope, ...]:
        repository_id = self._verified_repository_id()
        bounded_limit = min(int(limit), self.config.poll_limit)
        if bounded_limit <= 0:
            return ()
        try:
            comments = self.rest_client.list_comments()
        except GitHubRESTClientError as exc:
            raise GitHubControlAdapterError(f"SOURCE_NOT_ALLOWED: {exc}") from exc

        result: list[RawControlEnvelope] = []
        for comment in comments:
            body = comment.get("body")
            if not isinstance(body, str):
                continue
            if body.startswith(RESULT_PREFIX):
                continue
            if not body.startswith(CONTROL_PREFIX):
                continue
            if len(body.encode("utf-8")) > self.config.max_comment_bytes:
                raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: control comment exceeds byte limit")

            user = comment.get("user")
            actor_id = str(user.get("id")) if isinstance(user, Mapping) and user.get("id") is not None else ""
            if actor_id not in self.config.allowed_actor_ids:
                raise GitHubControlAdapterError("ACTOR_NOT_ALLOWED")
            comment_id = comment.get("id")
            if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
                raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: comment identity invalid")
            created_at = comment.get("created_at")
            if not isinstance(created_at, str) or not created_at:
                raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: comment timestamp missing")

            raw_payload = body[len(CONTROL_PREFIX):]
            try:
                parsed = json.loads(raw_payload)
            except Exception as exc:
                raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: control payload is not JSON") from exc
            if not isinstance(parsed, Mapping):
                raise GitHubControlAdapterError("SOURCE_NOT_ALLOWED: control payload must be an object")
            result.append(
                RawControlEnvelope(
                    source_repository_id=repository_id,
                    source_channel_id=f"PR:{self.config.control_pr_number}",
                    source_actor_id=actor_id,
                    source_message_id=str(comment_id),
                    content=self._canonical_object_bytes(parsed),
                    received_at=created_at,
                )
            )
            if len(result) >= bounded_limit:
                break
        return tuple(result)

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
        try:
            self.rest_client.publish_comment(body_bytes.decode("utf-8"))
        except GitHubRESTClientError as exc:
            raise GitHubControlAdapterError(f"projection publish failed: {exc}") from exc

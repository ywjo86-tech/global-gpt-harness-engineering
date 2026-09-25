"""Governed P2 successor release staging contracts.

This module starts with the immutable request identity used by DRY_RUN/STAGE.
Mutation behavior is added only by later TDD tasks.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

SUCCESSOR_RELEASE_STAGE_SCHEMA = "orchestration.successor-release-stage-request.v1"
SUCCESSOR_PROFILE = "lifecycle-v2-p2"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_REF = re.compile(r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_FIELDS = {
    "request_id",
    "schema_version",
    "project_alias",
    "expected_branch",
    "expected_head",
    "target_ref",
    "target_head",
    "successor_profile",
    "approval_policy_ref",
    "approval_policy_digest",
    "mode",
    "preflight_digest",
}


class SuccessorReleaseStageError(ValueError):
    """Fail-closed validation or staging error."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text) or ".." in text:
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _sha1(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA1.fullmatch(text):
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise SuccessorReleaseStageError(f"invalid {label}")
    return text


def _target_ref(value: object) -> str:
    text = str(value or "")
    if (
        not _TARGET_REF.fullmatch(text)
        or ".." in text
        or "//" in text
        or text.endswith(("/", "."))
    ):
        raise SuccessorReleaseStageError("invalid target ref")
    return text


@dataclass(frozen=True, slots=True)
class SuccessorReleaseStageRequest:
    request_id: str
    schema_version: str
    project_alias: str
    expected_branch: str
    expected_head: str
    target_ref: str
    target_head: str
    successor_profile: str
    approval_policy_ref: str
    approval_policy_digest: str
    mode: str
    preflight_digest: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SuccessorReleaseStageRequest":
        if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
            raise SuccessorReleaseStageError("successor stage request fields mismatch")
        if raw.get("schema_version") != SUCCESSOR_RELEASE_STAGE_SCHEMA:
            raise SuccessorReleaseStageError("unsupported successor stage request schema")

        mode = str(raw.get("mode") or "")
        if mode not in {"DRY_RUN", "STAGE"}:
            raise SuccessorReleaseStageError("invalid successor stage mode")

        profile = str(raw.get("successor_profile") or "")
        if profile != SUCCESSOR_PROFILE:
            raise SuccessorReleaseStageError("unsupported successor profile")

        preflight_raw = raw.get("preflight_digest")
        if mode == "DRY_RUN":
            if preflight_raw is not None:
                raise SuccessorReleaseStageError("DRY_RUN preflight digest must be absent")
            preflight_digest = None
        else:
            preflight_digest = _sha256(preflight_raw, "preflight digest")

        return cls(
            request_id=_safe_id(raw.get("request_id"), "request ID"),
            schema_version=SUCCESSOR_RELEASE_STAGE_SCHEMA,
            project_alias=_safe_id(raw.get("project_alias"), "project alias"),
            expected_branch=_safe_id(raw.get("expected_branch"), "expected branch"),
            expected_head=_sha1(raw.get("expected_head"), "expected head"),
            target_ref=_target_ref(raw.get("target_ref")),
            target_head=_sha1(raw.get("target_head"), "target head"),
            successor_profile=SUCCESSOR_PROFILE,
            approval_policy_ref=_safe_id(raw.get("approval_policy_ref"), "approval policy ref"),
            approval_policy_digest=_sha256(
                raw.get("approval_policy_digest"), "approval policy digest"
            ),
            mode=mode,
            preflight_digest=preflight_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "project_alias": self.project_alias,
            "expected_branch": self.expected_branch,
            "expected_head": self.expected_head,
            "target_ref": self.target_ref,
            "target_head": self.target_head,
            "successor_profile": self.successor_profile,
            "approval_policy_ref": self.approval_policy_ref,
            "approval_policy_digest": self.approval_policy_digest,
            "mode": self.mode,
            "preflight_digest": self.preflight_digest,
        }

    def intent_mapping(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("mode")
        value.pop("preflight_digest")
        return value

    @property
    def stage_intent_digest(self) -> str:
        return hashlib.sha256(_canonical(self.intent_mapping())).hexdigest()

    @property
    def phase_request_digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

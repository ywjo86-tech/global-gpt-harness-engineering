"""Immutable provider-stage handoff contract for PREPARE -> ACTION -> VERIFY lineage."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

HANDOFF_SCHEMA = "orchestration.provider-handoff.v1"
VALID_STAGES = frozenset({"PREPARE", "ACTION", "VERIFY", "REVIEW"})


class ProviderHandoffError(ValueError):
    pass


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderHandoffPackageV1:
    schema_version: str
    parent_execution_id: str
    stage: str
    provider_decision_digest: str
    input_artifact_digests: tuple[str, ...]
    output_artifact_digests: tuple[str, ...]
    proposed_change_manifest: tuple[str, ...]
    required_next_capabilities: tuple[str, ...]
    state_change_required: bool
    status: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != HANDOFF_SCHEMA:
            raise ProviderHandoffError("unsupported handoff schema")
        if not self.parent_execution_id or self.stage not in VALID_STAGES:
            raise ProviderHandoffError("handoff identity/stage is invalid")
        if len(self.provider_decision_digest) != 64:
            raise ProviderHandoffError("provider decision digest is invalid")
        if self.stage == "PREPARE" and self.status == "completed" and self.state_change_required:
            if not self.output_artifact_digests:
                raise ProviderHandoffError("prepared state-changing work requires output artifact lineage")

    def unsigned_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def handoff_digest(self) -> str:
        return _digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "handoff_digest": self.handoff_digest}

    @property
    def may_request_action(self) -> bool:
        return self.stage == "PREPARE" and self.status == "completed" and self.state_change_required and not self.errors


def build_provider_handoff(*, parent_execution_id: str, stage: str, provider_decision_digest: str,
                           input_artifact_digests: Sequence[str] = (), output_artifact_digests: Sequence[str] = (),
                           proposed_change_manifest: Sequence[str] = (), required_next_capabilities: Sequence[str] = (),
                           state_change_required: bool = False, status: str,
                           warnings: Sequence[str] = (), errors: Sequence[str] = ()) -> ProviderHandoffPackageV1:
    return ProviderHandoffPackageV1(
        schema_version=HANDOFF_SCHEMA, parent_execution_id=parent_execution_id, stage=stage,
        provider_decision_digest=provider_decision_digest,
        input_artifact_digests=tuple(input_artifact_digests), output_artifact_digests=tuple(output_artifact_digests),
        proposed_change_manifest=tuple(proposed_change_manifest),
        required_next_capabilities=tuple(sorted({str(x) for x in required_next_capabilities if str(x)})),
        state_change_required=state_change_required, status=status,
        warnings=tuple(warnings), errors=tuple(errors),
    )

"""Digest-bound publication evidence projections; canonical effect truth remains ToolEffectJournal."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contracts import canonical_sha256


@dataclass(frozen=True, slots=True)
class PublicationEvidence:
    schema_version: str
    operation: str
    policy_digest: str
    payload: dict[str, Any]

    @property
    def evidence_digest(self) -> str:
        return canonical_sha256(self.unsigned())

    def unsigned(self) -> dict[str, Any]:
        return asdict(self)

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned(), "evidence_digest": self.evidence_digest}


def seal_publication_evidence(operation: str, policy_digest: str, payload: dict[str, Any]) -> dict[str, Any]:
    return PublicationEvidence(
        schema_version="gch.full-mcp.publication-evidence.v1",
        operation=operation,
        policy_digest=policy_digest,
        payload=dict(payload),
    ).to_dict()

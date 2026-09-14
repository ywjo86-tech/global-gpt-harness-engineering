from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

_SHA40 = re.compile(r"^[0-9a-f]{40}$")

CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES = (
    "repository_structure",
    "symbol_lookup",
    "dependency_reference",
    "path_neighbor",
    "change_impact",
    "freshness_confidence",
    "investigation_support",
)


@dataclass(frozen=True)
class ProviderQueryRequest:
    scenario_id: str
    query: str
    source_ref: str
    token_budget: int = 1000

    def validate(self) -> None:
        if not self.scenario_id.strip() or not self.query.strip():
            raise ValueError("scenario_id and query are required")
        if not _SHA40.fullmatch(self.source_ref):
            raise ValueError("source_ref must be a 40-char lowercase git SHA")
        if self.token_budget < 100 or self.token_budget > 10000:
            raise ValueError("token_budget outside approved range")


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    scenario_id: str
    source_ref: str
    status: str
    output: str
    source_files: tuple[str, ...] = ()
    write_performed: bool = False
    freshness_state: str = "CURRENT"
    confidence: str = "EXTRACTED"
    error: str = ""

    def validate(self) -> None:
        if self.provider_id not in {"graphify", "existing_inspection"}:
            raise ValueError("unapproved provider_id")
        if self.write_performed:
            raise ValueError("repository intelligence provider performed a write")
        if not _SHA40.fullmatch(self.source_ref):
            raise ValueError("invalid source_ref")
        if self.freshness_state not in {"CURRENT", "STALE", "UNKNOWN"}:
            raise ValueError("invalid freshness_state")
        if self.confidence not in {"EXTRACTED", "CANONICAL", "PARTIAL", "UNKNOWN"}:
            raise ValueError("invalid confidence")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_files"] = list(self.source_files)
        return payload


def normalize_source_files(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value and not value.startswith("/")}))

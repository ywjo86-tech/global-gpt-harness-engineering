from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .contracts import canonical_digest
from .requirement_intake import RequirementEnvelopeV1

CONTEXT_ASSEMBLY_SCHEMA_V1 = "ai-office.context-assembly.v1"
SOURCE_PRECEDENCE_VERSION_V1 = "ai-office.source-precedence.v1"
PRECEDENCE = {
    "USER_DECISION": 0,
    "APPROVED_PLAN": 1,
    "VERIFIED_REPOSITORY": 2,
    "VERIFIED_STATE": 3,
    "TECHNICAL_ASSUMPTION": 4,
}


class ContextAssemblyError(ValueError):
    pass


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise ContextAssemblyError(f"invalid {label}")
    return value.strip()
def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ContextAssemblyError(f"invalid {label}")
    return text


@dataclass(frozen=True, slots=True)
class ContextSourceRefV1:
    binding_key: str
    authority_tier: str
    source_ref: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_key", _text(self.binding_key, "binding_key"))
        if self.authority_tier not in PRECEDENCE:
            raise ContextAssemblyError("unknown source authority tier")
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_digest", _sha256(self.source_digest, "source_digest"))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextAssemblyV1:
    schema_version: str
    source_precedence_version: str
    requirement_digests: tuple[str, ...]
    context_items: tuple[ContextSourceRefV1, ...]
    def __post_init__(self) -> None:
        if self.schema_version != CONTEXT_ASSEMBLY_SCHEMA_V1:
            raise ContextAssemblyError("unsupported context assembly schema")
        if self.source_precedence_version != SOURCE_PRECEDENCE_VERSION_V1:
            raise ContextAssemblyError("unsupported source precedence version")
        reqs = tuple(_sha256(item, "requirement_digest") for item in self.requirement_digests)
        if len(reqs) != len(set(reqs)):
            raise ContextAssemblyError("duplicate requirement digest")
        object.__setattr__(self, "requirement_digests", reqs)
        keys = [item.binding_key for item in self.context_items]
        if len(keys) != len(set(keys)):
            raise ContextAssemblyError("duplicate context binding key")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_precedence_version": self.source_precedence_version,
            "requirement_digests": list(self.requirement_digests),
            "context_items": [item.to_dict() for item in self.context_items],
        }

    @property
    def context_digest(self) -> str:
        return canonical_digest(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "context_digest": self.context_digest}
def assemble_context(
    requirements: Iterable[RequirementEnvelopeV1],
    sources: Iterable[ContextSourceRefV1],
) -> ContextAssemblyV1:
    requirement_list = sorted(requirements, key=lambda item: (item.requirement_id, item.envelope_digest))
    if not requirement_list:
        raise ContextAssemblyError("at least one approved requirement is required")
    by_key: dict[str, ContextSourceRefV1] = {}
    for item in sources:
        if not isinstance(item, ContextSourceRefV1):
            raise ContextAssemblyError("context source must be a validated reference")
        current = by_key.get(item.binding_key)
        if current is None:
            by_key[item.binding_key] = item
            continue
        old_rank = PRECEDENCE[current.authority_tier]
        new_rank = PRECEDENCE[item.authority_tier]
        if old_rank == new_rank and current.source_digest != item.source_digest:
            raise ContextAssemblyError("SOURCE_BINDING_BLOCKED: conflicting same-precedence source")
        if new_rank < old_rank:
            by_key[item.binding_key] = item
    selected = tuple(sorted(
        by_key.values(),
        key=lambda item: (PRECEDENCE[item.authority_tier], item.binding_key, item.source_ref, item.source_digest),
    ))
    if not selected:
        raise ContextAssemblyError("context requires at least one verified source")
    return ContextAssemblyV1(
        CONTEXT_ASSEMBLY_SCHEMA_V1,
        SOURCE_PRECEDENCE_VERSION_V1,
        tuple(item.envelope_digest for item in requirement_list),
        selected,
    )

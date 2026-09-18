from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from .contracts import canonical_digest

PROJECT_DEFINITION_SCHEMA_V1 = "ai-office.project-definition.v1"
OPERATING_CONTRACT_SCHEMA_V1 = "ai-office.operating-contract.v1"
SCAFFOLD_INTENT_SCHEMA_V1 = "ai-office.scaffold-intent.v1"
LIFECYCLE_TRANSITIONS = {
    "DRAFT": "GOVERNED",
    "GOVERNED": "SCAFFOLD_PENDING",
    "SCAFFOLD_PENDING": "SCAFFOLD_VERIFIED",
    "SCAFFOLD_VERIFIED": "PILOT",
    "PILOT": "PRODUCTION",
}


class FoundryError(ValueError):
    pass


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1024:
        raise FoundryError(f"invalid {label}")
    return value.strip()


def _sha(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise FoundryError(f"invalid {label}")
    return text
def _target_within_scope(target_root: str, approved_root: str) -> str:
    target = PurePosixPath(_text(target_root, "target_root"))
    approved = PurePosixPath(_text(approved_root, "approved_root"))
    if not target.is_absolute() or not approved.is_absolute():
        raise FoundryError("project roots must be absolute")
    if target != approved and approved not in target.parents:
        raise FoundryError("target root is outside approved Foundry scope")
    return str(target)


@dataclass(frozen=True, slots=True)
class OfficeProjectDefinitionV1:
    schema_version: str
    project_id: str
    office_id: str
    target_root: str
    approved_root: str
    requirement_ref: str
    context_ref: str
    template_ref: str
    template_digest: str
    operating_policy_refs: tuple[str, ...]
    lifecycle_state: str = "DRAFT"

    def __post_init__(self) -> None:
        if self.schema_version != PROJECT_DEFINITION_SCHEMA_V1:
            raise FoundryError("unsupported project definition schema")
        for field in ("project_id", "office_id", "requirement_ref", "context_ref", "template_ref"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "target_root", _target_within_scope(self.target_root, self.approved_root))
        object.__setattr__(self, "approved_root", str(PurePosixPath(self.approved_root)))
        object.__setattr__(self, "template_digest", _sha(self.template_digest, "template_digest"))
        object.__setattr__(self, "operating_policy_refs", tuple(_text(x, "operating_policy_ref") for x in self.operating_policy_refs))
        if self.lifecycle_state != "DRAFT":
            raise FoundryError("new project definition must start DRAFT")
    @property
    def definition_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class OfficeOperatingContractV1:
    schema_version: str
    project_definition_digest: str
    governance_decision_ref: str
    allowed_scaffold_scope: tuple[str, ...]
    lifecycle_state: str

    def __post_init__(self) -> None:
        if self.schema_version != OPERATING_CONTRACT_SCHEMA_V1:
            raise FoundryError("unsupported operating contract schema")
        object.__setattr__(self, "project_definition_digest", _sha(self.project_definition_digest, "project_definition_digest"))
        object.__setattr__(self, "governance_decision_ref", _text(self.governance_decision_ref, "governance_decision_ref"))
        scope = tuple(sorted({_text(path, "scaffold_scope") for path in self.allowed_scaffold_scope}))
        if not scope:
            raise FoundryError("scaffold scope is required")
        object.__setattr__(self, "allowed_scaffold_scope", scope)
        if self.lifecycle_state != "GOVERNED":
            raise FoundryError("operating contract requires GOVERNED lifecycle")

    @property
    def contract_digest(self) -> str:
        return canonical_digest(asdict(self))
@dataclass(frozen=True, slots=True)
class ScaffoldIntentV1:
    schema_version: str
    operating_contract_digest: str
    intended_paths: tuple[str, ...]
    expected_changes: tuple[str, ...]
    validation_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCAFFOLD_INTENT_SCHEMA_V1:
            raise FoundryError("unsupported scaffold intent schema")
        object.__setattr__(self, "operating_contract_digest", _sha(self.operating_contract_digest, "operating_contract_digest"))
        paths = tuple(sorted({_text(path, "intended_path") for path in self.intended_paths}))
        if not paths:
            raise FoundryError("intended paths are required")
        object.__setattr__(self, "intended_paths", paths)
        changes = tuple(_text(item, "expected_change") for item in self.expected_changes)
        refs = tuple(_text(item, "validation_ref") for item in self.validation_refs)
        if not changes or not refs:
            raise FoundryError("scaffold changes and validation refs are required")
        object.__setattr__(self, "expected_changes", changes)
        object.__setattr__(self, "validation_refs", refs)

    @property
    def intent_digest(self) -> str:
        return canonical_digest(asdict(self))


def advance_lifecycle(current_state: str, next_state: str) -> str:
    if LIFECYCLE_TRANSITIONS.get(current_state) != next_state:
        raise FoundryError("undeclared Foundry lifecycle transition")
    return next_state
def create_operating_contract(
    definition: OfficeProjectDefinitionV1, *, governance_decision_ref: str,
    allowed_scaffold_scope: tuple[str, ...],
) -> OfficeOperatingContractV1:
    advance_lifecycle(definition.lifecycle_state, "GOVERNED")
    return OfficeOperatingContractV1(
        OPERATING_CONTRACT_SCHEMA_V1,
        definition.definition_digest,
        governance_decision_ref,
        allowed_scaffold_scope,
        "GOVERNED",
    )


def create_scaffold_intent(
    contract: OfficeOperatingContractV1, *, intended_paths: tuple[str, ...],
    expected_changes: tuple[str, ...], validation_refs: tuple[str, ...],
) -> ScaffoldIntentV1:
    allowed = tuple(PurePosixPath(path) for path in contract.allowed_scaffold_scope)
    for raw in intended_paths:
        path = PurePosixPath(_text(raw, "intended_path"))
        if path.is_absolute() or ".." in path.parts:
            raise FoundryError("scaffold path escapes declarative scope")
        if not any(path == root or root in path.parents for root in allowed):
            raise FoundryError("scaffold path outside operating contract scope")
    return ScaffoldIntentV1(
        SCAFFOLD_INTENT_SCHEMA_V1,
        contract.contract_digest,
        intended_paths,
        expected_changes,
        validation_refs,
    )

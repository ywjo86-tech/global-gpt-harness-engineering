from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleProjectionV1:
    contract_id: str
    contract_version: str
    endpoint_version: str
    activation_epoch: int
    state: str
    health: str
    active_dependency_count: int
    replacement_contract_id: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def project_capability_lifecycle(
    record: object,
) -> CapabilityLifecycleProjectionV1:
    """Create a bounded read-only lifecycle projection."""

    contract = getattr(record, "contract", None)

    if contract is None:
        raise ValueError(
            "capability lifecycle record contract is missing"
        )

    contract_id = getattr(
        contract,
        "contract_id",
        "",
    )
    contract_version = getattr(
        contract,
        "contract_version",
        "",
    )
    endpoint_version = getattr(
        contract,
        "endpoint_version",
        "",
    )
    activation_epoch = getattr(
        contract,
        "activation_epoch",
        0,
    )

    state = getattr(record, "state", "")
    health = getattr(record, "health", "")
    dependency_count = getattr(
        record,
        "active_dependency_count",
        None,
    )

    if (
        not isinstance(contract_id, str)
        or not contract_id
        or not isinstance(contract_version, str)
        or not contract_version
        or not isinstance(endpoint_version, str)
        or not isinstance(activation_epoch, int)
        or activation_epoch < 0
        or not isinstance(state, str)
        or not state
        or not isinstance(health, str)
        or not health
        or not isinstance(dependency_count, int)
        or dependency_count < 0
    ):
        raise ValueError(
            "capability lifecycle projection source is malformed"
        )

    replacement_contract_id = getattr(
        record,
        "replacement_contract_id",
        "",
    )

    if replacement_contract_id is None:
        replacement_contract_id = ""

    if not isinstance(replacement_contract_id, str):
        raise ValueError(
            "replacement capability identity is malformed"
        )

    evidence_refs = getattr(
        record,
        "evidence_refs",
        (),
    )

    if (
        not isinstance(evidence_refs, tuple)
        or any(
            not isinstance(item, str) or not item
            for item in evidence_refs
        )
    ):
        raise ValueError(
            "capability lifecycle evidence references are malformed"
        )

    return CapabilityLifecycleProjectionV1(
        contract_id=contract_id,
        contract_version=contract_version,
        endpoint_version=endpoint_version,
        activation_epoch=activation_epoch,
        state=state,
        health=health,
        active_dependency_count=dependency_count,
        replacement_contract_id=replacement_contract_id,
        evidence_refs=evidence_refs,
    )

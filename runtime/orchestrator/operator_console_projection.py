"""Non-authoritative read/control contract for the future Harness Operator Console.

The console may project authorization-filtered canonical state and may normalize a
control request into the existing OCPv2 remote envelope.  It owns no Full Plan,
execution-gateway, Full MCP, migration, or completion authority.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

from .remote_operator_envelope import RemoteOperatorEnvelopeV2, validate_remote_envelope


CONSOLE_PROJECTION_SCHEMA = "orchestration.operator-console-projection.v1"
_SAFE_ATOM = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SAFE_REF = re.compile(r"[A-Za-z0-9._:/-]{1,256}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class OperatorConsoleProjectionError(ValueError):
    pass


def _atom(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SAFE_ATOM.fullmatch(text) or ".." in text:
        raise OperatorConsoleProjectionError(f"invalid {label}")
    return text


def _digest(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if not _SHA256.fullmatch(text):
        raise OperatorConsoleProjectionError(f"invalid {label}")
    return text


def _refs(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise OperatorConsoleProjectionError(f"invalid {label}")
    result: list[str] = []
    for item in value:
        text = str(item or "")
        if not _SAFE_REF.fullmatch(text) or ".." in text:
            raise OperatorConsoleProjectionError(f"invalid {label}")
        result.append(text)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class OperatorConsoleProjectionV1:
    project_id: str
    run_id: str
    task_id: str
    gate_id: str
    stage: str
    execution_readiness: str
    operator_authority_label: str
    transport_state: str
    checkpoint_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    migration_phase: str
    migration_transaction_sha256: str
    status_flags: tuple[str, ...]
    schema_version: str = CONSOLE_PROJECTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["checkpoint_refs"] = list(self.checkpoint_refs)
        value["evidence_refs"] = list(self.evidence_refs)
        value["status_flags"] = list(self.status_flags)
        return value


def build_operator_console_projection(
    canonical_read_model: Mapping[str, Any],
    *,
    transport_state: str,
    status_flags: tuple[str, ...] | list[str],
) -> OperatorConsoleProjectionV1:
    """Project only a closed, value-bounded read model for the console.

    Unknown input fields are intentionally ignored.  This keeps provider/model,
    credentials, authorizations, raw effect payloads, and other restricted values out
    of the console contract instead of turning the projection into another authority.
    """
    if not isinstance(canonical_read_model, Mapping):
        raise OperatorConsoleProjectionError("canonical read model must be a mapping")
    flags = tuple(_atom(item, "status flag") for item in status_flags)
    return OperatorConsoleProjectionV1(
        project_id=_atom(canonical_read_model.get("project_id"), "project ID"),
        run_id=_atom(canonical_read_model.get("run_id"), "run ID"),
        task_id=_atom(canonical_read_model.get("task_id"), "task ID", allow_empty=True),
        gate_id=_atom(canonical_read_model.get("gate_id"), "gate ID"),
        stage=_atom(canonical_read_model.get("stage"), "stage"),
        execution_readiness=_atom(
            canonical_read_model.get("execution_readiness", "UNKNOWN"),
            "execution readiness",
        ),
        operator_authority_label=_atom(
            canonical_read_model.get("operator_authority_label", "GPT_OPERATOR"),
            "operator authority label",
        ),
        transport_state=_atom(transport_state, "transport state"),
        checkpoint_refs=_refs(canonical_read_model.get("checkpoint_refs", ()), "checkpoint refs"),
        evidence_refs=_refs(canonical_read_model.get("evidence_refs", ()), "evidence refs"),
        migration_phase=_atom(
            canonical_read_model.get("migration_phase", ""),
            "migration phase",
            allow_empty=True,
        ),
        migration_transaction_sha256=_digest(
            canonical_read_model.get("migration_transaction_sha256", ""),
            "migration transaction digest",
            allow_empty=True,
        ),
        status_flags=flags,
    )


def normalize_console_control_request(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> RemoteOperatorEnvelopeV2:
    """Enter console control intent through the existing OCPv2 envelope validator.

    No console-specific execution shortcut exists: callers must pass the returned
    envelope through the normal ingress/receipt/authorization/CAS path.
    """
    return validate_remote_envelope(payload, now=now)

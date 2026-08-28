from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from .lv_execution_package import canonical_json_bytes


class CompletenessError(ValueError):
    pass


REQUIREMENT_IDS = tuple(f"R{number:02d}" for number in range(1, 26))
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_STATUSES = {"PENDING", "IMPLEMENTED", "VERIFIED", "CHECKPOINTED", "EXITED", "BLOCKED"}
_ROW_FIELDS = {
    "item_id", "item_kind", "gate_id", "lv_id", "order", "owned_files", "selected_assets",
    "excluded_assets", "selection_rationale", "tests", "evidence_sha256", "status",
    "checkpoint_ref", "exit_ref", "handoff_ref",
}
_HANDOFF_FIELDS = {
    "schema_version", "project_id", "gate_id", "lv_id", "run_id", "requirements_sha256",
    "plan_sha256", "branch", "head", "completed_items", "remaining_items", "owned_files",
    "changed_files", "tests", "review", "artifact_sha256", "checkpoint_ref", "exit_ref",
    "ledger_sha256", "known_issues", "deferred_items", "next_condition", "permissions",
    "forbidden_actions", "selected_assets", "excluded_assets", "selection_rationale",
}


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_ledger(*, project_id: str, requirements_sha256: str, plan_sha256: str,
                 plan_items: Sequence[Mapping[str, object]], requirements: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    if set(requirements) != set(REQUIREMENT_IDS):
        raise CompletenessError("R01-R25 completeness mismatch")
    rows: list[dict[str, object]] = []
    for item in plan_items:
        rows.append(_row(item, "PLAN_ITEM", len(rows) + 1))
    for requirement_id in REQUIREMENT_IDS:
        value = dict(requirements[requirement_id]); value["item_id"] = requirement_id
        rows.append(_row(value, "REQUIREMENT", len(rows) + 1))
    payload = {
        "schema_version": "orchestration.completeness-ledger.v1", "project_id": project_id,
        "requirements_sha256": requirements_sha256, "plan_sha256": plan_sha256, "items": rows,
    }
    validate_ledger(payload, plan_items=plan_items, requirements=requirements)
    return {"payload": payload, "ledger_sha256": _hash(payload)}


def _row(source: Mapping[str, object], kind: str, order: int) -> dict[str, object]:
    defaults = {
        "item_id": "", "gate_id": "", "lv_id": "", "owned_files": [], "selected_assets": [],
        "excluded_assets": [], "selection_rationale": "", "tests": [], "evidence_sha256": "",
        "status": "PENDING", "checkpoint_ref": "", "exit_ref": "", "handoff_ref": "",
    }
    defaults.update(source)
    defaults["item_kind"] = kind; defaults["order"] = order
    if set(defaults) != _ROW_FIELDS:
        raise CompletenessError("ledger item schema mismatch")
    return defaults


def validate_ledger(payload: Mapping[str, object], *, plan_items: Sequence[Mapping[str, object]],
                    requirements: Mapping[str, Mapping[str, object]] | None = None,
                    requirements_sha256: str | None = None, plan_sha256: str | None = None,
                    require_exit: bool = False) -> None:
    if set(payload) != {"schema_version", "project_id", "requirements_sha256", "plan_sha256", "items"} or payload.get("schema_version") != "orchestration.completeness-ledger.v1":
        raise CompletenessError("ledger schema mismatch")
    if requirements_sha256 is not None and payload.get("requirements_sha256") != requirements_sha256:
        raise CompletenessError("requirements SHA drift")
    if plan_sha256 is not None and payload.get("plan_sha256") != plan_sha256:
        raise CompletenessError("plan SHA drift")
    if not _SHA.fullmatch(str(payload.get("requirements_sha256", ""))) or not _SHA.fullmatch(str(payload.get("plan_sha256", ""))):
        raise CompletenessError("ledger SHA binding is invalid")
    items = payload.get("items")
    if not isinstance(items, list) or any(not isinstance(row, dict) or set(row) != _ROW_FIELDS for row in items):
        raise CompletenessError("ledger item schema mismatch")
    expected_plan = [str(item["item_id"]) for item in plan_items]
    expected = expected_plan + list(REQUIREMENT_IDS)
    actual = [row["item_id"] for row in items]
    if actual != expected or len(set(actual)) != len(expected):
        raise CompletenessError("ledger missing, duplicate, unlinked, or out-of-order item")
    for index, row in enumerate(items, 1):
        kind = "PLAN_ITEM" if index <= len(expected_plan) else "REQUIREMENT"
        if row["order"] != index or row["item_kind"] != kind or not row["gate_id"] or not row["lv_id"]:
            raise CompletenessError("ledger order or Gate/LV linkage mismatch")
        if row["status"] not in _STATUSES:
            raise CompletenessError("invalid ledger status")
        if not isinstance(row["owned_files"], list) or not isinstance(row["tests"], list):
            raise CompletenessError("invalid ledger files/tests")
        if not isinstance(row["selected_assets"], list) or not isinstance(row["excluded_assets"], list) or not row["selection_rationale"]:
            raise CompletenessError("Skill/Agent selection evidence is incomplete")
        if row["status"] in {"VERIFIED", "CHECKPOINTED", "EXITED"} and not _SHA.fullmatch(str(row["evidence_sha256"])):
            raise CompletenessError("verified item lacks evidence SHA")
        if row["status"] in {"CHECKPOINTED", "EXITED"} and not row["checkpoint_ref"]:
            raise CompletenessError("checkpoint reference is missing")
        if row["status"] == "EXITED" and (not row["exit_ref"] or not row["handoff_ref"]):
            raise CompletenessError("Exit or handoff reference is missing")
        source: Mapping[str, object] | None
        if index <= len(plan_items):
            source = plan_items[index - 1]
        elif requirements is not None:
            source = requirements[str(row["item_id"])]
        else:
            source = None
        if source is not None:
            for field in ("gate_id", "lv_id", "owned_files", "selected_assets", "excluded_assets", "selection_rationale", "tests"):
                if row[field] != source.get(field):
                    raise CompletenessError(f"ledger canonical {field} linkage mismatch")
    if require_exit and any(row["status"] != "EXITED" for row in items):
        raise CompletenessError("ledger is not fully exited")


def save_ledger(path: str | Path, envelope: Mapping[str, object]) -> None:
    target = Path(path)
    if target.exists():
        raise CompletenessError("immutable ledger already exists")
    if set(envelope) != {"payload", "ledger_sha256"} or envelope.get("ledger_sha256") != _hash(envelope.get("payload")):
        raise CompletenessError("ledger envelope hash mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(envelope)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream: stream.write(data)
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def load_ledger(path: str | Path) -> dict[str, object]:
    source = Path(path)
    if not source.is_file() or source.is_symlink(): raise CompletenessError("ledger is missing or unsafe")
    try: envelope = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc: raise CompletenessError("ledger is malformed") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "ledger_sha256"} or envelope.get("ledger_sha256") != _hash(envelope.get("payload")):
        raise CompletenessError("ledger envelope hash mismatch")
    return envelope


def seal_handoff(payload: Mapping[str, object]) -> dict[str, object]:
    value = dict(payload)
    if set(value) != _HANDOFF_FIELDS or value.get("schema_version") != "orchestration.structured-handoff.v1":
        raise CompletenessError("handoff required fields mismatch")
    return {"payload": value, "handoff_sha256": _hash(value)}


def validate_handoff(envelope: Mapping[str, object], *, ledger_envelope: Mapping[str, object],
                     project_id: str, gate_id: str, lv_id: str, run_id: str,
                     requirements_sha256: str, plan_sha256: str, branch: str, head: str,
                     artifact_sha256: str, checkpoint_ref: str, exit_ref: str) -> None:
    if set(envelope) != {"payload", "handoff_sha256"} or not isinstance(envelope.get("payload"), dict):
        raise CompletenessError("handoff envelope mismatch")
    handoff = envelope["payload"]
    assert isinstance(handoff, dict)
    if set(handoff) != _HANDOFF_FIELDS or envelope.get("handoff_sha256") != _hash(handoff):
        raise CompletenessError("handoff field or hash mismatch")
    expected = {"project_id": project_id, "gate_id": gate_id, "lv_id": lv_id, "run_id": run_id,
                "requirements_sha256": requirements_sha256, "plan_sha256": plan_sha256,
                "branch": branch, "head": head, "artifact_sha256": artifact_sha256,
                "checkpoint_ref": checkpoint_ref, "exit_ref": exit_ref,
                "ledger_sha256": ledger_envelope.get("ledger_sha256")}
    for key, value in expected.items():
        if handoff.get(key) != value: raise CompletenessError(f"handoff {key} consistency mismatch")
    if not _SHA.fullmatch(artifact_sha256) or not _HEAD.fullmatch(head): raise CompletenessError("handoff artifact/HEAD binding invalid")
    ledger = ledger_envelope.get("payload")
    if not isinstance(ledger, dict) or ledger_envelope.get("ledger_sha256") != _hash(ledger): raise CompletenessError("handoff ledger drift")
    rows = ledger.get("items")
    if not isinstance(rows, list): raise CompletenessError("handoff ledger items missing")
    ids = [row.get("item_id") for row in rows if isinstance(row, dict)]
    completed, remaining = handoff.get("completed_items"), handoff.get("remaining_items")
    if not isinstance(completed, list) or not isinstance(remaining, list) or completed + remaining != ids:
        raise CompletenessError("handoff completion order differs from ledger")
    matches = [row for row in rows if isinstance(row, dict) and row.get("lv_id") == lv_id]
    if not matches: raise CompletenessError("handoff LV is unlinked")
    allowed = {path for row in matches for path in row.get("owned_files", [])}
    if handoff.get("owned_files") != sorted(allowed) or any(path not in allowed for path in handoff.get("changed_files", [])):
        raise CompletenessError("handoff owned/changed files mismatch")
    if not handoff.get("tests") or not isinstance(handoff.get("review"), dict) or handoff["review"].get("verdict") != "PASS":
        raise CompletenessError("handoff test/review evidence incomplete")
    if handoff.get("selected_assets") != matches[0].get("selected_assets") or handoff.get("excluded_assets") != matches[0].get("excluded_assets") or handoff.get("selection_rationale") != matches[0].get("selection_rationale"):
        raise CompletenessError("handoff asset rationale differs from ledger")

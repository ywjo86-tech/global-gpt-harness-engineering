from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from .lv_execution_package import canonical_json_bytes
from .recovery_contract import is_completion_eligible


class CompletenessError(ValueError):
    pass


ENGINE_REQUIREMENT_IDS = tuple(f"R{number:02d}" for number in range(1, 26))
REQUIREMENT_IDS = ENGINE_REQUIREMENT_IDS  # legacy compatibility alias
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_HEAD = re.compile(r"[0-9a-f]{40,64}\Z")
_STATUSES = {"PENDING", "IMPLEMENTED", "VERIFIED", "CHECKPOINTED", "EXITED", "BLOCKED"}
_ROW_FIELDS = {
    "item_id", "item_kind", "gate_id", "lv_id", "order", "owned_files", "selected_assets",
    "excluded_assets", "selection_rationale", "tests", "evidence_sha256", "status",
    "checkpoint_ref", "exit_ref", "handoff_ref",
    "used_assets", "discovered_candidates", "evaluated_candidates", "selected_candidate",
    "candidate_use_authorized", "discovery_evidence_references", "evaluation_evidence_references",
}
_HANDOFF_FIELDS = {
    "schema_version", "project_id", "gate_id", "lv_id", "run_id", "requirements_sha256",
    "plan_sha256", "branch", "head", "completed_items", "remaining_items", "owned_files",
    "changed_files", "tests", "review", "artifact_sha256", "checkpoint_ref", "exit_ref",
    "ledger_sha256", "known_issues", "deferred_items", "next_condition", "permissions",
    "forbidden_actions", "selected_assets", "excluded_assets", "selection_rationale",
    "used_assets", "discovered_candidates", "evaluated_candidates", "selected_candidate",
    "candidate_use_authorized", "discovery_evidence_references", "evaluation_evidence_references",
}

PROJECT_REQUIREMENT_EVIDENCE_SCHEMA = "orchestration.project-requirement-evidence.v1"
COMPLETENESS_LEDGER_SCHEMA = "orchestration.completeness-ledger.v2"
STRUCTURED_HANDOFF_SCHEMA = "orchestration.structured-handoff.v2"


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _unique_strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item) for item in value) and len(value) == len(set(value))


def build_ledger(*, project_id: str, requirements_sha256: str, plan_sha256: str,
                 plan_items: Sequence[Mapping[str, object]], requirements: Mapping[str, Mapping[str, object]],
                 expected_requirement_ids: Sequence[str] | None = None) -> dict[str, object]:
    expected_ids = tuple(expected_requirement_ids) if expected_requirement_ids is not None else ENGINE_REQUIREMENT_IDS
    if len(set(expected_ids)) != len(expected_ids) or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", item) for item in expected_ids):
        raise CompletenessError("requirement ID order is invalid")
    if set(requirements) != set(expected_ids):
        raise CompletenessError("requirement completeness mismatch")
    rows: list[dict[str, object]] = []
    for item in plan_items:
        rows.append(_row(item, "PLAN_ITEM", len(rows) + 1))
    for requirement_id in expected_ids:
        value = dict(requirements[requirement_id]); value["item_id"] = requirement_id
        rows.append(_row(value, "REQUIREMENT", len(rows) + 1))
    payload = {
        "schema_version": COMPLETENESS_LEDGER_SCHEMA, "project_id": project_id,
        "requirements_sha256": requirements_sha256, "plan_sha256": plan_sha256, "items": rows,
    }
    validate_ledger(payload, plan_items=plan_items, requirements=requirements, expected_requirement_ids=expected_ids)
    return {"payload": payload, "ledger_sha256": _hash(payload)}


def _row(source: Mapping[str, object], kind: str, order: int) -> dict[str, object]:
    defaults = {
        "item_id": "", "gate_id": "", "lv_id": "", "owned_files": [], "selected_assets": [],
        "excluded_assets": [], "selection_rationale": "", "tests": [], "evidence_sha256": "",
        "status": "PENDING", "checkpoint_ref": "", "exit_ref": "", "handoff_ref": "",
        "used_assets": [], "discovered_candidates": [],
        "evaluated_candidates": [], "selected_candidate": "", "candidate_use_authorized": False,
        "discovery_evidence_references": [], "evaluation_evidence_references": [],
    }
    defaults.update(source)
    defaults["item_kind"] = kind; defaults["order"] = order
    if set(defaults) != _ROW_FIELDS:
        raise CompletenessError("ledger item schema mismatch")
    return defaults


def validate_ledger(payload: Mapping[str, object], *, plan_items: Sequence[Mapping[str, object]],
                    requirements: Mapping[str, Mapping[str, object]] | None = None,
                    requirements_sha256: str | None = None, plan_sha256: str | None = None,
                    require_exit: bool = False, expected_requirement_ids: Sequence[str] | None = None) -> None:
    if set(payload) != {"schema_version", "project_id", "requirements_sha256", "plan_sha256", "items"} or payload.get("schema_version") != COMPLETENESS_LEDGER_SCHEMA:
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
    expected_requirements = tuple(expected_requirement_ids) if expected_requirement_ids is not None else ENGINE_REQUIREMENT_IDS
    expected = expected_plan + list(expected_requirements)
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
        candidate_fields = ("used_assets", "discovered_candidates", "evaluated_candidates",
                            "discovery_evidence_references", "evaluation_evidence_references")
        if any(not _unique_strings(row[field]) for field in candidate_fields) or not isinstance(row["selected_candidate"], str) or not isinstance(row["candidate_use_authorized"], bool):
            raise CompletenessError("Skill Discovery ledger evidence is malformed")
        if set(row["discovered_candidates"]) & set(row["used_assets"]):
            raise CompletenessError("discovered candidate cannot be recorded as a used asset")
        if not set(row["evaluated_candidates"]).issubset(row["discovered_candidates"]):
            raise CompletenessError("evaluated candidate is not a discovered candidate")
        if row["selected_candidate"] and row["selected_candidate"] not in row["evaluated_candidates"]:
            raise CompletenessError("selected candidate is not an evaluated candidate")
        if row["candidate_use_authorized"] is not False:
            raise CompletenessError("candidate use authorization is outside Phase 3A")
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
            defaults_by_field = {
                "used_assets": [], "discovered_candidates": [],
                "evaluated_candidates": [], "selected_candidate": "", "candidate_use_authorized": False,
                "discovery_evidence_references": [], "evaluation_evidence_references": [],
            }
            for field in ("gate_id", "lv_id", "owned_files", "selected_assets", "excluded_assets", "selection_rationale", "tests",
                          "used_assets", "discovered_candidates", "evaluated_candidates", "selected_candidate",
                          "candidate_use_authorized", "discovery_evidence_references", "evaluation_evidence_references"):
                if row[field] != source.get(field, defaults_by_field.get(field)):
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


def aggregate_project_requirement_evidence(*, contract: Mapping[str, Mapping[str, object]],
                                           worker: Mapping[str, Mapping[str, object]],
                                           review: Mapping[str, Mapping[str, object]],
                                           project_id: str, gate_id: str, lv_id: str,
                                           plan_sha256: str, package_sha256: str,
                                           approval_sha256: str, contract_sha256: str,
                                           lifecycle_attempt: int = 1) -> dict[str, object]:
    """Combine truthful worker and independent-review evidence per requirement."""
    ids = tuple(contract)
    if not ids or len(set(ids)) != len(ids) or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", item) for item in ids) or set(worker) - set(ids) or set(review) - set(ids):
        raise CompletenessError("project requirement evidence IDs are missing, duplicate, or unknown")
    final: dict[str, object] = {}
    for requirement_id in ids:
        item = contract[requirement_id]
        w = worker.get(requirement_id); r = review.get(requirement_id)
        if not isinstance(item, Mapping) or item.get("status") != "PENDING" or item.get("semantic_sha256") is not None and not _SHA.fullmatch(str(item.get("semantic_sha256"))):
            raise CompletenessError("project requirement contract is not PENDING")
        if not isinstance(w, Mapping) or not isinstance(r, Mapping):
            raise CompletenessError(f"{requirement_id} implementation/review evidence is missing")
        for evidence in (w, r):
            if evidence.get("project_id") != project_id or evidence.get("gate_id") != gate_id or evidence.get("lv_id") != lv_id or evidence.get("plan_sha256") != plan_sha256 or evidence.get("package_sha256") != package_sha256 or evidence.get("approval_sha256") != approval_sha256 or evidence.get("contract_sha256") != contract_sha256 or evidence.get("requirement_id") != requirement_id or evidence.get("lifecycle_attempt") != lifecycle_attempt:
                raise CompletenessError(f"{requirement_id} evidence binding mismatch")
        owned = item.get("owned_files")
        changed = w.get("changed_files")
        if isinstance(owned, list) and isinstance(changed, list) and any(path not in owned for path in changed):
            raise CompletenessError(f"{requirement_id} implementation changed file is outside owned scope")
        if not is_completion_eligible(w) or not is_completion_eligible(r) or r.get("verdict") != "PASS" or w.get("status") != "IMPLEMENTED":
            final[requirement_id] = {"status": "INCOMPLETE", "worker": dict(w), "review": dict(r)}
            continue
        final[requirement_id] = {"schema_version": PROJECT_REQUIREMENT_EVIDENCE_SCHEMA, "project_id": project_id, "gate_id": gate_id, "lv_id": lv_id, "plan_sha256": plan_sha256, "package_sha256": package_sha256, "approval_sha256": approval_sha256, "contract_sha256": contract_sha256, "requirement_id": requirement_id, "semantic_sha256": item.get("semantic_sha256"), "lifecycle_attempt": lifecycle_attempt, "implementation_evidence": dict(w), "review_evidence": dict(r), "status": "COMPLETE", "verdict": "PASS"}
        final[requirement_id]["evidence_sha256"] = _hash(final[requirement_id])
    return final


def validate_project_requirement_evidence(record: Mapping[str, object], *, project_id: str,
                                          gate_id: str, lv_id: str, plan_sha256: str,
                                          package_sha256: str, approval_sha256: str,
                                          contract_sha256: str, requirement_id: str,
                                          lifecycle_attempt: int = 1) -> None:
    """Validate one final project evidence record without treating a contract as evidence."""
    required = {
        "schema_version", "project_id", "gate_id", "lv_id", "plan_sha256",
        "package_sha256", "approval_sha256", "contract_sha256", "requirement_id",
        "semantic_sha256", "lifecycle_attempt", "implementation_evidence",
        "review_evidence", "status", "verdict", "evidence_sha256",
    }
    if set(record) != required or record.get("schema_version") != PROJECT_REQUIREMENT_EVIDENCE_SCHEMA:
        raise CompletenessError("project evidence schema mismatch")
    expected = {
        "project_id": project_id, "gate_id": gate_id, "lv_id": lv_id,
        "plan_sha256": plan_sha256, "package_sha256": package_sha256,
        "approval_sha256": approval_sha256, "contract_sha256": contract_sha256,
        "requirement_id": requirement_id, "lifecycle_attempt": lifecycle_attempt,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise CompletenessError(f"project evidence {key} binding mismatch")
    if not isinstance(record.get("semantic_sha256"), str) or not _SHA.fullmatch(record["semantic_sha256"]):
        raise CompletenessError("project evidence semantic SHA is invalid")
    if not is_completion_eligible(record) or record.get("status") != "COMPLETE" or record.get("verdict") != "PASS":
        raise CompletenessError("project evidence is not complete")
    worker = record.get("implementation_evidence")
    review = record.get("review_evidence")
    if not isinstance(worker, Mapping) or not isinstance(review, Mapping):
        raise CompletenessError("project evidence component is missing")
    if worker.get("status") != "IMPLEMENTED" or review.get("verdict") != "PASS":
        raise CompletenessError("project evidence component verdict mismatch")
    if record.get("evidence_sha256") != _hash({key: record[key] for key in required if key != "evidence_sha256"}):
        raise CompletenessError("project evidence SHA mismatch")


def seal_handoff(payload: Mapping[str, object]) -> dict[str, object]:
    value = dict(payload)
    if set(value) != _HANDOFF_FIELDS or value.get("schema_version") != STRUCTURED_HANDOFF_SCHEMA:
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
    discovery_fields = ("used_assets", "discovered_candidates", "evaluated_candidates", "selected_candidate",
                        "candidate_use_authorized", "discovery_evidence_references", "evaluation_evidence_references")
    if any(handoff.get(field) != matches[0].get(field) for field in discovery_fields):
        raise CompletenessError("handoff Skill Discovery evidence differs from ledger")
    if set(handoff.get("discovered_candidates", [])) & set(handoff.get("used_assets", [])):
        raise CompletenessError("discovered candidate cannot be recorded as a used asset")
    if any(not _unique_strings(handoff.get(field)) for field in ("used_assets", "discovered_candidates", "evaluated_candidates",
                                                                  "discovery_evidence_references", "evaluation_evidence_references")):
        raise CompletenessError("handoff Skill Discovery identifiers are malformed or duplicated")
    if not set(handoff.get("evaluated_candidates", [])).issubset(handoff.get("discovered_candidates", [])):
        raise CompletenessError("evaluated candidate is not a discovered candidate")
    if handoff.get("selected_candidate") and handoff.get("selected_candidate") not in handoff.get("evaluated_candidates", []):
        raise CompletenessError("selected candidate is not an evaluated candidate")
    if handoff.get("candidate_use_authorized") is not False:
        raise CompletenessError("candidate use authorization is outside Phase 3A")

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from .approval_hash import calculate_record_hash
from .canonical_transition import validate_canonical_gate_state
from .production_approval import load_v2_event_log, validate_v2_chain


MAPPING_DIR = Path(__file__).resolve().parent / "contract_mappings"
MAPPING_ROOT_ENV = "HARNESS_CONTRACT_MAPPING_ROOT"
ALLOWED_CONTRACT_KEYS = {
    "development_plan",
    "changelog",
    "app_log",
    "orchestration_state_md",
}


class ContractMappingError(ValueError):
    pass


@dataclass(frozen=True)
class ContractMapping:
    project_root: Path
    project_id: str
    contract_paths: dict[str, Path]
    required_contract_keys: list[str]
    canonical_source: Path
    canonical_sha256: str
    approved_source: Path
    approved_source_sha256: str
    business_approval_path: Path
    gate_state_path: Path
    gate_state_ledger_path: Path | None
    transition_approval_id: str | None
    gate_approval_ids: dict[str, str] | None = None
    interpreter_policy_id: str | None = None
    historical_plan_sha256: tuple[str, ...] = ()
    task_lv_projection_path: Path | None = None
    task_lv_projection_sha256: str | None = None

    def summary(self, project_root: Path, selected_source: Path | None = None) -> dict[str, Any]:
        def relative(path: Path) -> str:
            return path.relative_to(project_root).as_posix()

        selected = selected_source or self.canonical_source
        selected_hash = self.canonical_sha256 if selected == self.canonical_source else self.approved_source_sha256
        return {
            "project_id": self.project_id,
            "contract_paths": {key: relative(path) for key, path in self.contract_paths.items()},
            "required_contract_keys": list(self.required_contract_keys),
            "canonical_implementation_source": {
                "path": relative(self.canonical_source),
                "sha256": self.canonical_sha256,
            },
            "approved_source_reference": {
                "path": relative(self.approved_source),
                "sha256": self.approved_source_sha256,
            },
            "selected_canonical_source": {
                "path": relative(selected),
                "sha256": selected_hash,
            },
            **({"gate_state_ledger": relative(self.gate_state_ledger_path)} if self.gate_state_ledger_path else {}),
            **({"historical_plan_sha256": list(self.historical_plan_sha256)} if self.historical_plan_sha256 else {}),
            **({"task_lv_authority_projection": {"path": relative(self.task_lv_projection_path), "sha256": self.task_lv_projection_sha256}}
               if self.task_lv_projection_path is not None and self.task_lv_projection_sha256 is not None else {}),
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_project_path(project_root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or "\\" in value:
        raise ContractMappingError(f"{field} must be a non-empty project-relative path")
    candidate = (project_root / value).resolve()
    if not candidate.is_relative_to(project_root):
        raise ContractMappingError(f"{field} escapes the project root")
    return candidate


def _source(payload: dict[str, Any], key: str, root: Path) -> tuple[Path, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ContractMappingError(f"{key} must be an object")
    path = _resolve_project_path(root, value.get("path"), f"{key}.path")
    digest = value.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ContractMappingError(f"{key}.sha256 must be a lowercase SHA-256 value")
    return path, digest


def _mapping_root(value: str | Path | None) -> Path:
    """Resolve the declarative mapping registry without crossing a symlink boundary.

    The normal installation uses the code-owned registry.  Production CLI fixtures
    and declarative onboarding may supply an isolated registry root explicitly (or
    through ``HARNESS_CONTRACT_MAPPING_ROOT``); this is intentionally process-local
    and never mutates the shared registry.
    """
    supplied = value if value is not None else __import__("os").environ.get(MAPPING_ROOT_ENV)
    if supplied is None:
        return MAPPING_DIR
    root = Path(supplied)
    if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink() or root != root.resolve():
        raise ContractMappingError("mapping root must be an existing absolute directory without symlink components")
    return root


def load_project_mapping(project_root: str | Path, *, mapping_root: str | Path | None = None) -> ContractMapping | None:
    root = Path(project_root).resolve()
    registry_root = _mapping_root(mapping_root)
    mapping_path = registry_root / f"{root.name}.json"
    if mapping_path.exists():
        candidates = [mapping_path]
    else:
        candidates = sorted(
            path for path in registry_root.glob("*.json")
            if path.is_file() and not path.is_symlink()
        )
        bound: list[Path] = []
        for candidate in candidates:
            try:
                candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ContractMappingError(f"malformed mapping entry: {candidate.name}") from exc
            canonical = candidate_payload.get("canonical_implementation_source")
            if not isinstance(canonical, dict):
                continue
            value = canonical.get("path")
            if not isinstance(value, str) or not value or Path(value).is_absolute():
                continue
            try:
                canonical_path = _resolve_project_path(root, value, "canonical_implementation_source.path")
            except ContractMappingError:
                continue
            expected = canonical.get("sha256")
            if canonical_path.is_file() and isinstance(expected, str) and sha256_file(canonical_path) == expected:
                bound.append(candidate)
        if not bound:
            return None
        if len(bound) != 1:
            raise ContractMappingError("project mapping resolution is ambiguous")
        mapping_path = bound[0]
    if mapping_path.is_symlink() or not mapping_path.is_file():
        raise ContractMappingError("mapping entry is missing, non-regular, or symlinked")
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ContractMappingError("mapping project_id must be a non-empty string")
    if mapping_path.stem == root.name and project_id != root.name:
        raise ContractMappingError("mapping project_id does not match the target project")

    raw_paths = payload.get("contract_paths")
    if not isinstance(raw_paths, dict) or not raw_paths:
        raise ContractMappingError("contract_paths must be a non-empty object")
    unknown = set(raw_paths) - ALLOWED_CONTRACT_KEYS
    if unknown:
        raise ContractMappingError(f"unsupported contract path keys: {sorted(unknown)}")
    contract_paths = {
        key: _resolve_project_path(root, value, f"contract_paths.{key}")
        for key, value in raw_paths.items()
    }

    required = payload.get("required_contract_keys")
    if not isinstance(required, list) or not required or any(key not in ALLOWED_CONTRACT_KEYS for key in required):
        raise ContractMappingError("required_contract_keys contains an unsupported key")
    if any(key not in contract_paths for key in required):
        raise ContractMappingError("each required mapped key must have an explicit contract path")

    canonical_path, canonical_digest = _source(payload, "canonical_implementation_source", root)
    approved_path, approved_digest = _source(payload, "approved_source_reference", root)
    if contract_paths.get("development_plan") != canonical_path:
        raise ContractMappingError("development_plan must point to canonical_implementation_source")

    static = payload.get("static_validation")
    if not isinstance(static, dict):
        raise ContractMappingError("static_validation must be an object")
    ledger_value = static.get("gate_state_ledger")
    ledger_path = None
    if ledger_value is not None:
        if not isinstance(ledger_value, str) or (root / ledger_value).is_symlink():
            raise ContractMappingError("static_validation.gate_state_ledger must be a non-symlink relative path")
        ledger_path = _resolve_project_path(root, ledger_value, "static_validation.gate_state_ledger")
    transition = payload.get("canonical_transition", {})
    if not isinstance(transition, dict):
        raise ContractMappingError("canonical_transition must be an object")
    transition_approval_id = transition.get("gate_1_approval_id")
    gate_approval_ids = transition.get("gate_approval_ids", {})
    if not isinstance(gate_approval_ids, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in gate_approval_ids.items()):
        raise ContractMappingError("canonical_transition.gate_approval_ids must be an object of strings")
    if transition_approval_id is not None and (not isinstance(transition_approval_id, str) or not transition_approval_id):
        raise ContractMappingError("canonical_transition.gate_1_approval_id must be null or a non-empty string")
    projection_value = payload.get("task_lv_authority_projection")
    task_lv_projection_path = None
    task_lv_projection_sha256 = None
    if projection_value is not None:
        task_lv_projection_path, task_lv_projection_sha256 = _source(payload, "task_lv_authority_projection", root)

    migrations = payload.get("plan_sha_migrations", [])
    if not isinstance(migrations, list) or any(
        not isinstance(item, dict) or set(item) != {"from", "to"}
        or not isinstance(item["from"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["from"])
        or not isinstance(item["to"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["to"])
        for item in migrations
    ):
        raise ContractMappingError("plan_sha_migrations is invalid")
    return ContractMapping(
        project_root=root,
        project_id=project_id,
        contract_paths=contract_paths,
        required_contract_keys=list(required),
        canonical_source=canonical_path,
        canonical_sha256=canonical_digest,
        approved_source=approved_path,
        approved_source_sha256=approved_digest,
        business_approval_path=_resolve_project_path(root, static.get("business_lv_approval"), "static_validation.business_lv_approval"),
        gate_state_path=_resolve_project_path(root, static.get("gate_state"), "static_validation.gate_state"),
        gate_state_ledger_path=ledger_path,
        transition_approval_id=transition_approval_id,
        gate_approval_ids=dict(gate_approval_ids),
        interpreter_policy_id=payload.get("interpreter_policy_id"),
        historical_plan_sha256=tuple(item["from"] for item in migrations),
        task_lv_projection_path=task_lv_projection_path,
        task_lv_projection_sha256=task_lv_projection_sha256,
    )


def validate_mapping_sources(mapping: ContractMapping) -> list[str]:
    errors: list[str] = []
    sources = [
        ("canonical implementation source", mapping.canonical_source, mapping.canonical_sha256),
        ("approved source reference", mapping.approved_source, mapping.approved_source_sha256),
    ]
    if mapping.task_lv_projection_path is not None and mapping.task_lv_projection_sha256 is not None:
        sources.append(("TASK-to-LV authority projection", mapping.task_lv_projection_path, mapping.task_lv_projection_sha256))
    for label, path, expected in sources:
        if not path.is_file():
            errors.append(f"{label} is missing")
        elif sha256_file(path) != expected:
            errors.append(f"{label} SHA-256 mismatch")
    return errors


def _approval_events(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ContractMappingError("approval event JSON is malformed") from exc
        if isinstance(value, dict) and value.get("schema_version") == "orchestration.production-approval-log.v2":
            raw_events = value.get("events")
            if not isinstance(raw_events, list) or any(not isinstance(item, dict) for item in raw_events):
                raise ContractMappingError("production approval log events must be objects")
            return [dict(item) for item in raw_events]
    events: list[dict[str, Any]] = []
    for block in re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL):
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            raise ContractMappingError("approval event JSON is malformed") from exc
        if not isinstance(value, dict):
            raise ContractMappingError("approval event must be an object")
        events.append(value)
    return events


def validate_approval_state(text: str, allowed_plan_hashes: set[str]) -> dict[str, Any]:
    stripped = text.strip()
    production_log_input = False
    if stripped.startswith("{"):
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError:
            document = None
        production_log_input = bool(
            isinstance(document, dict)
            and document.get("schema_version") == "orchestration.production-approval-log.v2"
        )
    required = {
        "approval_id",
        "target_type",
        "target_id",
        "approval_type",
        "approval_scope",
        "approval_version",
        "approval_hash_version",
        "plan_version",
        "plan_sha256",
        "external_action",
        "action_parameters",
        "approved_hash",
        "approved_by",
        "approved_at",
        "expires_at",
        "source_reference",
        "approval_event_type",
        "previous_approval_id",
        "revokes_approval_id",
        "previous_record_hash",
        "record_hash",
    }
    errors: list[str] = []
    try:
        events = _approval_events(text)
    except ContractMappingError as exc:
        events = []
        errors.append(str(exc))
    if not events:
        errors.append("no approval events found")
    raw_events = events
    events = []
    production_events: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    approval_ids: set[str] = set()
    lineage_heads: dict[tuple[object, object], dict[str, Any]] = {}
    record_hashes_valid = True
    production_chain_valid = True
    for index, event in enumerate(raw_events, start=1):
        if event.get("schema_version") == "orchestration.production-approval.v2":
            production_events.append(event)
            try:
                validate_v2_chain(
                    production_events,
                    initial_predecessor=previous.get("record_hash") if previous else None,
                    known_supersedes=approval_ids,
                )
            except ValueError as exc:
                production_chain_valid = False
                errors.append(f"event {index} production v2 validation failed: {exc}")
            if production_log_input and event.get("plan_sha256") not in allowed_plan_hashes:
                errors.append(f"event {index} plan SHA-256 is not bound to a mapped source")
            continue
        events.append(event)
        approval_id = event.get("approval_id")
        safe_id = approval_id if isinstance(approval_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", approval_id) else f"event-{index}"
        missing = sorted(required - set(event))
        if missing:
            errors.append(f"event {index} missing fields: {', '.join(missing)}")
        if not isinstance(approval_id, str) or not approval_id or approval_id in approval_ids:
            errors.append(f"event {index} approval_id is missing or duplicated")
        else:
            approval_ids.add(approval_id)
        lineage = (event.get("target_type"), event.get("target_id"))
        lineage_head = lineage_heads.get(lineage)
        if lineage_head is None:
            if event.get("approval_version") != 1:
                errors.append(f"event {index} first lineage approval_version must be 1")
            if event.get("previous_approval_id") is not None:
                errors.append(f"event {index} first lineage previous_approval_id must be null")
        else:
            expected_version = lineage_head.get("approval_version")
            if not isinstance(expected_version, int) or event.get("approval_version") != expected_version + 1:
                errors.append(f"event {index} lineage approval_version is not sequential")
            if event.get("previous_approval_id") != lineage_head.get("approval_id"):
                errors.append(f"event {index} previous_approval_id does not match the prior lineage event")
        if event.get("plan_sha256") not in allowed_plan_hashes:
            errors.append(f"event {index} plan SHA-256 is not bound to a mapped source")
        record_hash = event.get("record_hash")
        if not isinstance(record_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", record_hash):
            errors.append(f"event {index} ({safe_id}) record_hash format is invalid")
            record_hashes_valid = False
        elif calculate_record_hash(event) != record_hash:
            errors.append(f"event {index} ({safe_id}) record_hash payload mismatch")
            record_hashes_valid = False
        expected_previous = previous.get("record_hash") if previous else None
        if event.get("previous_record_hash") != expected_previous:
            errors.append(f"event {index} previous_record_hash does not link to the prior event")
        lineage_heads[lineage] = event
        previous = event
    return {
        "events": events,
        "event_count": len(events) + len(production_events),
        "schema_valid": not errors,
        "chain_links_valid": not any("previous_record_hash" in error for error in errors),
        "record_hashes_valid": (
            bool(production_events) and production_chain_valid
            if production_log_input
            else bool(events) and record_hashes_valid
        ),
        "plan_hash_bound": (
            bool(production_events) and all(event.get("plan_sha256") in allowed_plan_hashes for event in production_events)
            if production_log_input
            else bool(events) and all(event.get("plan_sha256") in allowed_plan_hashes for event in events)
        ),
        "errors": errors,
        "production_events": production_events,
    }


def _git_output(root: Path, *args: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _committed_blob(root: Path, commit: str, relative_path: str) -> bytes | None:
    return _git_output(root, "show", f"{commit}:{relative_path}")


LEDGER_FIELDS = {
    "schema_version",
    "project_id",
    "gate_id",
    "gate_state",
    "canonical_plan",
    "plan_sha256",
    "approval_id",
    "approval_record_hash",
    "active_scope",
    "owned_files",
}
LEDGER_OPTIONAL_FIELDS_V1 = {"last_review", "transition_authorized"}
LAST_REVIEW_FIELDS_V1 = {
    "decision", "review_artifact", "finding_counts", "recovery_required", "reason",
}


def _validate_legacy_ledger_extensions(value: Mapping[str, Any]) -> None:
    if "transition_authorized" in value and not isinstance(value["transition_authorized"], bool):
        raise ContractMappingError("legacy Gate transition_authorized must be boolean")
    review = value.get("last_review")
    if review is None:
        return
    if not isinstance(review, Mapping) or set(review) != LAST_REVIEW_FIELDS_V1:
        raise ContractMappingError("legacy Gate last_review schema is invalid")
    if review.get("decision") not in {"GO", "NO_GO"}:
        raise ContractMappingError("legacy Gate last_review decision is invalid")
    artifact = review.get("review_artifact")
    if not isinstance(artifact, str) or not artifact or Path(artifact).is_absolute() or ".." in PurePosixPath(artifact).parts:
        raise ContractMappingError("legacy Gate last_review artifact is invalid")
    counts = review.get("finding_counts")
    if (
        not isinstance(counts, Mapping)
        or set(counts) != {"BLOCKER", "MAJOR", "MINOR"}
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts.values())
    ):
        raise ContractMappingError("legacy Gate last_review finding counts are invalid")
    recovery = review.get("recovery_required")
    if recovery is not None and (not isinstance(recovery, str) or not recovery):
        raise ContractMappingError("legacy Gate last_review recovery reference is invalid")
    reason = review.get("reason")
    if not isinstance(reason, str) or not reason or len(reason) > 4096:
        raise ContractMappingError("legacy Gate last_review reason is invalid")
    if review["decision"] == "NO_GO" and value.get("transition_authorized") is not False:
        raise ContractMappingError("legacy Gate NO_GO review must fail closed")


LEDGER_FIELDS_V2 = {
    "schema_version", "project_id", "gate_id", "phase", "plan_sha256",
    "gate_status", "closure_status", "approval_record_hash",
}


def _json_no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractMappingError(f"Gate State ledger contains duplicate key: {key}")
        value[key] = item
    return value


def _ledger_payload(text: str) -> dict[str, Any]:
    if text.startswith("\ufeff") or "\x00" in text:
        raise ContractMappingError("Gate State ledger must be UTF-8 without BOM or NUL")
    if any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        raise ContractMappingError("Gate State ledger contains a conflict marker")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:AKIA|gh[pousr]_|sk-[A-Za-z0-9])", text):
        raise ContractMappingError("Gate State ledger contains a secret-like value")
    blocks = re.findall(r"```json[ \t]*\r?\n(.*?)\r?\n```", text, flags=re.DOTALL)
    if not blocks:
        raise ContractMappingError("Gate State ledger must contain a json fenced block")
    values: list[dict[str, Any]] = []
    for block in blocks:
        try:
            value = json.loads(block, object_pairs_hook=_json_no_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise ContractMappingError("Gate State ledger JSON is malformed") from exc
        if not isinstance(value, dict):
            raise ContractMappingError("Gate State ledger payload must be an object")
        is_v2 = value.get("schema_version") == "orchestration.canonical-gate-state.v2"
        expected_fields = LEDGER_FIELDS_V2 if is_v2 else LEDGER_FIELDS
        allowed_fields = expected_fields if is_v2 else expected_fields | LEDGER_OPTIONAL_FIELDS_V1
        if not expected_fields.issubset(value) or not set(value).issubset(allowed_fields):
            missing = sorted(expected_fields - set(value))
            unknown = sorted(set(value) - allowed_fields)
            detail = []
            if missing:
                detail.append(f"missing fields: {', '.join(missing)}")
            if unknown:
                detail.append(f"unknown fields: {', '.join(unknown)}")
            raise ContractMappingError("Gate State ledger fields are invalid (" + "; ".join(detail) + ")")
        if not is_v2:
            _validate_legacy_ledger_extensions(value)
        values.append(value)
    if len(values) > 1 and any(value.get("schema_version") != "orchestration.canonical-gate-state.v2" for value in values):
        raise ContractMappingError("append-only Gate State ledger entries must use canonical v2 schema")
    return values[-1]


def _validate_ledger_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or "\\" in value:
        raise ContractMappingError(f"{field} must be a project-relative POSIX path")
    parts = PurePosixPath(value).parts
    if ".." in parts or any(part == "" for part in parts):
        raise ContractMappingError(f"{field} must not escape the project root")
    return value


def _find_ledger_activation_commit(root: Path, relative_path: str, current: bytes) -> tuple[str, str] | None:
    history = _git_output(root, "rev-list", "--first-parent", "--reverse", "HEAD")
    if history is None:
        return None
    for raw_commit in history.decode("ascii").splitlines():
        commit = raw_commit.strip()
        blob = _committed_blob(root, commit, relative_path)
        if blob != current:
            continue
        parent = _git_output(root, "rev-parse", f"{commit}^")
        parent_blob = None
        if parent:
            parent_blob = _committed_blob(root, parent.decode("ascii").strip(), relative_path)
        if parent_blob == current:
            continue
        timestamp = _git_output(root, "show", "-s", "--format=%cI", commit)
        if timestamp is None:
            return None
        return commit, timestamp.decode("ascii").strip()
    return None


def canonical_gate_phase(mapping: ContractMapping) -> str | None:
    """Return the validated canonical v2 Gate phase when one is authoritative.

    Legacy ledgers intentionally return None so callers can retain their
    historical text-based phase fallback. Canonical v2 ledgers are validated
    through the same fail-closed path used by Gate orchestration before their
    phase is exposed as project status.
    """
    path = mapping.gate_state_ledger_path
    if path is None or not path.is_file() or path.is_symlink():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ContractMappingError("Gate State ledger must be valid UTF-8") from exc
    payload = _ledger_payload(text)
    if payload.get("schema_version") != "orchestration.canonical-gate-state.v2":
        return None
    validate_gate_state_ledger(mapping, [])
    return str(payload["phase"])


def validate_gate_state_ledger(mapping: ContractMapping, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    path = mapping.gate_state_ledger_path
    if path is None:
        return None
    relative = path.relative_to(mapping.project_root).as_posix()
    if not path.exists():
        if _committed_blob(mapping.project_root, "HEAD", relative) is not None:
            raise ContractMappingError("Gate State ledger is missing from the working tree")
        return None
    if path.is_symlink() or not path.is_file():
        raise ContractMappingError("Gate State ledger must be a regular non-symlink file")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractMappingError("Gate State ledger must be valid UTF-8") from exc
    payload = _ledger_payload(text)
    if payload["schema_version"] == "orchestration.canonical-gate-state.v2":
        try:
            validate_canonical_gate_state(
                payload, project_id=mapping.project_id, gate_id=str(payload["gate_id"]),
                phase=str(payload["phase"]), plan_sha256=mapping.canonical_sha256,
                approval_record_hash=payload["approval_record_hash"],
            )
        except ValueError as exc:
            raise ContractMappingError(str(exc)) from exc
        committed = _committed_blob(mapping.project_root, "HEAD", relative)
        if committed != raw:
            raise ContractMappingError("Gate State ledger is not committed at HEAD")
        activation = _find_ledger_activation_commit(mapping.project_root, relative, raw)
        if activation is None:
            raise ContractMappingError("Gate State ledger has no first-parent activation commit")
        production_event: dict[str, Any] | None = None
        if payload["gate_status"] == "READY_FOR_TRANSITION":
            try:
                production_events = load_v2_event_log(mapping.business_approval_path)
            except ValueError as exc:
                raise ContractMappingError(str(exc)) from exc
            production_event = production_events[-1]
            if (
                production_event.get("project_id") != mapping.project_id
                or production_event.get("gate_id") != payload["gate_id"]
                or production_event.get("plan_sha256") != payload["plan_sha256"]
                or production_event.get("record_hash") != payload["approval_record_hash"]
            ):
                raise ContractMappingError("production approval does not match canonical Gate state")
        return {
            "state": "GATE1_RESUME_READY" if production_event else "GATE1_APPROVAL_READY",
            "gate_id": payload["gate_id"],
            "canonical_plan": mapping.canonical_source.relative_to(mapping.project_root).as_posix(),
            "plan_sha256": payload["plan_sha256"],
            "approval_id": production_event.get("event_id") if production_event else None,
            "approval_record_hash": payload["approval_record_hash"],
            "active_scope": list(production_event.get("canonical_lv_scope", [])) if production_event else [],
            "owned_files": sorted({path for paths in production_event.get("owned_file_scope", {}).values() for path in paths}) if production_event else [],
            "activation_commit": activation[0],
            "activation_committed_at": activation[1],
            "ledger_path": relative,
        }
    if payload["schema_version"] != 1 or payload["project_id"] != mapping.project_id:
        raise ContractMappingError("Gate State ledger fixed fields are invalid")
    if payload["gate_state"] != "GATE1_ACTIVE":
        raise ContractMappingError("Gate State ledger gate_state must be GATE1_ACTIVE")
    canonical_relative = mapping.canonical_source.relative_to(mapping.project_root).as_posix()
    if payload["canonical_plan"] != canonical_relative:
        raise ContractMappingError("Gate State ledger canonical_plan is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", payload["plan_sha256"]) or payload["plan_sha256"] != mapping.canonical_sha256:
        raise ContractMappingError("Gate State ledger plan_sha256 is invalid")
    if not isinstance(payload["approval_id"], str) or not isinstance(payload["approval_record_hash"], str):
        raise ContractMappingError("Gate State ledger approval fields are invalid")
    expected_approval = (mapping.gate_approval_ids or {}).get(payload["gate_id"], mapping.transition_approval_id)
    if payload["approval_id"] != expected_approval or not re.fullmatch(r"[0-9a-f]{64}", payload["approval_record_hash"]):
        raise ContractMappingError("Gate State ledger approval binding is invalid")
    matches = [event for event in events if event.get("approval_id") == payload["approval_id"]]
    if len(matches) != 1 or matches[0].get("record_hash") != payload["approval_record_hash"]:
        raise ContractMappingError("Gate State ledger approval record is missing or mismatched")
    approval = matches[0]
    if approval.get("plan_sha256") != payload["plan_sha256"]:
        raise ContractMappingError("Gate State ledger approval plan binding is invalid")
    scope = payload["active_scope"]
    owned = payload["owned_files"]
    approval_scope_ids = approval.get("approval_scope", {}).get("lv3_ids")
    legacy_scope = False
    if isinstance(scope, list) and scope != approval_scope_ids:
        # Existing Wallet ledgers retain the last completed LV scope while a
        # migrated Gate approval records the full Gate scope. Accept that
        # representation only when it exactly matches the predecessor event;
        # never broaden or infer scope from identifiers.
        predecessor_id = approval.get("previous_approval_id")
        predecessor = next((event for event in events if event.get("approval_id") == predecessor_id), None)
        predecessor_scope = predecessor.get("approval_scope", {}) if isinstance(predecessor, dict) else {}
        legacy_scope = scope == predecessor_scope.get("lv3_ids")
        if not legacy_scope:
            raise ContractMappingError("Gate State ledger active_scope does not match approval scope")
    approved_owned = approval.get("approval_scope", {}).get("owned_files")
    if not isinstance(owned, list) or (owned != approved_owned and not (legacy_scope and owned == predecessor_scope.get("owned_files"))):
        raise ContractMappingError("Gate State ledger owned_files does not match approval scope")
    for index, item in enumerate(scope):
        if not isinstance(item, str) or not item:
            raise ContractMappingError(f"Gate State ledger active_scope[{index}] is invalid")
    for index, item in enumerate(owned):
        _validate_ledger_relative_path(item, f"owned_files[{index}]")
    committed = _committed_blob(mapping.project_root, "HEAD", relative)
    if committed != raw:
        raise ContractMappingError("Gate State ledger is not committed at HEAD")
    activation = _find_ledger_activation_commit(mapping.project_root, relative, raw)
    if activation is None:
        raise ContractMappingError("Gate State ledger has no first-parent activation commit")
    return {
        "state": "GATE1_ACTIVE",
        "gate_id": payload["gate_id"],
        "canonical_plan": payload["canonical_plan"],
        "plan_sha256": payload["plan_sha256"],
        "approval_id": payload["approval_id"],
        "approval_record_hash": payload["approval_record_hash"],
        "active_scope": list(scope),
        "owned_files": list(owned),
        "activation_commit": activation[0],
        "activation_committed_at": activation[1],
        "ledger_path": relative,
    }


def _gate_checkpoint_metadata(text: str) -> tuple[int, str] | None:
    closures = re.findall(r"Gate closure:\s*`(OPEN|CLOSED)`", text)
    exits = re.findall(r"G0-LV3-8:\s*`(PASS|FAIL)`", text)
    counts = re.findall(r"approval event count:\s*`(\d+)`", text)
    heads = re.findall(r"last `record_hash`:\s*`([0-9a-f]{64})`", text)
    if not closures or not exits or (closures[-1], exits[-1]) != ("CLOSED", "PASS"):
        return None
    if not counts or not heads:
        return None
    return int(counts[-1]), heads[-1]


def _find_gate_zero_checkpoint(
    root: Path,
    gate_relative: str,
    approval_relative: str,
    allowed_plan_hashes: set[str],
) -> tuple[str, int, str, list[dict[str, Any]]] | None:
    history = _git_output(root, "rev-list", "--first-parent", "--reverse", "HEAD")
    if history is None:
        return None
    for commit in history.decode("ascii").splitlines():
        gate_blob = _committed_blob(root, commit, gate_relative)
        approval_blob = _committed_blob(root, commit, approval_relative)
        if gate_blob is None or approval_blob is None:
            continue
        try:
            metadata = _gate_checkpoint_metadata(gate_blob.decode("utf-8"))
            approval_validation = validate_approval_state(
                approval_blob.decode("utf-8"),
                allowed_plan_hashes,
            )
        except UnicodeDecodeError:
            continue
        if metadata is None or not approval_validation["schema_valid"]:
            continue
        count, record_head = metadata
        events = approval_validation["events"]
        if count >= 1 and len(events) == count and events[-1].get("record_hash") == record_head:
            return commit, count, record_head, events
    return None



def _evaluate_first_gate_activation(mapping: ContractMapping, gate_text: str) -> dict[str, Any] | None:
    if "FIRST_GATE_ACTIVE" not in gate_text:
        return None
    root = mapping.project_root
    activation_path = root / "docs" / "harness" / "first-gate.activation.json"
    if not activation_path.is_file() or activation_path.is_symlink():
        raise ContractMappingError("first Gate activation is missing or unsafe")
    activation_raw = activation_path.read_bytes()
    activation_relative = activation_path.relative_to(root).as_posix()
    if _committed_blob(root, "HEAD", activation_relative) != activation_raw:
        raise ContractMappingError("first Gate activation is not committed at HEAD")
    try:
        activation = json.loads(activation_raw.decode("utf-8"), object_pairs_hook=_json_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractMappingError("first Gate activation is malformed") from exc
    expected_fields = {
        "schema_version", "project_id", "gate_id", "plan_sha256", "approval_id",
        "approval_record_hash", "branch", "head", "lv_order", "owned_files",
        "state", "system_transition",
    }
    if not isinstance(activation, dict) or set(activation) != expected_fields:
        raise ContractMappingError("first Gate activation schema mismatch")
    if (
        activation.get("schema_version") != "orchestration.first-gate.activation.v1"
        or activation.get("project_id") != mapping.project_id
        or activation.get("plan_sha256") != mapping.canonical_sha256
        or activation.get("state") != "ACTIVE"
        or activation.get("system_transition") is not True
        or not isinstance(activation.get("branch"), str)
        or not activation.get("branch")
    ):
        raise ContractMappingError("first Gate activation binding mismatch")
    active_branch_raw = _git_output(root, "branch", "--show-current")
    active_branch = active_branch_raw.decode("utf-8").strip() if active_branch_raw is not None else ""
    if not active_branch or active_branch != activation["branch"]:
        raise ContractMappingError("first Gate activation branch mismatch")
    if not isinstance(activation.get("gate_id"), str) or not activation["gate_id"]:
        raise ContractMappingError("first Gate activation gate_id is invalid")
    if not isinstance(activation.get("approval_id"), str) or not activation["approval_id"]:
        raise ContractMappingError("first Gate activation approval_id is invalid")
    if not isinstance(activation.get("approval_record_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", activation["approval_record_hash"]):
        raise ContractMappingError("first Gate activation approval record hash is invalid")
    if not isinstance(activation.get("head"), str) or not re.fullmatch(r"[0-9a-f]{40,64}", activation["head"]):
        raise ContractMappingError("first Gate activation baseline head is invalid")
    lv_order = activation.get("lv_order")
    owned_files = activation.get("owned_files")
    if not isinstance(lv_order, list) or not lv_order or len(set(lv_order)) != len(lv_order) or any(not isinstance(item, str) or not item for item in lv_order):
        raise ContractMappingError("first Gate activation LV order is invalid")
    if not isinstance(owned_files, list):
        raise ContractMappingError("first Gate activation owned_files is invalid")
    for index, item in enumerate(owned_files):
        _validate_ledger_relative_path(item, f"first_gate_activation.owned_files[{index}]")

    ledger = _ledger_payload(gate_text)
    canonical_relative = mapping.canonical_source.relative_to(root).as_posix()
    if (
        ledger.get("schema_version") != 1
        or ledger.get("project_id") != mapping.project_id
        or ledger.get("gate_id") != activation["gate_id"]
        or ledger.get("gate_state") != "GATE1_ACTIVE"
        or ledger.get("canonical_plan") != canonical_relative
        or ledger.get("plan_sha256") != mapping.canonical_sha256
        or ledger.get("approval_id") != activation["approval_id"]
        or ledger.get("active_scope") != lv_order
        or ledger.get("owned_files") != owned_files
    ):
        raise ContractMappingError("first Gate activation ledger binding mismatch")

    approval_raw = mapping.business_approval_path.read_bytes() if mapping.business_approval_path.is_file() else b""
    approval_relative = mapping.business_approval_path.relative_to(root).as_posix()
    if not approval_raw or mapping.business_approval_path.is_symlink() or _committed_blob(root, "HEAD", approval_relative) != approval_raw:
        raise ContractMappingError("first Gate approval log is missing, unsafe, or not committed at HEAD")
    try:
        approval_validation = validate_approval_state(
            approval_raw.decode("utf-8"),
            {mapping.approved_source_sha256, mapping.canonical_sha256, *mapping.historical_plan_sha256},
        )
    except UnicodeDecodeError as exc:
        raise ContractMappingError("first Gate approval log is not valid UTF-8") from exc
    if not approval_validation["schema_valid"]:
        raise ContractMappingError("first Gate approval log validation failed: " + "; ".join(approval_validation["errors"]))
    matches = [event for event in approval_validation["events"] if event.get("approval_id") == activation["approval_id"]]
    if len(matches) != 1:
        raise ContractMappingError("first Gate approval event is missing or duplicated")
    approval = matches[0]
    if (
        approval.get("target_type") != "GATE"
        or approval.get("target_id") != activation["gate_id"]
        or approval.get("approval_type") != "START_GATE"
        or approval.get("approval_event_type") not in {"APPROVED", "RENEWED"}
        or approval.get("plan_sha256") != mapping.canonical_sha256
        or approval.get("approved_hash") != activation["approval_record_hash"]
        or approval.get("record_hash") != ledger.get("approval_record_hash")
        or approval.get("approval_scope", {}).get("lv3_ids") != lv_order
        or approval.get("approval_scope", {}).get("owned_files") != owned_files
    ):
        raise ContractMappingError("first Gate approval event binding mismatch")

    gate_relative = mapping.gate_state_path.relative_to(root).as_posix()
    gate_raw = mapping.gate_state_path.read_bytes()
    if _committed_blob(root, "HEAD", gate_relative) != gate_raw:
        raise ContractMappingError("first Gate state ledger is not committed at HEAD")
    activation_commit = _find_ledger_activation_commit(root, activation_relative, activation_raw)
    if activation_commit is None:
        raise ContractMappingError("first Gate activation has no first-parent activation commit")
    activation_commit_id, activation_committed_at = activation_commit
    parent = _git_output(root, "rev-parse", f"{activation_commit_id}^")
    if parent is None or parent.decode("ascii").strip() != activation["head"]:
        raise ContractMappingError("first Gate activation baseline parent mismatch")
    changed = _git_output(root, "diff-tree", "--no-commit-id", "--name-only", "-r", activation_commit_id)
    expected_changed = {gate_relative, approval_relative, activation_relative}
    if changed is None or set(changed.decode("utf-8").splitlines()) != expected_changed:
        raise ContractMappingError("first Gate activation commit scope mismatch")

    return {
        "state": "GATE1_ACTIVE",
        "selected_source": mapping.canonical_source,
        "checkpoint_commit": activation["head"],
        "transition_authorized": bool(ledger.get("transition_authorized", True)),
        "gate_1_started": True,
        **({"last_review": dict(ledger["last_review"])} if isinstance(ledger.get("last_review"), Mapping) else {}),
        "gate_id": activation["gate_id"],
        "approval_id": activation["approval_id"],
        "approval_record_hash": ledger["approval_record_hash"],
        "canonical_plan": canonical_relative,
        "plan_sha256": mapping.canonical_sha256,
        "active_scope": list(lv_order),
        "owned_files": list(owned_files),
        "activation_commit": activation_commit_id,
        "activation_committed_at": activation_committed_at,
        "ledger_path": gate_relative,
    }

def evaluate_canonical_state(mapping: ContractMapping) -> dict[str, Any]:
    source_errors = validate_mapping_sources(mapping)
    if source_errors:
        raise ContractMappingError("; ".join(source_errors))

    root = mapping.project_root
    gate_text = mapping.gate_state_path.read_text(encoding="utf-8") if mapping.gate_state_path.is_file() else ""
    first_gate_state = _evaluate_first_gate_activation(mapping, gate_text)
    if first_gate_state is not None:
        return first_gate_state
    # Successor Gates use the canonical v2 Gate-state + production-approval
    # path.  Resolve that path before applying the legacy Gate-0 checkpoint
    # parser; newly onboarded projects intentionally have no Gate-0 markers.
    if gate_text:
        try:
            current_ledger = _ledger_payload(gate_text)
        except ContractMappingError:
            current_ledger = None
        if isinstance(current_ledger, dict) and current_ledger.get("schema_version") == "orchestration.canonical-gate-state.v2":
            ledger_state = validate_gate_state_ledger(mapping, [])
            if ledger_state is None:
                raise ContractMappingError("canonical Gate state ledger is unavailable")
            return {
                **ledger_state,
                "selected_source": mapping.canonical_source,
                "checkpoint_commit": ledger_state.get("activation_commit"),
                "transition_authorized": ledger_state["state"] == "GATE1_RESUME_READY",
                "gate_1_started": False,
            }
    approval_text = mapping.business_approval_path.read_text(encoding="utf-8") if mapping.business_approval_path.is_file() else ""
    closure_matches = re.findall(r"Gate closure:\s*`(OPEN|CLOSED)`", gate_text)
    exit_matches = re.findall(r"G0-LV3-8:\s*`(PASS|FAIL)`", gate_text)
    gate_one_not_started = bool(re.search(r"Gate 1:\s*(?:`)?(?:시작하지 않음|대기)", gate_text))
    # A newly onboarded project has no predecessor Gate checkpoint.  This
    # explicit state is a waiting boundary, not a fabricated Gate-0 closure.
    if "FIRST_GATE_WAITING_APPROVAL" in gate_text:
        return {
            "state": "FIRST_GATE_WAITING_APPROVAL",
            "selected_source": mapping.canonical_source,
            "checkpoint_commit": None,
            "transition_authorized": False,
            "gate_1_started": False,
        }
    if not closure_matches or not exit_matches:
        raise ContractMappingError("Gate 0 transition state is missing or unknown")

    closure = closure_matches[-1]
    exit_status = exit_matches[-1]
    checkpoint_counts = re.findall(r"approval event count:\s*`(\d+)`", gate_text)
    checkpoint_heads = re.findall(r"last `record_hash`:\s*`([0-9a-f]{64})`", gate_text)
    checkpoint_count = checkpoint_counts[-1] if checkpoint_counts else None
    checkpoint_head = checkpoint_heads[-1] if checkpoint_heads else None
    if (closure, exit_status) not in {("OPEN", "FAIL"), ("CLOSED", "PASS")}:
        raise ContractMappingError("Gate 0 transition evidence is conflicting")

    working_validation = validate_approval_state(
        approval_text,
        {mapping.approved_source_sha256, mapping.canonical_sha256, *mapping.historical_plan_sha256},
    )
    if not working_validation["schema_valid"]:
        raise ContractMappingError("working approval log validation failed: " + "; ".join(working_validation["errors"]))
    events = working_validation["events"]

    if closure == "OPEN":
        if mapping.transition_approval_id is not None:
            raise ContractMappingError("Gate 0 pre-checkpoint state conflicts with transition evidence")
        return {
            "state": "PRE_CHECKPOINT",
            "selected_source": mapping.approved_source,
            "checkpoint_commit": None,
            "transition_authorized": False,
            "gate_1_started": not gate_one_not_started,
        }

    if not checkpoint_count or not checkpoint_head:
        raise ContractMappingError("Gate 0 checkpoint approval count/head is missing")

    head_bytes = _git_output(root, "rev-parse", "--verify", "HEAD^{commit}")
    if head_bytes is None:
        raise ContractMappingError("CHECKPOINT_DECLARED_BUT_UNCOMMITTED: Git HEAD does not exist")
    checkpoint_commit = head_bytes.decode("ascii").strip()
    gate_relative = mapping.gate_state_path.relative_to(root).as_posix()
    approval_relative = mapping.business_approval_path.relative_to(root).as_posix()
    committed_gate = _committed_blob(root, "HEAD", gate_relative)
    committed_approval = _committed_blob(root, "HEAD", approval_relative)
    if committed_gate is None or committed_approval is None:
        raise ContractMappingError("CHECKPOINT_DECLARED_BUT_UNCOMMITTED: Git HEAD does not contain the Gate 0 report and approval log")
    if committed_gate != mapping.gate_state_path.read_bytes():
        raise ContractMappingError("CHECKPOINT_DECLARED_BUT_UNCOMMITTED: working Gate 0 report differs from the committed HEAD snapshot")
    if committed_approval != mapping.business_approval_path.read_bytes():
        raise ContractMappingError("working approval log differs from the committed HEAD snapshot")

    committed_validation = validate_approval_state(
        committed_approval.decode("utf-8"),
        {mapping.approved_source_sha256, mapping.canonical_sha256, *mapping.historical_plan_sha256},
    )
    if not committed_validation["schema_valid"]:
        raise ContractMappingError("committed approval log validation failed: " + "; ".join(committed_validation["errors"]))
    committed_events = committed_validation["events"]
    checkpoint = _find_gate_zero_checkpoint(
        root,
        gate_relative,
        approval_relative,
        {mapping.approved_source_sha256, mapping.canonical_sha256, *mapping.historical_plan_sha256},
    )
    if checkpoint is None:
        raise ContractMappingError("CHECKPOINT_DECLARED_BUT_UNCOMMITTED: no valid Gate 0 checkpoint exists in first-parent history")
    checkpoint_commit, count, checkpoint_record_head, checkpoint_events = checkpoint
    if int(checkpoint_count) != count or checkpoint_head != checkpoint_record_head:
        raise ContractMappingError("current Gate 0 checkpoint metadata differs from the committed checkpoint")
    if len(committed_events) < count or committed_events[:count] != checkpoint_events:
        raise ContractMappingError("committed approval log does not extend the Gate 0 checkpoint")

    ledger_state = validate_gate_state_ledger(mapping, committed_events)
    if ledger_state is not None and ledger_state["state"] in {"GATE1_APPROVAL_READY", "GATE1_RESUME_READY"}:
        return {
            **ledger_state,
            "selected_source": mapping.canonical_source,
            "checkpoint_commit": checkpoint_commit,
            "transition_authorized": ledger_state["state"] == "GATE1_RESUME_READY",
            "gate_1_started": False,
        }

    configured_gate_ids = list((mapping.gate_approval_ids or {}).keys())
    if len(configured_gate_ids) > 1:
        raise ContractMappingError("legacy transition mapping must identify one Gate")
    transition_id = next(iter((mapping.gate_approval_ids or {}).values()), None) or mapping.transition_approval_id
    transition_gate_id = configured_gate_ids[0] if configured_gate_ids else next(
        (
            str(event.get("target_id"))
            for event in committed_events[count:]
            if transition_id is not None and event.get("approval_id") == transition_id
        ),
        None,
    )
    unmapped_gate_candidates = [
        event
        for event in committed_events[count:]
        if event.get("target_type") == "GATE"
        and event.get("approval_type") == "START_GATE"
        and event.get("approval_event_type") in {"APPROVED", "RENEWED"}
    ]
    gate_candidates = [
        event for event in unmapped_gate_candidates
        if transition_gate_id is not None and event.get("target_id") == transition_gate_id
    ]
    if transition_id is None:
        if unmapped_gate_candidates:
            raise ContractMappingError("Gate approval exists but canonical transition mapping is not configured")
        return {
            "state": "GATE0_CLOSED_WAITING_GATE1_APPROVAL",
            "selected_source": mapping.approved_source,
            "checkpoint_commit": checkpoint_commit,
            "transition_authorized": False,
            "gate_1_started": False,
        }

    transition_id_events = [
        event
        for event in committed_events[count:]
        if event.get("approval_id") == transition_id
    ]
    if not gate_candidates and not transition_id_events:
        return {
            "state": "GATE0_CLOSED_WAITING_GATE1_APPROVAL",
            "selected_source": mapping.approved_source,
            "checkpoint_commit": checkpoint_commit,
            "transition_authorized": False,
            "gate_1_started": False,
        }
    if transition_id_events and not gate_candidates:
        raise ContractMappingError("Gate transition approval is not bound to the implementation plan")
    matches = [event for event in gate_candidates if event.get("approval_id") == transition_id]
    if len(matches) != 1:
        raise ContractMappingError("Gate transition approval is missing or duplicated")
    approval = matches[0]
    if not (
        approval.get("target_type") == "GATE"
        and approval.get("target_id") == transition_gate_id
        and approval.get("approval_type") == "START_GATE"
        and approval.get("approval_event_type") in {"APPROVED", "RENEWED"}
        and approval.get("plan_sha256") == mapping.canonical_sha256
    ):
        raise ContractMappingError("Gate transition approval is not bound to the implementation plan")
    ledger_state = validate_gate_state_ledger(mapping, committed_events)
    result = {
        "state": "TRANSITION_READY",
        "selected_source": mapping.canonical_source,
        "checkpoint_commit": checkpoint_commit,
        "transition_authorized": True,
        "gate_1_started": ledger_state is not None,
    }
    if ledger_state is not None:
        result.update(ledger_state)
        result["state"] = "GATE1_ACTIVE"
    return result


def select_canonical_source(mapping: ContractMapping) -> Path:
    return evaluate_canonical_state(mapping)["selected_source"]

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAPPING_DIR = Path(__file__).resolve().parent / "contract_mappings"
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
    project_id: str
    contract_paths: dict[str, Path]
    required_contract_keys: list[str]
    canonical_source: Path
    canonical_sha256: str
    approved_source: Path
    approved_source_sha256: str
    business_approval_path: Path
    gate_state_path: Path
    transition_approval_id: str | None

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
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_project_path(project_root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
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


def load_project_mapping(project_root: str | Path) -> ContractMapping | None:
    root = Path(project_root).resolve()
    mapping_path = MAPPING_DIR / f"{root.name}.json"
    if not mapping_path.exists():
        return None
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    if payload.get("project_id") != root.name:
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
    transition = payload.get("canonical_transition", {})
    if not isinstance(transition, dict):
        raise ContractMappingError("canonical_transition must be an object")
    transition_approval_id = transition.get("gate_1_approval_id")
    if transition_approval_id is not None and (not isinstance(transition_approval_id, str) or not transition_approval_id):
        raise ContractMappingError("canonical_transition.gate_1_approval_id must be null or a non-empty string")
    return ContractMapping(
        project_id=root.name,
        contract_paths=contract_paths,
        required_contract_keys=list(required),
        canonical_source=canonical_path,
        canonical_sha256=canonical_digest,
        approved_source=approved_path,
        approved_source_sha256=approved_digest,
        business_approval_path=_resolve_project_path(root, static.get("business_lv_approval"), "static_validation.business_lv_approval"),
        gate_state_path=_resolve_project_path(root, static.get("gate_state"), "static_validation.gate_state"),
        transition_approval_id=transition_approval_id,
    )


def validate_mapping_sources(mapping: ContractMapping) -> list[str]:
    errors: list[str] = []
    for label, path, expected in (
        ("canonical implementation source", mapping.canonical_source, mapping.canonical_sha256),
        ("approved source reference", mapping.approved_source, mapping.approved_source_sha256),
    ):
        if not path.is_file():
            errors.append(f"{label} is missing")
        elif sha256_file(path) != expected:
            errors.append(f"{label} SHA-256 mismatch")
    return errors


def _approval_events(text: str) -> list[dict[str, Any]]:
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


def select_canonical_source(mapping: ContractMapping) -> Path:
    source_errors = validate_mapping_sources(mapping)
    if source_errors:
        raise ContractMappingError("; ".join(source_errors))

    gate_text = mapping.gate_state_path.read_text(encoding="utf-8") if mapping.gate_state_path.is_file() else ""
    approval_text = mapping.business_approval_path.read_text(encoding="utf-8") if mapping.business_approval_path.is_file() else ""
    closure_match = re.search(r"Gate closure:\s*`(OPEN|CLOSED)`", gate_text)
    exit_match = re.search(r"G0-LV3-8:\s*`(PASS|FAIL)`", gate_text)
    gate_one_not_started = bool(re.search(r"Gate 1:\s*(?:`)?(?:시작하지 않음|대기)", gate_text))
    if not closure_match or not exit_match:
        raise ContractMappingError("Gate 0 transition state is missing or unknown")

    closure = closure_match.group(1)
    exit_status = exit_match.group(1)
    checkpoint_count = re.search(r"approval event count:\s*`(\d+)`", gate_text)
    checkpoint_head = re.search(r"last `record_hash`:\s*`([0-9a-f]{64})`", gate_text)
    checkpoint_commit = re.search(r"local checkpoint commit:\s*`([0-9a-f]{40}|[0-9a-f]{64})`", gate_text)
    has_checkpoint = bool(checkpoint_count and checkpoint_head and checkpoint_commit)

    if (closure, exit_status) not in {("OPEN", "FAIL"), ("CLOSED", "PASS")}:
        raise ContractMappingError("Gate 0 transition evidence is conflicting")

    pre_checkpoint = closure == "OPEN" or exit_status == "FAIL" or not has_checkpoint or gate_one_not_started
    if pre_checkpoint:
        if has_checkpoint or mapping.transition_approval_id is not None:
            raise ContractMappingError("Gate 0 pre-checkpoint state conflicts with transition evidence")
        return mapping.approved_source

    if mapping.transition_approval_id is None:
        raise ContractMappingError("Gate 1 transition approval is not configured")

    events = _approval_events(approval_text)
    previous_record_hash: str | None = None
    approval_ids: set[str] = set()
    for event in events:
        approval_id = event.get("approval_id")
        record_hash = event.get("record_hash")
        if not isinstance(approval_id, str) or not approval_id or approval_id in approval_ids:
            raise ContractMappingError("approval log contains a missing or duplicated approval_id")
        if not isinstance(record_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", record_hash):
            raise ContractMappingError("approval log contains an invalid record_hash")
        if event.get("previous_record_hash") != previous_record_hash:
            raise ContractMappingError("approval log record_hash chain is disconnected")
        approval_ids.add(approval_id)
        previous_record_hash = record_hash
    count = int(checkpoint_count.group(1))
    if count < 1 or len(events) < count or events[count - 1].get("record_hash") != checkpoint_head.group(1):
        raise ContractMappingError("approval log does not match the Gate 0 checkpoint")
    matches = [event for event in events if event.get("approval_id") == mapping.transition_approval_id]
    if len(matches) != 1:
        raise ContractMappingError("Gate 1 transition approval is missing or duplicated")
    approval = matches[0]
    if not (
        approval.get("target_type") == "GATE"
        and approval.get("approval_type") == "START_GATE"
        and approval.get("approval_event_type") in {"APPROVED", "RENEWED"}
        and approval.get("plan_sha256") == mapping.canonical_sha256
    ):
        raise ContractMappingError("Gate 1 transition approval is not bound to the implementation plan")
    return mapping.canonical_source

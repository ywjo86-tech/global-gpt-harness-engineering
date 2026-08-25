from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .approval_hash import calculate_record_hash
from .contract_adapter import load_project_mapping, select_canonical_source, sha256_file, validate_mapping_sources
from .contract_loader import load_contract


class ReadOnlyValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("read-only static validation failed")
        self.report = report


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _validate_approval_state(text: str, allowed_plan_hashes: set[str]) -> dict[str, Any]:
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
    events: list[dict[str, Any]] = []
    for block in re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            errors.append("approval event JSON is malformed")
            continue
        if isinstance(value, dict):
            events.append(value)
    if not events:
        errors.append("no approval events found")
    previous: dict[str, Any] | None = None
    record_hashes_valid = True
    for index, event in enumerate(events, start=1):
        approval_id = event.get("approval_id")
        safe_id = approval_id if isinstance(approval_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", approval_id) else f"event-{index}"
        missing = sorted(required - set(event))
        if missing:
            errors.append(f"event {index} missing fields: {', '.join(missing)}")
        if event.get("plan_sha256") not in allowed_plan_hashes:
            errors.append(f"event {index} plan SHA-256 is not bound to a mapped source")
        if event.get("approval_version") != index:
            errors.append(f"event {index} approval_version is not sequential")
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
        previous = event
    return {
        "event_count": len(events),
        "schema_valid": not errors,
        "chain_links_valid": not any("link" in error for error in errors),
        "record_hashes_valid": bool(events) and record_hashes_valid,
        "plan_hash_bound": bool(events) and all(event.get("plan_sha256") in allowed_plan_hashes for event in events),
        "errors": errors,
    }


def inspect_read_only(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    mapping = load_project_mapping(root)
    approval_validation: dict[str, Any] | None = None
    if mapping is not None:
        approval_validation = _validate_approval_state(
            _read(mapping.business_approval_path),
            {mapping.approved_source_sha256, mapping.canonical_sha256},
        )
        if not approval_validation["schema_valid"]:
            raise ReadOnlyValidationError(
                {
                    "inspection_mode": "read_only_no_write",
                    "write_operations_performed": False,
                    "contract_mapping": {
                        **mapping.summary(root, mapping.approved_source),
                        "configured": True,
                        "valid": False,
                        "errors": ["approval validation failed before canonical selection"],
                    },
                    "project_static_inspect": {
                        "project_id": root.name,
                        "status": "not_evaluated",
                    },
                    "business_lv_approval_state": {
                        "namespace": "business_lv_gate_approval",
                        "status": "invalid_static_evidence",
                        "validation": "static_only",
                        "reused_as_runtime_approval": False,
                        "source": _relative(root, mapping.business_approval_path),
                        **approval_validation,
                    },
                    "business_gate_state": {
                        "namespace": "business_gate_state",
                        "status": "not_evaluated",
                        "validation": "static_only",
                        "transition_authorized": False,
                    },
                    "codex_runtime_sandbox_approval_state": {
                        "namespace": "codex_runtime_sandbox_approval",
                        "status": "not_requested_read_only",
                        "business_approval_reused": False,
                        "runtime_mutation_authorized": False,
                    },
                }
            )

    contract = load_contract(root, strict=True)

    mapping_report: dict[str, Any] = {"configured": mapping is not None, "valid": True}
    business_report: dict[str, Any] = {
        "namespace": "business_lv_gate_approval",
        "status": "not_configured",
        "validation": "static_only",
        "reused_as_runtime_approval": False,
    }
    gate_report: dict[str, Any] = {
        "namespace": "business_gate_state",
        "status": "not_configured",
        "validation": "static_only",
        "transition_authorized": False,
    }

    if mapping is not None:
        errors = validate_mapping_sources(mapping)
        selected_source = select_canonical_source(mapping)
        mapping_report = {
            **mapping.summary(root, selected_source),
            "configured": True,
            "valid": not errors,
            "errors": errors,
            "observed_sha256": {
                _relative(root, mapping.canonical_source): sha256_file(mapping.canonical_source),
                _relative(root, mapping.approved_source): sha256_file(mapping.approved_source),
            },
        }
        assert approval_validation is not None
        business_report.update(
            {
                "source": _relative(root, mapping.business_approval_path),
                "status": "static_evidence_valid" if approval_validation["schema_valid"] else "invalid_static_evidence",
                **approval_validation,
            }
        )
        gate_text = _read(mapping.gate_state_path)
        closure = re.search(r"Gate closure:\s*`([^`]+)`", gate_text)
        lv3 = re.search(r"G0-LV3-8:\s*`([^`]+)`", gate_text)
        gate_one_not_started = bool(re.search(r"Gate 1:\s*(?:`)?(?:시작하지 않음|대기)", gate_text))
        gate_errors: list[str] = []
        if not gate_text:
            gate_errors.append("gate evidence is missing")
        if not closure:
            gate_errors.append("Gate closure is missing")
        if not lv3:
            gate_errors.append("G0-LV3-8 status is missing")
        if not gate_one_not_started:
            gate_errors.append("Gate 1 non-started evidence is missing")
        gate_report.update(
            {
                "source": _relative(root, mapping.gate_state_path),
                "status": "static_evidence_valid" if not gate_errors else "invalid_static_evidence",
                "gate_closure": closure.group(1) if closure else "unknown",
                "g0_lv3_8": lv3.group(1) if lv3 else "unknown",
                "gate_1_started": False if gate_one_not_started else "unknown",
                "errors": gate_errors,
            }
        )

    report = {
        "inspection_mode": "read_only_no_write",
        "write_operations_performed": False,
        "contract_mapping": mapping_report,
        "project_static_inspect": {
            "project_id": root.name,
            "current_phase": contract.current_phase,
            "required_contract_files_valid": not contract.missing_files,
        },
        "business_lv_approval_state": business_report,
        "business_gate_state": gate_report,
        "codex_runtime_sandbox_approval_state": {
            "namespace": "codex_runtime_sandbox_approval",
            "status": "not_requested_read_only",
            "business_approval_reused": False,
            "runtime_mutation_authorized": False,
        },
    }
    if not mapping_report["valid"] or business_report["status"] == "invalid_static_evidence" or gate_report["status"] == "invalid_static_evidence":
        raise ReadOnlyValidationError(report)
    return report

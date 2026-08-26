from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .contract_adapter import (
    evaluate_canonical_state,
    load_project_mapping,
    sha256_file,
    validate_approval_state,
    validate_mapping_sources,
)
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
    report = validate_approval_state(text, allowed_plan_hashes)
    return {key: value for key, value in report.items() if key != "events"}


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
        canonical_state = evaluate_canonical_state(mapping)
        selected_source = canonical_state["selected_source"]
        mapping_report = {
            **mapping.summary(root, selected_source),
            "configured": True,
            "valid": not errors,
            "errors": errors,
            "observed_sha256": {
                _relative(root, mapping.canonical_source): sha256_file(mapping.canonical_source),
                _relative(root, mapping.approved_source): sha256_file(mapping.approved_source),
            },
            "canonical_state": canonical_state["state"],
            "checkpoint_commit": canonical_state["checkpoint_commit"],
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
        closures = re.findall(r"Gate closure:\s*`([^`]+)`", gate_text)
        lv3_results = re.findall(r"G0-LV3-8:\s*`([^`]+)`", gate_text)
        gate_one_not_started = bool(re.search(r"Gate 1:\s*(?:`)?(?:시작하지 않음|대기)", gate_text))
        gate_one_active = canonical_state["state"] == "GATE1_ACTIVE"
        gate_errors: list[str] = []
        if not gate_text:
            gate_errors.append("gate evidence is missing")
        if not closures:
            gate_errors.append("Gate closure is missing")
        if not lv3_results:
            gate_errors.append("G0-LV3-8 status is missing")
        if not gate_one_not_started and not gate_one_active:
            gate_errors.append("Gate 1 non-started evidence is missing")
        gate_report.update(
            {
                "source": _relative(root, mapping.gate_state_path),
                "status": "static_evidence_valid" if not gate_errors else "invalid_static_evidence",
                "gate_closure": closures[-1] if closures else "unknown",
                "g0_lv3_8": lv3_results[-1] if lv3_results else "unknown",
                "transition_authorized": bool(canonical_state.get("transition_authorized", False)),
                "gate_1_started": gate_one_active,
                "errors": gate_errors,
            }
        )
        if gate_one_active:
            gate_report["activation_commit"] = canonical_state["activation_commit"]
            gate_report["activation_committed_at"] = canonical_state["activation_committed_at"]

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

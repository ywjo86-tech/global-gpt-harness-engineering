from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

BASELINE_ID = "FULL_PLAN_STABLE_BASELINE"
DEFAULT_MANIFEST = "docs/harness/FULL_PLAN_STABLE_BASELINE_FINAL_MANIFEST_20260914.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root: Path, relative_path: str) -> Path | None:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _git_commit_exists(root: Path, commit_sha: str) -> bool:
    if not _GIT_SHA_RE.fullmatch(commit_sha):
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def verify_predecessor_baseline(
    project_root: str | Path,
    expected_baseline_ref: str,
    *,
    manifest_path: str = DEFAULT_MANIFEST,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    reasons: list[str] = []
    verified_hashes: dict[str, str] = {}
    evidence_refs: list[str] = []

    manifest_file = _inside(root, manifest_path)
    if manifest_file is None or not manifest_file.is_file():
        reasons.append("manifest_missing_or_outside_project")
        manifest: dict[str, Any] = {}
    else:
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
            reasons.append("manifest_unreadable_or_invalid_json")
    required_manifest = {
        "baseline_id": BASELINE_ID,
        "baseline_commit_sha": expected_baseline_ref,
        "origin_main_sha": expected_baseline_ref,
        "synchronized": True,
        "completion_status": "VERIFIED_COMPLETE",
        "final_baseline_approval_status": "APPROVED_SEALED",
        "blocking_defects_found": 0,
    }
    for key, expected in required_manifest.items():
        if manifest.get(key) != expected:
            reasons.append(f"manifest_{key}_mismatch")

    raw_refs: list[dict[str, Any]] = []
    raw_refs.extend(manifest.get("documents", []) if isinstance(manifest.get("documents"), list) else [])
    raw_refs.extend(manifest.get("source_evidence", []) if isinstance(manifest.get("source_evidence"), list) else [])
    approval_record = manifest.get("approval_record")
    if isinstance(approval_record, dict):
        raw_refs.append(approval_record)
    else:
        reasons.append("approval_record_missing")

    seen: set[str] = set()
    for item in raw_refs:
        rel = str(item.get("path", ""))
        digest = str(item.get("sha256", ""))
        if not rel or rel in seen:
            reasons.append("evidence_reference_missing_or_ambiguous")
            continue
        seen.add(rel)
        evidence_refs.append(rel)
        target = _inside(root, rel)
        if target is None or not target.is_file():
            reasons.append(f"evidence_missing:{rel}")
            continue
        actual = _sha256(target)
        verified_hashes[rel] = actual
        if not _SHA256_RE.fullmatch(digest) or actual != digest:
            reasons.append(f"evidence_hash_mismatch:{rel}")

    if isinstance(approval_record, dict):
        approval_path = _inside(root, str(approval_record.get("path", "")))
        if approval_path is not None and approval_path.is_file():
            try:
                approval = json.loads(approval_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                approval = {}
                reasons.append("approval_record_unreadable_or_invalid_json")
            expected_approval = {
                "baseline_id": BASELINE_ID,
                "normalized_decision": "APPROVED",
                "baseline_commit_sha": expected_baseline_ref,
                "origin_main_sha": expected_baseline_ref,
                "completion_status": "VERIFIED_COMPLETE",
                "blocking_defects_found": 0,
            }
            for key, expected in expected_approval.items():
                if approval.get(key) != expected:
                    reasons.append(f"approval_{key}_mismatch")

    if not _git_commit_exists(root, expected_baseline_ref):
        reasons.append("baseline_git_commit_missing")
    verified = not reasons
    record: dict[str, Any] = {
        "record_type": "PredecessorBaselineEvidenceRecord",
        "baseline_id": BASELINE_ID,
        "baseline_ref": expected_baseline_ref,
        "manifest_path": manifest_path,
        "evidence_refs": evidence_refs,
        "verified_hashes": verified_hashes,
        "verification_status": "VERIFIED" if verified else "FAILED",
        "predecessor_entry_eligible": verified,
        "reasons": reasons,
    }

    if output_path is not None:
        destination = Path(output_path)
        if not destination.is_absolute():
            destination = root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return record


DANGEROUS_INSTALL_APPROVAL_PHRASE = "위험 확인 후 승인"


def evaluate_poc_entry_gate(
    predecessor_record: dict[str, Any],
    source_record: dict[str, Any],
    version_record: dict[str, Any],
    baseline_guard_record: dict[str, Any],
    install_approval_record: dict[str, Any],
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    prerequisite_status = {
        "predecessor_verified": (
            predecessor_record.get("verification_status") == "VERIFIED"
            and predecessor_record.get("predecessor_entry_eligible") is True
        ),
        "current_source_reverified": (
            source_record.get("current_source_baseline") == "REVERIFIED"
            and source_record.get("test_002_status") == "PASS"
            and source_record.get("unresolved_what_impact_drift") is False
            and source_record.get("source_drift_detected") is False
        ),
        "version_qualified": (
            version_record.get("qualification_status")
            == "QUALIFIED_PINNED_FOR_INSTALLATION_REQUEST"
            and bool(version_record.get("package_name"))
            and bool(version_record.get("version"))
            and bool(version_record.get("exact_requirement"))
            and version_record.get("installation_ready_subject_to_gate") is True
            and version_record.get("installer_policy", {}).get("package_installation_performed") is False
            and version_record.get("installer_policy", {}).get("automatic_upgrade_allowed") is False
            and version_record.get("transport_policy", {}).get("shared_http_allowed") is False
            and version_record.get("transport_policy", {}).get("external_semantic_backend_allowed") is False
        ),
        "controlled_baseline_clear": (
            baseline_guard_record.get("guard_status") == "CLEAR"
            and baseline_guard_record.get("verification_status") == "VERIFIED"
            and baseline_guard_record.get("entry_eligible") is True
            and baseline_guard_record.get("controlled_change_required") is False
        ),
        "dangerous_install_approval": (
            install_approval_record.get("normalized_decision") == "APPROVED"
            and install_approval_record.get("approval_scope") == "GRAPHIFY_PACKAGE_INSTALLATION"
            and install_approval_record.get("approval_statement_verbatim")
            == DANGEROUS_INSTALL_APPROVAL_PHRASE
        ),
    }
    baseline_refs = {
        str(predecessor_record.get("baseline_ref", "")),
        str(source_record.get("baseline_ref", "")),
        str(baseline_guard_record.get("baseline_ref", "")),
    }
    prerequisite_status["baseline_refs_consistent"] = (
        len(baseline_refs) == 1 and "" not in baseline_refs
    )

    reasons = [
        f"prerequisite_failed:{name}"
        for name, passed in prerequisite_status.items()
        if not passed
    ]
    gate_open = not reasons
    record: dict[str, Any] = {
        "record_type": "GraphifyPoCEntryGateRecord",
        "gate_id": "GATE-002",
        "gate_status": "OPEN" if gate_open else "CLOSED",
        "entry_eligible": gate_open,
        "package_installation_authorized": gate_open,
        "poc_runtime_ready": False,
        "next_step": "TASK-005" if gate_open else "REMEDIATE_PREREQUISITES",
        "prerequisites": prerequisite_status,
        "baseline_ref": next(iter(baseline_refs)) if len(baseline_refs) == 1 else "",
        "exact_requirement": str(version_record.get("exact_requirement", "")),
        "reasons": reasons,
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return record

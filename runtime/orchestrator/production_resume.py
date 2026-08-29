"""Read-only bridge for promoting immutable LV exits into a v2 Gate resume."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .gate_orchestrator import GatePlan, load_gate_plan
from .contract_adapter import load_project_mapping


class ResumeBridgeError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ResumeBridgeError(f"immutable evidence is missing or unsafe: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResumeBridgeError(f"immutable evidence is malformed: {path.name}") from exc
    if not isinstance(value, dict):
        raise ResumeBridgeError(f"immutable evidence must be an object: {path.name}")
    return value


def _attempt(root: Path, run_id: str) -> Path:
    candidates = sorted((root / "_workspace" / "orchestration-results" / run_id).glob("attempt-*/reviewer.report.json"))
    candidates += [root / "_workspace" / "orchestration-results" / run_id / "reviewer.report.json"]
    for candidate in reversed(candidates):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise ResumeBridgeError(f"immutable review evidence is missing for {run_id}")


def _run_id_for(plan_item: str) -> str:
    # Historical run names are supplied by immutable package metadata; this
    # fallback is only used for generic fixtures and never for Wallet logic.
    return plan_item.lower()


def _discover_run_ids(harness_root: Path, gate_id: str) -> dict[str, str]:
    discovered: dict[str, str] = {}
    for manifest_path in (harness_root / "_workspace" / "orchestration-runs").glob("*/package.manifest.json"):
        try:
            manifest = _load(manifest_path)
        except ResumeBridgeError:
            continue
        if manifest.get("gate_id") == gate_id and isinstance(manifest.get("lv_id"), str):
            discovered.setdefault(manifest["lv_id"], manifest_path.parent.name)
    return discovered


def build_resume_bridge(project_root: str | Path, harness_root: str | Path, gate_id: str,
                        *, plan_sha256: str, completed_run_ids: Mapping[str, str] | None = None,
                        required_completed: tuple[str, ...] = ()) -> dict[str, Any]:
    plan: GatePlan = load_gate_plan(project_root, gate_id)
    if plan.canonical_plan_sha256 != plan_sha256:
        raise ResumeBridgeError("resume bridge plan SHA mismatch")
    completed_run_ids = {**_discover_run_ids(Path(harness_root), gate_id), **dict(completed_run_ids or {})}
    mapping = load_project_mapping(project_root)
    historical = set(mapping.historical_plan_sha256) if mapping else set()
    completed: list[dict[str, Any]] = []
    first_incomplete: str | None = None
    for item in plan.lvs:
        run_id = completed_run_ids.get(item.lv_id, _run_id_for(item.lv_id))
        try:
            package = Path(harness_root) / "_workspace" / "orchestration-runs" / run_id / "package.manifest.json"
            manifest = _load(package)
            review_path = _attempt(Path(harness_root), run_id)
            review = _load(review_path)
            if manifest.get("gate_id") != gate_id or manifest.get("lv_id") != item.lv_id:
                raise ResumeBridgeError("evidence Gate/LV binding mismatch")
            if manifest.get("canonical_plan_sha256") not in ({plan_sha256} | historical):
                raise ResumeBridgeError("historical evidence plan SHA is not mapped to canonical plan")
            if review.get("verdict") != "PASS":
                raise ResumeBridgeError("immutable review evidence is not PASS")
            completed.append({"lv_id": item.lv_id, "run_id": run_id,
                              "package_sha256": _sha(package), "review_sha256": _sha(review_path),
                              "status": "COMPLETE", "source": "immutable"})
        except ResumeBridgeError:
            if item.lv_id in required_completed:
                raise
            first_incomplete = item.lv_id
            break
    if first_incomplete is None and len(completed) < len(plan.lvs):
        first_incomplete = plan.lvs[len(completed)].lv_id
    remaining = [item.lv_id for item in plan.lvs if item.lv_id not in {row["lv_id"] for row in completed}]
    payload = {"schema_version": "orchestration.production-resume-bridge.v1",
               "project_id": plan.project_id, "gate_id": gate_id, "plan_sha256": plan_sha256,
               "completed": completed, "remaining": remaining,
               "first_incomplete_lv": first_incomplete, "source_immutable": True}
    payload["bridge_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


def validate_resume_bridge(bridge: Mapping[str, Any], *, project_id: str, gate_id: str,
                           plan_sha256: str) -> dict[str, Any]:
    if bridge.get("schema_version") != "orchestration.production-resume-bridge.v1":
        raise ResumeBridgeError("resume bridge schema mismatch")
    if bridge.get("project_id") != project_id or bridge.get("gate_id") != gate_id or bridge.get("plan_sha256") != plan_sha256:
        raise ResumeBridgeError("resume bridge binding mismatch")
    unsigned = {k: v for k, v in bridge.items() if k != "bridge_sha256"}
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bridge.get("bridge_sha256") != digest or bridge.get("source_immutable") is not True:
        raise ResumeBridgeError("resume bridge digest or immutability mismatch")
    return dict(bridge)

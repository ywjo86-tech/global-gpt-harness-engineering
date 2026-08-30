"""Read-only bridge for promoting immutable LV exits into a v2 Gate resume."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .gate_orchestrator import GatePlan, load_gate_plan
from .contract_adapter import load_project_mapping
from .recovery_contract import is_completion_eligible
from .production_completion import verify_product_completion, ProductCompletionError


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


def _sealed_sha(path: Path) -> str:
    candidates = [path.with_suffix(".sha256"), path.with_suffix(path.suffix + ".sha256")]
    sidecar = next((item for item in candidates if item.is_file()), candidates[0])
    if not sidecar.is_file() or sidecar.is_symlink():
        raise ResumeBridgeError(f"sealed hash sidecar is missing: {path.name}")
    expected = sidecar.read_text(encoding="ascii").strip()
    actual = _sha(path)
    if expected != actual:
        raise ResumeBridgeError(f"sealed hash sidecar mismatch: {path.name}")
    return actual


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

def _recovery_completion(project_root: Path, harness_root: Path, plan: GatePlan,
                         item: Any, run_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Read-only discovery of recovery attempts; never manufactures evidence."""
    rejected: list[dict[str, Any]] = []
    run_root = harness_root / "_workspace" / "orchestration-runs" / run_id
    for attempt_root in sorted(run_root.glob("attempt-[0-9][0-9]"), reverse=True):
        try: attempt = int(attempt_root.name.split("-")[1])
        except (IndexError, ValueError): continue
        required = {"package.json":"package_sha256","consumption.json":"consumption_sha256",
                    "lv.exit.json":"lv_exit_sha256","handoff.json":"handoff_sha256"}
        values: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        for name, hash_key in required.items():
            try: value = _load(attempt_root / name)
            except ResumeBridgeError: reasons.append(f"MISSING_{name.upper().replace('.', '_')}"); continue
            claimed = value.get(hash_key); unsigned = {k:v for k,v in value.items() if k != hash_key}
            actual = hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            if claimed != actual: reasons.append(f"INVALID_{hash_key.upper()}")
            if value.get("project_id") != plan.project_id or value.get("gate_id") != plan.gate_id or value.get("lv_id") != item.lv_id or value.get("run_id") != run_id or value.get("attempt") != attempt:
                reasons.append("RECOVERY_BINDING_MISMATCH")
            values[name] = value
        product_path = attempt_root / "product-completion.json"
        verdict = None
        if product_path.is_file() and not product_path.is_symlink():
            try:
                evidence = _load(product_path)
                package = values.get("package.json", {})
                contract = {"project_id":plan.project_id,"gate_id":plan.gate_id,"lv_id":item.lv_id,"run_id":run_id,
                            "approval_event_id":package.get("approval_event_id"),"plan_sha256":plan.canonical_plan_sha256,
                            "owned_files":list(item.owned_files),"allow_no_op":False}
                verdict = verify_product_completion(project_root,evidence,contract)
                reasons.extend(verdict["reasons"])
            except (ResumeBridgeError, ProductCompletionError): reasons.append("PRODUCT_COMPLETION_INVALID")
        else: reasons.append("PRODUCT_COMPLETION_EVIDENCE_MISSING")
        reasons = sorted(set(reasons))
        if not reasons and verdict and verdict["completion_eligible"]:
            return {"lv_id":item.lv_id,"run_id":run_id,"attempt":attempt,"status":"COMPLETE","source":"recovery",
                    "product_completion_sha256":_sha(product_path),"handoff_sha256":values["handoff.json"]["handoff_sha256"]}, rejected
        rejected.append({"attempt":attempt,"status":"REJECTED_COMPLETION_UNPROVEN","reasons":reasons,
                         "source_shas":{name:_sha(attempt_root/name) for name in required if (attempt_root/name).is_file()}})
    return None, sorted(rejected,key=lambda x:x["attempt"])


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
    rejections: list[dict[str, Any]] = []
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
            if review.get("hard_stop") is not True or review.get("run_id") != run_id:
                raise ResumeBridgeError("review evidence hard-stop/run binding is invalid")
            package_sha = _sealed_sha(package)
            if review.get("package_manifest_sha256") != package_sha:
                raise ResumeBridgeError("review/package lineage mismatch")
            review_sha = _sealed_sha(review_path)
            worker = review_path.parent / "worker.result.json"
            if not worker.is_file():
                worker = review_path.parent.parent / "worker.result.json"
            worker_payload = _load(worker)
            # Historical immutable exits may predate the recovery binding
            # fields.  Only explicitly rejected artifacts are excluded here;
            # the partial run without PASS review remains incomplete naturally.
            if not is_completion_eligible(worker_payload):
                raise ResumeBridgeError("worker evidence is completion-ineligible")
            worker_sha = _sealed_sha(worker)
            if review.get("worker_result_sha256") != worker_sha:
                raise ResumeBridgeError("review/worker lineage mismatch")
            completed.append({"lv_id": item.lv_id, "run_id": run_id,
                              "package_sha256": package_sha, "review_sha256": review_sha,
                              "worker_sha256": worker_sha,
                              "status": "COMPLETE", "source": "immutable"})
        except ResumeBridgeError:
            recovered, rejected = _recovery_completion(Path(project_root),Path(harness_root),plan,item,run_id)
            rejections.extend({"lv_id":item.lv_id,"run_id":run_id,**row} for row in rejected)
            if recovered is not None:
                completed.append(recovered)
                continue
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
               "first_incomplete_lv": first_incomplete, "rejections":rejections,
               "next_attempt":max([row["attempt"] for row in rejections],default=0)+1 if rejections else None,
               "source_immutable": True}
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

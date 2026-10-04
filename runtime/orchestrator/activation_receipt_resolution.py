"""Read-only resolution of immutable Full Plan activation receipts after job supersession."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .full_plan_activation import FullPlanActivationReceiptV1
from .production_full_plan_entry import load_job


@dataclass(frozen=True, slots=True)
class ActivationJobResolutionV1:
    request_id: str
    run_id: str
    authority_digest: str
    status: str
    resolved_job_path: str
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_receipt(path: Path) -> FullPlanActivationReceiptV1:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("activation receipt is malformed")
    return FullPlanActivationReceiptV1.from_mapping(value)


def _job_matches(path: Path, receipt: FullPlanActivationReceiptV1) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        job = load_job(path)
    except Exception:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(value, dict):
            return False
        job = value
    return (
        str(job.get("run_id") or "") == receipt.run_id
        and str(job.get("authority_core_sha256") or "") == receipt.authority_digest
    )


def resolve_activation_receipt_job(
    state_root: str | Path,
    receipt_path: str | Path,
) -> ActivationJobResolutionV1:
    root = Path(state_root).expanduser().resolve()
    source = Path(receipt_path).expanduser().resolve()
    receipt = _read_receipt(source)
    canonical = Path(receipt.canonical_job_path).expanduser()
    if _job_matches(canonical, receipt):
        return ActivationJobResolutionV1(
            receipt.activation_request_id, receipt.run_id, receipt.authority_digest,
            "DIRECT", str(canonical.resolve()), 1,
        )

    workspace = root / "_workspace"
    candidates: list[Path] = []
    if workspace.is_dir():
        for path in workspace.rglob("superseded-job-*.json"):
            if _job_matches(path, receipt):
                candidates.append(path.resolve())
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return ActivationJobResolutionV1(
            receipt.activation_request_id, receipt.run_id, receipt.authority_digest,
            "ARCHIVED_SUPERSEDED", str(unique[0]), 1,
        )
    return ActivationJobResolutionV1(
        receipt.activation_request_id, receipt.run_id, receipt.authority_digest,
        "UNRESOLVED" if not unique else "AMBIGUOUS", "", len(unique),
    )


def diagnose_activation_receipts(state_root: str | Path) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    receipts = root / "_workspace" / "full-plan-activation-receipts"
    rows: list[dict[str, Any]] = []
    if receipts.is_dir():
        for path in sorted(receipts.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                rows.append(resolve_activation_receipt_job(root, path).to_dict())
            except Exception as exc:
                rows.append({
                    "request_id": path.stem, "status": "INVALID", "resolved_job_path": "",
                    "candidate_count": 0, "error": str(exc),
                })
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "INVALID")
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": "orchestration.activation-receipt-resolution-diagnostic.v1",
        "receipt_count": len(rows),
        "counts": counts,
        "unresolved_count": sum(counts.get(key, 0) for key in ("UNRESOLVED", "AMBIGUOUS", "INVALID")),
        "rows": rows,
    }

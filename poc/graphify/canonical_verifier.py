from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ProviderResult


def verify_provider_result(
    result: ProviderResult,
    *,
    expected_source: str,
    expected_source_ref: str,
    source_root: str | Path,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    expected_path = (root / expected_source).resolve()
    reasons: list[str] = []

    if result.source_ref != expected_source_ref:
        reasons.append("source_ref_mismatch")
    if result.write_performed:
        reasons.append("provider_write_detected")
    if result.freshness_state != "CURRENT":
        reasons.append("stale_or_unknown_result")
    if not expected_path.is_file():
        reasons.append("canonical_source_missing")

    candidate_hit = (
        expected_source in result.source_files
        or expected_source in result.output
    )
    if not candidate_hit:
        reasons.append("expected_source_not_found")
    verified = not reasons
    return {
        "record_type": "CanonicalVerificationResult",
        "provider_id": result.provider_id,
        "scenario_id": result.scenario_id,
        "source_ref": result.source_ref,
        "expected_source_ref": expected_source_ref,
        "expected_source": expected_source,
        "candidate_source_files": list(result.source_files),
        "canonical_source_exists": expected_path.is_file(),
        "candidate_hit": candidate_hit,
        "freshness_state": result.freshness_state,
        "confidence": result.confidence,
        "verified": verified,
        "reasons": reasons,
    }


def verify_graph_manifest(
    manifest_path: str | Path,
    *,
    required_sources: list[str],
) -> dict[str, Any]:
    import json

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    missing = [source for source in required_sources if source not in payload]
    return {
        "record_type": "GraphManifestFreshnessResult",
        "manifest_present": path.is_file(),
        "required_sources": required_sources,
        "missing_sources": missing,
        "freshness_verified": path.is_file() and not missing,
    }

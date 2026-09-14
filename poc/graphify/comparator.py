from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from .canonical_verifier import verify_provider_result
from .contracts import ProviderQueryRequest, ProviderResult


class QueryProvider(Protocol):
    def query(self, request: ProviderQueryRequest) -> ProviderResult: ...


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    query: str
    expected_source: str
    token_budget: int = 1000


def _run_one(
    provider: QueryProvider,
    request: ProviderQueryRequest,
    *,
    expected_source: str,
    source_root: str | Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = provider.query(request)
        verification = verify_provider_result(
            result,
            expected_source=expected_source,
            expected_source_ref=request.source_ref,
            source_root=source_root,
        )
        error = ""
    except Exception as exc:
        result = None
        verification = {"verified": False, "reasons": ["provider_error"]}
        error = f"{type(exc).__name__}:{exc}"
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    output = result.output if result is not None else ""
    return {
        "provider_id": result.provider_id if result is not None else "unknown",
        "scenario_id": request.scenario_id,
        "latency_ms": latency_ms,
        "output_chars": len(output),
        "estimated_tokens": max(0, len(output) // 4),
        "verification": verification,
        "result": result.to_dict() if result is not None else None,
        "error": error,
    }


def run_comparison(
    graphify_provider: QueryProvider,
    baseline_provider: QueryProvider,
    scenarios: Iterable[Scenario],
    *,
    source_ref: str,
    source_root: str | Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    negative_evidence: list[dict[str, Any]] = []
    for scenario in scenarios:
        request = ProviderQueryRequest(
            scenario.scenario_id, scenario.query, source_ref, scenario.token_budget
        )
        for provider in (graphify_provider, baseline_provider):
            row = _run_one(
                provider, request,
                expected_source=scenario.expected_source,
                source_root=source_root,
            )
            rows.append(row)
            if row["error"] or not row["verification"].get("verified", False):
                negative_evidence.append({
                    "scenario_id": scenario.scenario_id,
                    "provider_id": row["provider_id"],
                    "error": row["error"],
                    "reasons": row["verification"].get("reasons", []),
                })
    metrics: dict[str, dict[str, Any]] = {}
    for provider_id in ("graphify", "existing_inspection"):
        provider_rows = [row for row in rows if row["provider_id"] == provider_id]
        completed = [row for row in provider_rows if not row["error"]]
        verified = [row for row in provider_rows if row["verification"].get("verified", False)]
        metrics[provider_id] = {
            "scenario_count": len(provider_rows),
            "completed_count": len(completed),
            "verified_count": len(verified),
            "verified_rate": round(len(verified) / len(provider_rows), 4) if provider_rows else 0.0,
            "average_latency_ms": round(
                sum(row["latency_ms"] for row in provider_rows) / len(provider_rows), 3
            ) if provider_rows else 0.0,
            "estimated_tokens_total": sum(row["estimated_tokens"] for row in provider_rows),
        }
    return {
        "record_type": "ComparativePoCReport",
        "source_ref": source_ref,
        "scenario_count": len({row["scenario_id"] for row in rows}),
        "rows": rows,
        "metrics": metrics,
        "negative_evidence": negative_evidence,
    }


def query_with_fallback(
    graphify_provider: QueryProvider,
    baseline_provider: QueryProvider,
    request: ProviderQueryRequest,
) -> tuple[ProviderResult, dict[str, Any]]:
    try:
        primary = graphify_provider.query(request)
        if primary.freshness_state != "CURRENT" or primary.status != "completed":
            raise RuntimeError("graphify result is stale or incomplete")
        return primary, {"fallback_used": False, "primary_error": ""}
    except Exception as exc:
        fallback = baseline_provider.query(request)
        return fallback, {
            "fallback_used": True,
            "primary_error": f"{type(exc).__name__}:{exc}",
            "fallback_provider": fallback.provider_id,
        }

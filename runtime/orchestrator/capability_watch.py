from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence


WATCH_ACTIONS = frozenset({
    "NO_ACTION",
    "SEARCH",
    "REASSESS",
    "REPLACEMENT_REVIEW",
    "RETIREMENT_REVIEW",
})


@dataclass(frozen=True, slots=True)
class CapabilityWatchDecisionV1:
    scan_due: bool
    actions: tuple[str, ...]
    capability_refs: tuple[str, ...]
    rationale_refs: tuple[str, ...]
    next_eligible_scan_at: str


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("capability watch timestamp is required")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "capability watch timestamp is invalid"
        ) from exc

    if parsed.tzinfo is None:
        raise ValueError(
            "capability watch timestamp must be timezone-aware"
        )

    return parsed


def evaluate_capability_watch(
    *,
    records: Sequence[object],
    capability_gaps: Sequence[str],
    metrics: Sequence[Mapping[str, object]],
    last_scan_at: str,
    now: str,
    scan_interval_seconds: int,
) -> CapabilityWatchDecisionV1:
    """Evaluate bounded recommendations only.

    No network access, install, activation, replacement, drain,
    retirement, thread, loop, scheduler, or executor is owned here.
    """

    if (
        not isinstance(scan_interval_seconds, int)
        or scan_interval_seconds <= 0
    ):
        raise ValueError(
            "scan interval must be a positive integer"
        )

    last_scan = _timestamp(last_scan_at)
    current = _timestamp(now)

    if last_scan > current:
        raise ValueError(
            "last capability scan cannot be in the future"
        )

    next_scan = last_scan + timedelta(
        seconds=scan_interval_seconds
    )

    scan_due = current >= next_scan

    if not scan_due:
        return CapabilityWatchDecisionV1(
            scan_due=False,
            actions=("NO_ACTION",),
            capability_refs=(),
            rationale_refs=(),
            next_eligible_scan_at=next_scan.isoformat(),
        )

    contract_ids: set[str] = set()

    for record in records:
        contract = getattr(record, "contract", None)
        contract_id = getattr(
            contract,
            "contract_id",
            "",
        )

        if not isinstance(contract_id, str) or not contract_id:
            raise ValueError(
                "capability watch record identity is malformed"
            )

        contract_ids.add(contract_id)

    normalized_gaps: list[str] = []

    for gap in capability_gaps:
        if not isinstance(gap, str) or not gap:
            raise ValueError(
                "capability gap identity is malformed"
            )

        if gap not in normalized_gaps:
            normalized_gaps.append(gap)

    actions: list[str] = []
    capability_refs: list[str] = []
    rationale_refs: list[str] = []

    if normalized_gaps:
        actions.append("SEARCH")
        capability_refs.extend(
            f"gap:{gap}"
            for gap in normalized_gaps
        )
        rationale_refs.append(
            "CAPABILITY_GAP_PRESENT"
        )

    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise ValueError(
                "capability watch metric is malformed"
            )

        contract_id = metric.get("contract_id")

        if (
            not isinstance(contract_id, str)
            or contract_id not in contract_ids
        ):
            raise ValueError(
                "capability watch metric contract is unknown"
            )

        health = metric.get("health")

        if not isinstance(health, str) or not health:
            raise ValueError(
                "capability watch metric health is malformed"
            )

        overlap = metric.get(
            "overlap_candidate_ref",
            "",
        )

        if overlap and not isinstance(overlap, str):
            raise ValueError(
                "capability overlap reference is malformed"
            )

        if health == "DEGRADED":
            if "REASSESS" not in actions:
                actions.append("REASSESS")

            if contract_id not in capability_refs:
                capability_refs.append(contract_id)

            rationale_refs.append(
                f"{contract_id}:DEGRADED"
            )

            if overlap:
                if "REPLACEMENT_REVIEW" not in actions:
                    actions.append(
                        "REPLACEMENT_REVIEW"
                    )

                rationale_refs.append(
                    f"{contract_id}:OVERLAP:{overlap}"
                )

    if not actions:
        actions.append("NO_ACTION")

    if any(action not in WATCH_ACTIONS for action in actions):
        raise ValueError(
            "unsupported capability watch action"
        )

    return CapabilityWatchDecisionV1(
        scan_due=True,
        actions=tuple(actions),
        capability_refs=tuple(capability_refs),
        rationale_refs=tuple(rationale_refs),
        next_eligible_scan_at=(
            current
            + timedelta(seconds=scan_interval_seconds)
        ).isoformat(),
    )

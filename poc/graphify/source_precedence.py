from __future__ import annotations

from typing import Any, Iterable


def verify_source_precedence(
    *,
    current_repository_fact: Any,
    approved_baseline_fact: Any,
    lower_priority_fixtures: Iterable[Any],
) -> dict[str, Any]:
    fixtures = list(lower_priority_fixtures)
    if current_repository_fact is not None:
        authoritative_source = "CURRENT_REPOSITORY"
        authoritative_value = current_repository_fact
    elif approved_baseline_fact is not None:
        authoritative_source = "APPROVED_BASELINE"
        authoritative_value = approved_baseline_fact
    else:
        authoritative_source = "NONE"
        authoritative_value = None

    conflicts = [value for value in fixtures if value != authoritative_value]
    verified = authoritative_source != "NONE"
    return {
        "record_type": "SourcePrecedenceResult",
        "authoritative_source": authoritative_source,
        "authoritative_value": authoritative_value,
        "lower_priority_fixtures": fixtures,
        "conflicting_lower_priority_values": conflicts,
        "lower_priority_override_applied": False,
        "verified": verified,
    }

"""Read-only Operator turn exit classification for governed orchestration.

The guard never owns continuation, approval, routing, provider selection, or
effects.  It only decides whether a user-facing response may end the current
Operator turn from facts already produced by Full Plan and R2 interaction
policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .production_attention import AttentionOutbox
from .user_interaction_policy import (
    IMMEDIATE_DECISION,
    UserDecisionAssessment,
    evaluate_attention_delivery,
)

CONTINUE_EXECUTION = "CONTINUE_EXECUTION"
REQUEST_USER_DECISION = "REQUEST_USER_DECISION"
NOTIFY_STALLED = "NOTIFY_STALLED"
REPORT_TERMINAL_STOP = "REPORT_TERMINAL_STOP"
REPORT_BOUNDED_CHECKPOINT = "REPORT_BOUNDED_CHECKPOINT"
ALLOW_COMPLETION_RESPONSE = "ALLOW_COMPLETION_RESPONSE"

_VALID_STATES = frozenset({
    "READY", "DISPATCHED", "RUNNING", "VERIFYING", "RECOVERING",
    "WAITING_APPROVAL", "WAITING_PROVIDER", "WAITING_RESOURCE",
    "BLOCKED", "FAILED", "COMPLETED", "CANCELLED",
})
_INACTIVE_QUEUE_STATES = frozenset({"COMPLETED", "BLOCKED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class OperatorExitAssessment:
    disposition: str
    allow_final_response: bool
    successful_completion: bool
    reason: str
    pending_obligations: tuple[str, ...] = ()
    control_authority: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _continue(reason: str, pending: Sequence[str] = ()) -> OperatorExitAssessment:
    return OperatorExitAssessment(
        CONTINUE_EXECUTION, False, False, reason, tuple(sorted(set(pending))), "NONE"
    )


def _valid_state(state: Mapping[str, Any]) -> bool:
    if not isinstance(state, Mapping):
        return False
    required = {"project_id", "run_id", "state", "gates", "completed_gates", "queue", "terminal_reason"}
    if not required.issubset(state):
        return False
    if not isinstance(state.get("project_id"), str) or not state["project_id"]:
        return False
    if not isinstance(state.get("run_id"), str) or not state["run_id"]:
        return False
    if str(state.get("state")) not in _VALID_STATES:
        return False
    gates = state.get("gates")
    completed = state.get("completed_gates")
    queue = state.get("queue")
    if not isinstance(gates, list) or not gates or any(not isinstance(x, str) or not x for x in gates):
        return False
    if len(gates) != len(set(gates)) or not isinstance(completed, list):
        return False
    if any(item not in gates for item in completed) or len(completed) != len(set(completed)):
        return False
    if not isinstance(queue, list) or any(not isinstance(item, Mapping) for item in queue):
        return False
    return True


def _continuation_incomplete(states: Sequence[Mapping[str, Any] | object]) -> bool:
    for item in states:
        if isinstance(item, Mapping):
            value = item.get("execution_state")
        else:
            value = getattr(item, "execution_state", None)
        if str(value or "") != "COMPLETED":
            return True
    return False


def _completion_facts_hold(state: Mapping[str, Any]) -> bool:
    gates = list(state["gates"])
    completed = list(state["completed_gates"])
    queue = list(state["queue"])
    return (
        state.get("state") == "COMPLETED"
        and state.get("terminal_reason") == "ALL_GATES_COMPLETED"
        and state.get("current_gate") is None
        and completed == gates
        and bool(queue)
        and all(str(item.get("status") or "") == "COMPLETED" for item in queue)
    )


def assess_operator_turn_exit(
    full_plan_state: Mapping[str, Any], *,
    now: datetime,
    attention_events: Sequence[Mapping[str, Any]] = (),
    completion_obligations: Mapping[str, bool] | None = None,
    continuation_states: Sequence[Mapping[str, Any] | object] = (),
    user_decision: UserDecisionAssessment | None = None,
    recoverable_continuation: bool = False,
    bounded_turn_yield: bool = False,
    durable_turn_checkpoint: bool = False,
    attention_threshold_seconds: int = 300,
) -> OperatorExitAssessment:
    """Classify whether the Operator may end the user-facing turn.

    This function is deliberately effect-free.  `CONTINUE_EXECUTION` means an
    existing orchestration authority must keep working; it does not perform
    that continuation itself.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not _valid_state(full_plan_state):
        return _continue("Full Plan state is malformed or incomplete")

    state_name = str(full_plan_state["state"])
    if user_decision is not None and user_decision.required:
        return OperatorExitAssessment(
            REQUEST_USER_DECISION, True, False, user_decision.reason, (), "NONE"
        )
    if state_name == "WAITING_APPROVAL":
        return OperatorExitAssessment(
            REQUEST_USER_DECISION, True, False, "Full Plan is waiting for user approval", (), "NONE"
        )
    if state_name == "CANCELLED":
        return OperatorExitAssessment(
            REPORT_TERMINAL_STOP, True, False,
            str(full_plan_state.get("terminal_reason") or "Full Plan was cancelled"), (), "NONE"
        )

    for event in attention_events:
        try:
            attention = evaluate_attention_delivery(
                event, full_plan_state, now=now,
                threshold_seconds=attention_threshold_seconds,
            )
        except (TypeError, ValueError):
            continue
        if not attention.eligible:
            continue
        if attention.delivery_class == IMMEDIATE_DECISION:
            return OperatorExitAssessment(
                REQUEST_USER_DECISION, True, False, attention.reason, (), "NONE"
            )
        return OperatorExitAssessment(
            NOTIFY_STALLED, True, False, attention.reason, (), "NONE"
        )

    if bounded_turn_yield:
        if not durable_turn_checkpoint:
            return _continue("bounded turn yield requires a durable continuation checkpoint")
        return OperatorExitAssessment(
            REPORT_BOUNDED_CHECKPOINT, True, False,
            "bounded turn soft budget reached at a durable continuation checkpoint", (), "NONE"
        )

    if recoverable_continuation:
        return _continue("verified autonomous continuation remains available")

    if _continuation_incomplete(continuation_states):
        pending = tuple(
            str(name) for name, value in (completion_obligations or {}).items() if value is not True
        )
        return _continue("operator continuation checkpoint remains incomplete", pending)

    if state_name == "COMPLETED":
        if not _completion_facts_hold(full_plan_state):
            return _continue("Full Plan completion facts are inconsistent")
        if completion_obligations is None:
            return _continue("completion obligations were not supplied")
        invalid = [name for name, value in completion_obligations.items() if not isinstance(name, str) or not name or not isinstance(value, bool)]
        if invalid:
            return _continue("completion obligations are malformed", [str(x) for x in invalid])
        pending = [name for name, value in completion_obligations.items() if value is not True]
        if pending:
            return _continue("completion obligations remain open", pending)
        return OperatorExitAssessment(
            ALLOW_COMPLETION_RESPONSE, True, True,
            "Full Plan and caller completion obligations are complete", (), "NONE"
        )

    return _continue(f"Full Plan state {state_name} is not successful completion")


def assess_run_base(
    run_base: str | Path, *, now: datetime,
    completion_obligations: Mapping[str, bool] | None = None,
    continuation_states: Sequence[Mapping[str, Any] | object] = (),
    user_decision: UserDecisionAssessment | None = None,
    recoverable_continuation: bool = False,
    bounded_turn_yield: bool = False,
    durable_turn_checkpoint: bool = False,
    attention_threshold_seconds: int = 300,
) -> OperatorExitAssessment:
    """Read persisted Full Plan state/attention and assess turn exit without mutation."""
    base = Path(run_base).resolve()
    state_path = base / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        state = {}
    if isinstance(state, Mapping):
        supplied_hash = str(state.get("state_sha256") or "")
        unsigned = {key: value for key, value in state.items() if key != "state_sha256"}
        calculated_hash = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if supplied_hash != calculated_hash:
            state = {}
    events: list[Mapping[str, Any]] = []
    if isinstance(state, Mapping) and state.get("project_id") and state.get("run_id"):
        try:
            events = AttentionOutbox(
                base, project_id=str(state["project_id"]), run_id=str(state["run_id"])
            ).pending()
        except Exception:
            events = []
    return assess_operator_turn_exit(
        state if isinstance(state, Mapping) else {}, now=now,
        attention_events=events, completion_obligations=completion_obligations,
        continuation_states=continuation_states, user_decision=user_decision,
        recoverable_continuation=recoverable_continuation,
        bounded_turn_yield=bounded_turn_yield, durable_turn_checkpoint=durable_turn_checkpoint,
        attention_threshold_seconds=attention_threshold_seconds,
    )


def _parse_obligations(values: Sequence[str]) -> Mapping[str, bool] | None:
    if not values:
        return None
    result: dict[str, bool] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError("obligation must be NAME=true|false")
        name, value = raw.split("=", 1)
        name = name.strip(); value = value.strip().lower()
        if not name or value not in {"true", "false"}:
            raise ValueError("obligation must be NAME=true|false")
        result[name] = value == "true"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Operator turn exit guard")
    parser.add_argument("--run-base", required=True)
    parser.add_argument("--obligation", action="append", default=[])
    parser.add_argument("--attention-threshold-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        obligations = _parse_obligations(args.obligation)
        assessment = assess_run_base(
            args.run_base, now=datetime.now(timezone.utc),
            completion_obligations=obligations,
            attention_threshold_seconds=args.attention_threshold_seconds,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(assessment.to_dict(), ensure_ascii=False))
    if assessment.disposition in {ALLOW_COMPLETION_RESPONSE, REPORT_TERMINAL_STOP}:
        return 0
    if assessment.disposition == REQUEST_USER_DECISION:
        return 4
    if assessment.disposition == NOTIFY_STALLED:
        return 5
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Lifecycle V2 Full Plan supervisor compatibility seam.

Only V2 runs use this subclass. It preserves V2-specific wait reasons without
changing the stable DurableFullPlanSupervisor used by legacy in-flight runs.
It creates no approval, execution, provider, completion, or effect authority.
"""
from __future__ import annotations

from typing import Any

from .diagnostic_context_bridge import record_failure_diagnostics
from .production_full_plan_runner import DurableFullPlanSupervisor, _failure_class


V2_DISPATCH_ACK_WAIT = "OPERATOR_DISPATCH_ACK_PENDING"


class LifecycleV2FullPlanSupervisor(DurableFullPlanSupervisor):
    """Additive V2 wait taxonomy while preserving legacy supervisor behavior."""

    def _handle_failure(
        self,
        state: dict[str, Any],
        item: dict[str, Any],
        reason: str,
        *,
        wait_state: str | None = None,
    ) -> dict[str, Any]:
        if wait_state != "WAITING_RESOURCE" or reason != V2_DISPATCH_ACK_WAIT:
            return super()._handle_failure(state, item, reason, wait_state=wait_state)

        item["last_error"] = reason
        state["last_error"] = reason
        state["lease"] = None
        failure_class = _failure_class(reason)
        try:
            diagnostic_ref = record_failure_diagnostics(
                output_root=self.base / "diagnostics",
                harness_root=self.root,
                project_id=self.project_id,
                run_id=self.run_id,
                gate_id=str(item["gate_id"]),
                reason=reason,
                failure_class=failure_class,
            )
            if diagnostic_ref:
                self._append_line(
                    self.events_path,
                    {
                        "event": "DIAGNOSTIC_RCA_RECORDED",
                        "gate_id": item["gate_id"],
                        "evidence_ref": str(diagnostic_ref),
                    },
                )
        except Exception as exc:
            self._append_line(
                self.events_path,
                {
                    "event": "DIAGNOSTIC_RCA_FAILED",
                    "gate_id": item["gate_id"],
                    "error_type": type(exc).__name__,
                },
            )

        item["status"] = "READY"
        item["resume"] = True
        state["state"] = "WAITING_RESOURCE"
        state["wait_reason"] = reason
        state = self._persist(
            state,
            {
                "event": "WAITING_RESOURCE",
                "gate_id": item["gate_id"],
                "reason": reason,
                "wait_reason": reason,
                "failure_class": failure_class,
            },
        )
        self._alert("WAITING_RESOURCE", state, gate_id=item["gate_id"], reason=reason)
        return state

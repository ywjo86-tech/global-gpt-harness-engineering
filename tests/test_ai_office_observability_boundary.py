from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path

from runtime.mprf.observability import EVENT_SCHEMA_V1, ProviderRuntimeEventV1
from runtime.orchestrator.observability_source_adapters import (
    ObservabilitySourceAdapterError, action_runtime_observation_from_record,
    provider_runtime_observation_from_event,
)
from runtime.orchestrator.public_observability_contract import (
    CORRELATED_OBSERVATION_SCHEMA_V1, CorrelatedObservationV1,
    PublicObservabilityContractError,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class AIOfficeObservabilityBoundaryTest(unittest.TestCase):
    def action_event(self):
        return {"schema_version":"gch.full-mcp.execution-event.v1", "operation_request_id":"op-1",
                "correlation_id":"corr", "operation":"git-stage", "state":"AUTHORIZED", "sequence":2,
                "occurred_at_utc":"2026-09-18T00:00:00.000Z", "result_digest":None,
                "effect_id":None, "error_code":None,
                "audit_ref":"_workspace/full-mcp/run/events/execution-events.jsonl#op-1:2"}

    def provider_event(self):
        return ProviderRuntimeEventV1(
            EVENT_SCHEMA_V1, "proj", "run", "task", "task-exec", "corr", "op-1",
            "nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b", "HEALTH", 3,
            "2026-09-18T00:00:01.000Z", {"eligible": True},
        )

    def test_007_public_projection_contains_refs_not_raw_source_payload(self) -> None:
        action = action_runtime_observation_from_record(
            self.action_event(), project_id="proj", project_run_id="run", task_execution_id="task-exec",
            source_ref="_workspace/full-mcp/run/events/execution-events.jsonl#op-1:2",
        )
        self.assertEqual("FULL_MCP_ACTION_RUNTIME", action.source_domain)
        self.assertEqual(64, len(action.event_digest))
        serialized = action.to_dict()
        for forbidden in ("arguments", "stdout", "stderr", "authorization", "provider_id", "model_ref"):
            self.assertNotIn(forbidden, serialized)

    def test_008_dual_domains_correlate_without_truth_merge(self) -> None:
        action = action_runtime_observation_from_record(
            self.action_event(), project_id="proj", project_run_id="run", task_execution_id="task-exec",
            source_ref="_workspace/full-mcp/run/events/execution-events.jsonl#op-1:2",
        )
        provider = provider_runtime_observation_from_event(
            self.provider_event(), source_ref="_workspace/mprf/run/events/provider-runtime-events.jsonl#3")
        correlated = CorrelatedObservationV1(
            CORRELATED_OBSERVATION_SCHEMA_V1, "proj", "run", "task-exec", "corr", "op-1",
            (action,), (provider,),
        )
        self.assertEqual("FULL_MCP_ACTION_RUNTIME", correlated.action_observations[0].source_domain)
        self.assertEqual("MPRF_PROVIDER_RUNTIME", correlated.provider_observations[0].source_domain)
        self.assertNotEqual(action.event_digest, provider.event_digest)
        self.assertEqual(64, len(correlated.correlation_digest))

    def test_008_identity_mismatch_fails_closed(self) -> None:
        action = action_runtime_observation_from_record(
            self.action_event(), project_id="proj", project_run_id="run", task_execution_id="task-exec",
            source_ref="action-ref")
        event = self.provider_event()
        other = ProviderRuntimeEventV1(
            EVENT_SCHEMA_V1, event.project_id, event.project_run_id, event.task_id, "different-task-exec",
            event.correlation_id, event.operation_request_id, event.provider_id, event.model_ref,
            event.event_type, event.sequence, event.occurred_at_utc, event.facts)
        provider = provider_runtime_observation_from_event(other, source_ref="provider-ref")
        with self.assertRaises(PublicObservabilityContractError):
            CorrelatedObservationV1(CORRELATED_OBSERVATION_SCHEMA_V1, "proj", "run", "task-exec",
                                    "corr", "op-1", (action,), (provider,))

    def test_009_result_digest_is_verified_and_adapters_have_no_store_mutators(self) -> None:
        body = {"schema_version":"gch.full-mcp.result-index.v1", "operation_request_id":"op-1",
                "correlation_id":"corr", "operation":"git-stage", "state":"COMPLETED",
                "started_at":"a", "ended_at":"b", "audit_ref":"audit-ref", "effect_id":"effect-ref",
                "error_code":None, "exit_code":0, "security_block":False, "restore_equivalent":False}
        record = {**body, "result_digest": digest(body)}
        projected = action_runtime_observation_from_record(
            record, project_id="proj", project_run_id="run", task_execution_id="task-exec", source_ref="result-ref")
        self.assertEqual(record["result_digest"], projected.event_digest)
        bad = dict(record); bad["result_digest"] = "0" * 64
        with self.assertRaises(ObservabilitySourceAdapterError):
            action_runtime_observation_from_record(
                bad, project_id="proj", project_run_id="run", task_execution_id="task-exec", source_ref="result-ref")
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "runtime/orchestrator/observability_source_adapters.py").read_text(encoding="utf-8"))
        defs = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertFalse(defs & {"append", "write", "emit", "seal_result"})


if __name__ == "__main__": unittest.main()

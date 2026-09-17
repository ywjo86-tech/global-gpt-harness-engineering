from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.mprf.contracts import (
    ADMISSION_ADMITTED, ADMISSION_RECORD_SCHEMA_V1, MODEL_RECORD_SCHEMA_V1,
    NVIDIA_PROVIDER, PROVIDER_RECORD_SCHEMA_V1, AdmissionRecordV1, ModelRecordV1, ProviderRecordV1,
)
from runtime.mprf.observability import (
    AUTHORITY_SCOPE, CORRELATION_SCHEMA_V1, EVENT_SCHEMA_V1, SOURCE_DOMAIN,
    MPRFObservabilityError, ProviderRuntimeEventStoreV1, correlation_projection,
)
from runtime.mprf.registry import REGISTRY_SCHEMA_V1, ProviderModelRegistryV1
from runtime.mprf.runtime import MPRFRuntimeV1, RUNTIME_SCHEMA_V1


def registry() -> ProviderModelRegistryV1:
    return ProviderModelRegistryV1(
        REGISTRY_SCHEMA_V1, "registry-1", 1,
        (
            ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, "nvidia", 1),
            ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, "codex", 1),
        ),
        (ModelRecordV1(MODEL_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, "nvidia/model-a", 1),),
        (AdmissionRecordV1(ADMISSION_RECORD_SCHEMA_V1, "admit-n", NVIDIA_PROVIDER, "nvidia/model-a", 1, ADMISSION_ADMITTED),),
    )


class ProviderRuntimeObservabilityTests(unittest.TestCase):
    def test_provider_runtime_events_are_append_only_correlated_and_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            store = ProviderRuntimeEventStoreV1(root, "run-1")
            first = store.append(
                project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a",
                event_type="HEALTH", facts={"health_state": "HEALTHY", "latency_bucket": "LT_1S"},
            )
            second = store.append(
                project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a",
                event_type="RETRY", facts={"retry_ordinal": 1, "failure_class": "NETWORK_FAILURE"},
            )
            events = store.read_all()
            self.assertEqual([e.sequence for e in events], [1, 2])
            self.assertEqual([e.event_digest for e in events], [first.event_digest, second.event_digest])
            self.assertEqual(store.events_path.stat().st_mode & 0o777, 0o600)
            raw = store.events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw), 2)
            self.assertEqual(json.loads(raw[0])["schema_version"], EVENT_SCHEMA_V1)

    def test_closed_event_taxonomy_and_secret_action_truth_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = ProviderRuntimeEventStoreV1(Path(td).resolve(), "run-1")
            base = dict(project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                        operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a")
            with self.assertRaisesRegex(MPRFObservabilityError, "closed provider-runtime taxonomy"):
                store.append(**base, event_type="ACTION_RESULT", facts={})
            for forbidden in ("effect_id", "result_digest", "stdout", "token", "raw_action_output"):
                with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                    MPRFObservabilityError, "action truth or secret material"
                ):
                    store.append(**base, event_type="HEALTH", facts={forbidden: "x"})

    def test_correlation_projection_does_not_transfer_action_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = ProviderRuntimeEventStoreV1(Path(td).resolve(), "run-1")
            event = store.append(
                project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a",
                event_type="FAILOVER", facts={"failure_class": "MODEL_FAILURE", "reason_code": "ROUTER_REROUTE"},
            )
            projection = correlation_projection(event)
            self.assertEqual(projection["schema_version"], CORRELATION_SCHEMA_V1)
            self.assertEqual(projection["source_domain"], SOURCE_DOMAIN)
            self.assertEqual(projection["authority_scope"], AUTHORITY_SCOPE)
            self.assertEqual(set(projection), {
                "schema_version", "project_id", "project_run_id", "task_id", "task_execution_id",
                "correlation_id", "operation_request_id", "source_domain", "authority_scope",
            })
            self.assertFalse(any(key in projection for key in ("effect_id", "result_digest", "action_state")))

    def test_runtime_records_provider_facts_without_full_mcp_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = ProviderRuntimeEventStoreV1(Path(td).resolve(), "run-1")
            runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry(), observability_store=store)
            event = runtime.record_provider_runtime_event(
                project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a",
                event_type="QUOTA", facts={"quota_state": "AVAILABLE", "quota_bucket": "NORMAL"},
            )
            self.assertEqual(event.event_type, "QUOTA")
            source = (Path(__file__).parents[2] / "runtime" / "mprf" / "observability.py").read_text(encoding="utf-8")
            runtime_source = (Path(__file__).parents[2] / "runtime" / "mprf" / "runtime.py").read_text(encoding="utf-8")
            self.assertNotIn("runtime.full_mcp", source)
            self.assertNotIn("runtime.full_mcp", runtime_source)

    def test_existing_log_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = ProviderRuntimeEventStoreV1(Path(td).resolve(), "run-1")
            store.append(
                project_id="P1", task_id="T1", task_execution_id="E1", correlation_id="C1",
                operation_request_id="OP1", provider_id="nvidia", model_ref="nvidia/model-a",
                event_type="MODEL", facts={"status": "ACTIVE"},
            )
            payload = json.loads(store.events_path.read_text(encoding="utf-8"))
            payload["facts"]["status"] = "TAMPERED"
            store.events_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MPRFObservabilityError, "malformed"):
                store.read_all()


if __name__ == "__main__":
    unittest.main()

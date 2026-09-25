from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import unittest

from runtime.orchestrator.external_advisory_contract import (
    REQUEST_SCHEMA_V1,
    ExternalCapabilityError,
    ExternalCapabilityRequestV1,
    ExternalCapabilityResultV1,
    canonical_external_digest,
)
from runtime.orchestrator.external_advisory_shadow import (
    ADVISORY_SHADOW_SCHEMA_V1,
    AdvisoryShadowError,
    AdvisoryShadowRecordV1,
    record_shadow_advisory,
)


class ExternalAdvisoryShadowTest(unittest.TestCase):
    def request(self, **overrides) -> ExternalCapabilityRequestV1:
        values = {
            "schema_version": REQUEST_SCHEMA_V1,
            "project_id": "PROJECT-1",
            "project_run_id": "RUN-1",
            "task_id": "TASK-1",
            "task_execution_id": "EXEC-1",
            "correlation_id": "CORR-1",
            "operation_request_id": "OP-1",
            "capability_id": "external.jev.typed_judgment.v1",
            "capability_version": "typesafe-api-0.2.0",
            "schema_digest": "sha256:" + "a" * 64,
            "input_set_digest": "sha256:" + "b" * 64,
            "source_snapshot_digest": "sha256:" + "c" * 64,
            "capability_admission_ref": "admission:shadow",
            "policy_ref": "policy:shadow-only",
            "egress_policy_ref": "egress:test",
            "budget_ref": "budget:test",
            "deadline_ms": 2000,
            "attempt": 1,
            "payload_digest": "sha256:" + "d" * 64,
            "provider_decision_ref": "e" * 64,
            "provider_id": "jev",
            "model_id": "typesafe/system-one",
            "route_ref": "route:jev:test",
        }
        values.update(overrides)
        return ExternalCapabilityRequestV1(**values)

    def result(self, request: ExternalCapabilityRequestV1, *, error=None):
        return ExternalCapabilityResultV1.from_external_payload(
            request=request,
            external_payload={} if error else {"choice": "A", "score": 0.9},
            evidence_ref="evidence:shadow:1",
            actual_provider_id=request.provider_id,
            actual_model_id=request.model_id,
            actual_route_ref=request.route_ref,
            confidence=None if error else 0.9,
            usage=None if error else {"requests": 1},
            latency_ms=17,
            error=error,
        )

    def baseline(self):
        return {
            "decision_id": "CANONICAL-1",
            "provider_ref": "canonical-provider",
            "model_ref": "canonical/model",
            "policy": {"approval": "UNCHANGED"},
        }

    def test_shadow_record_binds_baseline_and_advisory_digests_with_zero_delta(self) -> None:
        request = self.request()
        result = self.result(request)
        baseline = self.baseline()
        record = record_shadow_advisory(
            baseline_canonical_decision=baseline,
            request=request,
            result=result,
        )
        self.assertEqual(record.schema_version, ADVISORY_SHADOW_SCHEMA_V1)
        self.assertEqual(record.baseline_canonical_decision_digest, canonical_external_digest(baseline))
        self.assertEqual(record.advisory_result_digest, result.result_digest)
        self.assertEqual(record.request_digest, request.request_digest)
        self.assertEqual(record.canonical_decision_delta, 0)
        self.assertEqual(record.status, "RECORDED")

    def test_record_schema_has_no_control_or_mutation_fields(self) -> None:
        names = {field.name for field in fields(AdvisoryShadowRecordV1)}
        forbidden = {
            "selected_provider", "override", "approval", "authorization", "action",
            "completion", "completion_proof", "mutation_callback", "apply_callback",
        }
        self.assertTrue(forbidden.isdisjoint(names))

    def test_supplied_canonical_decision_is_not_mutated(self) -> None:
        request = self.request()
        result = self.result(request)
        baseline = self.baseline()
        before = deepcopy(baseline)
        record_shadow_advisory(
            baseline_canonical_decision=baseline,
            request=request,
            result=result,
        )
        self.assertEqual(baseline, before)

    def test_stale_result_is_rejected(self) -> None:
        request = self.request()
        result = self.result(request)
        changed = self.request(input_set_digest="sha256:" + "f" * 64)
        with self.assertRaises(AdvisoryShadowError) as caught:
            record_shadow_advisory(
                baseline_canonical_decision=self.baseline(),
                request=changed,
                result=result,
            )
        self.assertEqual(caught.exception.code, "CAPABILITY_EVIDENCE_STALE")

    def test_optional_unavailable_advisory_is_recorded_without_decision_change(self) -> None:
        request = self.request()
        result = self.result(
            request,
            error=ExternalCapabilityError(
                code="CAPABILITY_UNAVAILABLE",
                message="external service unavailable",
                retryable=False,
            ),
        )
        baseline = self.baseline()
        before = deepcopy(baseline)
        record = record_shadow_advisory(
            baseline_canonical_decision=baseline,
            request=request,
            result=result,
        )
        self.assertEqual(record.status, "UNAVAILABLE")
        self.assertEqual(record.error_code, "CAPABILITY_UNAVAILABLE")
        self.assertEqual(record.canonical_decision_delta, 0)
        self.assertEqual(baseline, before)

    def test_shadow_record_stores_only_digest_metadata_not_private_payload_or_result_body(self) -> None:
        request = self.request()
        result = self.result(request)
        record = record_shadow_advisory(
            baseline_canonical_decision=self.baseline(),
            request=request,
            result=result,
        )
        payload = record.to_dict()
        self.assertEqual(payload["payload_digest"], request.payload_digest)
        self.assertEqual(payload["advisory_result_digest"], result.result_digest)
        self.assertNotIn("payload", payload)
        self.assertNotIn("result", payload)
        self.assertNotIn("choice", repr(payload))
        self.assertNotIn("canonical-provider", repr(payload))

    def test_request_result_binding_must_match_exactly(self) -> None:
        request = self.request()
        result = self.result(request)
        changed = self.request(source_snapshot_digest="sha256:" + "0" * 64)
        with self.assertRaises(AdvisoryShadowError) as caught:
            record_shadow_advisory(
                baseline_canonical_decision=self.baseline(),
                request=changed,
                result=result,
            )
        self.assertEqual(caught.exception.code, "CAPABILITY_EVIDENCE_STALE")


if __name__ == "__main__":
    unittest.main()

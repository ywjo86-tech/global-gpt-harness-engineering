from __future__ import annotations

import unittest
from pathlib import Path

from runtime.orchestrator.public_execution_contract import (
    PUBLIC_EXECUTION_REQUEST_SCHEMA_V1, PUBLIC_EXECUTION_RESULT_SCHEMA_V1,
    PublicExecutionContractError, PublicExecutionRequestV1, PublicExecutionResultV1,
    public_execution_request_from_mapping, public_execution_tool_call, project_full_mcp_result,
)
from runtime.mprf.execution_client import PublicExecutionClient, PublicExecutionClientError


class PublicExecutionContractTest(unittest.TestCase):
    def _request(self):
        return PublicExecutionRequestV1(
            schema_version=PUBLIC_EXECUTION_REQUEST_SCHEMA_V1, operation_class="git_stage",
            public_arguments={"paths": ["owned/a.txt"], "publication_policy_digest": "a" * 64}, authorization_ref="AUTH-PUB-1",
            operation_request_id="pub-op-1", correlation_id="corr-pub-1",
            policy_digests=("a" * 64,), expected_effect_semantics="STATE_CHANGING",
        )

    def _result(self, **changes):
        values = dict(
            schema_version=PUBLIC_EXECUTION_RESULT_SCHEMA_V1, operation_request_id="pub-op-1",
            correlation_id="corr-pub-1", status="COMPLETED", result_digest="b" * 64,
            effect_ref="effect-1", reconciliation_state="NOT_REQUIRED", error_code="", audit_ref="audit-1",
        )
        values.update(changes)
        return PublicExecutionResultV1(**values)

    def test_public_dto_roundtrip_and_client_binding(self):
        request = self._request()
        parsed = public_execution_request_from_mapping(request.to_dict())
        self.assertEqual(parsed.request_digest, request.request_digest)
        result = PublicExecutionClient(lambda payload: self._result().to_dict()).execute(request)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.operation_request_id, request.operation_request_id)

    def test_version_negotiation_fails_closed(self):
        payload = self._request().to_dict()
        payload["schema_version"] = "orchestration.public-execution-request.v2"
        with self.assertRaises(PublicExecutionContractError):
            public_execution_request_from_mapping(payload)
        with self.assertRaises(PublicExecutionContractError):
            self._result(schema_version="orchestration.public-execution-result.v2")

    def test_response_binding_mismatch_fails_closed(self):
        request = self._request()
        client = PublicExecutionClient(lambda payload: self._result(correlation_id="different").to_dict())
        with self.assertRaises(PublicExecutionClientError):
            client.execute(request)

    def test_internal_full_mcp_exposure_is_rejected_and_import_negative_space_holds(self):
        with self.assertRaises(PublicExecutionContractError):
            PublicExecutionRequestV1(
                schema_version=PUBLIC_EXECUTION_REQUEST_SCHEMA_V1, operation_class="git_stage",
                public_arguments={"journal_path": "/internal/journal"}, authorization_ref="AUTH-PUB-1",
                operation_request_id="pub-op-2", correlation_id="corr-pub-2", policy_digests=(),
                expected_effect_semantics="STATE_CHANGING",
            )
        repo = Path(__file__).resolve().parents[1]
        client_source = (repo / "runtime/mprf/execution_client.py").read_text(encoding="utf-8")
        public_source = (repo / "runtime/orchestrator/public_execution_contract.py").read_text(encoding="utf-8")
        for forbidden in ("runtime.full_mcp", "ToolEffectJournal", "operation_registry", "receipt_store"):
            self.assertNotIn(forbidden, client_source)
        self.assertNotIn("from runtime.full_mcp", public_source)
        self.assertNotIn("import runtime.full_mcp", public_source)
        self.assertNotIn("provider_router", client_source)

    def test_public_request_projects_to_exact_publication_call_and_result(self):
        request = self._request()
        call = public_execution_tool_call(request)
        self.assertEqual(call["operation"], "git_stage")
        self.assertEqual(call["operation_request_id"], request.operation_request_id)
        raw = {
            "operation_request_id": request.operation_request_id, "correlation_id": request.correlation_id,
            "status": "COMPLETED", "result_digest": "b" * 64, "effect_id": "effect-1",
            "audit_ref": "audit-1", "data": {"reconciliation_state": "NOT_REQUIRED"}, "error": None,
        }
        projected = project_full_mcp_result(request, raw)
        self.assertEqual(projected.status, "COMPLETED")
        self.assertEqual(projected.effect_ref, "effect-1")

    def test_publication_call_requires_policy_digest_inside_public_arguments(self):
        request = PublicExecutionRequestV1(
            schema_version=PUBLIC_EXECUTION_REQUEST_SCHEMA_V1, operation_class="git_stage",
            public_arguments={"paths": ["owned/a.txt"]}, authorization_ref="AUTH-PUB-1",
            operation_request_id="pub-op-x", correlation_id="corr-pub-x",
            policy_digests=("a" * 64,), expected_effect_semantics="STATE_CHANGING",
        )
        with self.assertRaises(PublicExecutionContractError):
            public_execution_tool_call(request)


if __name__ == "__main__":
    unittest.main()

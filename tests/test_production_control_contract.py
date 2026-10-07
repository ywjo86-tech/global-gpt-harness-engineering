import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone

from runtime.orchestrator.production_control_contract import (
    PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
    RETIRE_FULL_PLAN_RUN,
    ProductionControlActionRequestV1,
    ProductionControlContractError,
)
from runtime.orchestrator.remote_operator_service import RemoteOperatorService
from runtime.orchestrator.remote_control_envelope import (
    PRODUCTION_CONTROL_ACTION_KIND,
    REMOTE_CONTROL_ENVELOPE_SCHEMA,
    RemoteControlEnvelopeError,
    RemoteProductionControlAuthorization,
    seal_remote_control_envelope,
    validate_remote_control_envelope,
)

NOW = datetime(2026, 10, 7, 23, 20, tzinfo=timezone.utc)


def request_payload(**changes):
    value = {
        "schema_version": PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
        "request_id": "PC-REQ-1",
        "project_id": "global-gpt-harness",
        "action": RETIRE_FULL_PLAN_RUN,
        "approval_ref": "OCP-FULL-PLAN-TEST-1",
        "activation_id": "ACT-1",
        "plan_digest": "a" * 64,
        "approval_proof_path": "_workspace/full-plan-human-approvals/ACT-1.json",
        "approval_proof_sha256": "b" * 64,
        "expected_state_sha256": "c" * 64,
        "expected_runtime_source_head": "d" * 40,
        "target_runtime_source_head": "e" * 40,
        "target_runtime_manifest_sha256": "f" * 64,
        "idempotency_key": "PC-IDEMP-1",
        "parameters": {
            "run_id": "RUN-1",
            "expected_terminal_reason": "RETRY_BUDGET_EXHAUSTED",
        },
    }
    value.update(changes)
    return value


def envelope_payload(**changes):
    request = ProductionControlActionRequestV1.from_mapping(request_payload())
    value = {
        "schema_version": REMOTE_CONTROL_ENVELOPE_SCHEMA,
        "request_kind": PRODUCTION_CONTROL_ACTION_KIND,
        "message_id": "MSG-PC-1",
        "sequence": 1,
        "issued_at": "2026-10-07T23:19:00+00:00",
        "expires_at": "2026-10-07T23:29:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "PR:1",
            "source_actor_id": "235775273",
            "source_message_id": "5001",
        },
        "payload": request.to_dict(),
        "payload_digest": "",
        "authorization": {
            "production_control_policy_ref": request.approval_ref,
        },
        "envelope_sha256": "",
    }
    value.update(changes)
    return seal_remote_control_envelope(value)


class ProductionControlContractTests(unittest.TestCase):
    def test_exact_action_contract_round_trips(self):
        request = ProductionControlActionRequestV1.from_mapping(request_payload())
        self.assertEqual(request.action, RETIRE_FULL_PLAN_RUN)
        self.assertEqual(len(request.request_digest), 64)

    def test_arbitrary_provider_model_backend_argv_or_path_is_rejected(self):
        for field in ("provider", "model", "backend", "argv", "path"):
            with self.subTest(field=field):
                raw = request_payload()
                raw[field] = "forbidden"
                with self.assertRaises(ProductionControlContractError):
                    ProductionControlActionRequestV1.from_mapping(raw)

        for field in ("provider", "model", "backend", "argv", "path"):
            with self.subTest(parameter=field):
                raw = request_payload()
                raw["parameters"] = dict(raw["parameters"])
                raw["parameters"][field] = "forbidden"
                with self.assertRaises(ProductionControlContractError):
                    ProductionControlActionRequestV1.from_mapping(raw)

    def test_unsafe_approval_proof_path_is_rejected(self):
        for path in ("/tmp/proof.json", "../proof.json", "x/../proof.json", "x\\proof.json"):
            with self.subTest(path=path):
                raw = request_payload(approval_proof_path=path)
                with self.assertRaises(ProductionControlContractError):
                    ProductionControlActionRequestV1.from_mapping(raw)

    def test_remote_envelope_has_distinct_authorization(self):
        envelope = validate_remote_control_envelope(envelope_payload(), now=NOW)
        self.assertEqual(envelope.request_kind, PRODUCTION_CONTROL_ACTION_KIND)
        self.assertIsInstance(envelope.authorization, RemoteProductionControlAuthorization)
        self.assertEqual(
            envelope.authorization.production_control_policy_ref,
            envelope.payload.approval_ref,
        )

    def test_policy_mismatch_and_tamper_fail_closed(self):
        raw = envelope_payload()
        raw["authorization"]["production_control_policy_ref"] = "OTHER-POLICY"
        raw["envelope_sha256"] = hashlib.sha256(
            json.dumps(
                {k: v for k, v in raw.items() if k != "envelope_sha256"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "authorization mismatch"):
            validate_remote_control_envelope(raw, now=NOW)

        raw = envelope_payload()
        raw["payload"]["parameters"]["run_id"] = "RUN-TAMPER"
        with self.assertRaises(RemoteControlEnvelopeError):
            validate_remote_control_envelope(raw, now=NOW)

    def test_expired_request_fails_closed(self):
        with self.assertRaisesRegex(RemoteControlEnvelopeError, "expired"):
            validate_remote_control_envelope(
                envelope_payload(),
                now=datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc),
            )

    def test_public_projection_exposes_only_refs_and_digests_not_authority_payload(self):
        envelope = validate_remote_control_envelope(envelope_payload(), now=NOW)
        projection = RemoteOperatorService._production_control_status_projection(
            envelope,
            "VERIFIED",
            detail={
                "status": "VERIFIED",
                "effect_digest": "1" * 64,
                "evidence_refs": ["effect:1"],
                "evidence_digests": ["2" * 64],
                "approval_ref": "must-not-leak",
                "approval_proof_path": "must-not-leak",
                "proof": {"must": "not-leak"},
            },
        )
        self.assertEqual(projection["status"], "VERIFIED")
        self.assertEqual(projection["effect_digest"], "1" * 64)
        self.assertEqual(projection["evidence_refs"], ["effect:1"])
        self.assertNotIn("approval_ref", projection)
        self.assertNotIn("approval_proof_path", projection)
        self.assertNotIn("proof", projection)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json

import pytest

from runtime.orchestrator.activation_provenance import (
    ActivationProvenanceError,
    record_ocpv2_full_plan_activation_provenance,
    validate_activation_provenance,
)


def _receipt():
    return {
        "activation_request_id": "FP-ACT-1",
        "activation_digest": "a" * 64,
        "result_status": "FULL_PLAN_REGISTERED",
        "canonical_job_path": "/tmp/job.json",
        "authority_digest": "b" * 64,
        "executable_authority_bundle_digest": "c" * 64,
    }


def _record(tmp_path, message_id="msg-1", replay=False):
    return record_ocpv2_full_plan_activation_provenance(
        tmp_path,
        receipt=_receipt(),
        executor_component="OCPV2_RUNTIME_SERVICE",
        control_path="REMOTE_FULL_PLAN_ACTIVATION",
        policy_ref="POLICY-1",
        message_id=message_id,
        runtime_source_head="d" * 40,
        runtime_manifest_sha256="e" * 64,
        replay_existing_receipt=replay,
        recorded_at="2026-10-05T10:00:00+00:00",
    )


def test_records_digest_bound_sidecar_without_mutating_receipt(tmp_path):
    before = dict(_receipt())
    path = _record(tmp_path)
    value = json.loads(path.read_text())
    validate_activation_provenance(value)
    assert _receipt() == before
    assert value["activation_digest"] == "a" * 64
    assert value["runtime_source_head"] == "d" * 40
    assert value["executor_component"] == "OCPV2_RUNTIME_SERVICE"
    assert value["control_path"] == "REMOTE_FULL_PLAN_ACTIVATION"
    assert value["replay_existing_receipt"] is False


def test_same_message_is_idempotent_and_different_message_gets_distinct_event(tmp_path):
    first = _record(tmp_path, "msg-1")
    again = _record(tmp_path, "msg-1", replay=True)
    second = _record(tmp_path, "msg-2", replay=True)
    assert first == again
    assert second != first
    assert len(list(first.parent.glob("*.json"))) == 2


def test_tamper_fails_closed(tmp_path):
    path = _record(tmp_path)
    value = json.loads(path.read_text())
    value["runtime_source_head"] = "f" * 40
    with pytest.raises(ActivationProvenanceError):
        validate_activation_provenance(value)

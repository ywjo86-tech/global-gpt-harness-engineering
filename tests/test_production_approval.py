from __future__ import annotations

import unittest
from datetime import datetime, timezone

from runtime.orchestrator.production_approval import (
    ApprovalBindings,
    ProductionApprovalError,
    calculate_v2_record_hash,
    classify_approval_schema,
    evaluate_production_authorization,
    validate_v2_chain,
    validate_v2_schema,
)


NOW = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
SHA = "a" * 64
HEAD = "b" * 40


def event(**changes):
    value = {
        "schema_version": "orchestration.production-approval.v2",
        "event_id": "APR-G1-20260829T000000Z",
        "event_type": "APPROVED",
        "project_id": "sample-project",
        "gate_id": "GATE-1",
        "plan_sha256": SHA,
        "branch": "main",
        "baseline_head": HEAD,
        "approved_at": "2026-08-28T23:59:00Z",
        "recorded_at": "2026-08-29T00:00:00Z",
        "approval_mode": "GATE_BY_GATE",
        "canonical_lv_scope": ["G1-LV3-1"],
        "owned_file_scope": {"G1-LV3-1": ["app/a.py", "tests/test_a.py"]},
        "completion_conditions_sha256": "c" * 64,
        "predecessor": None,
        "supersedes": None,
        "authorization_source": "USER_OWNER",
        "record_hash": "0" * 64,
    }
    value.update(changes)
    value["record_hash"] = calculate_v2_record_hash(value)
    return value


def bindings(**changes):
    values = dict(
        project_id="sample-project", gate_id="GATE-1", plan_sha256=SHA,
        branch="main", baseline_head=HEAD, approval_mode="GATE_BY_GATE",
        canonical_lv_scope=("G1-LV3-1",),
        owned_file_scope={"G1-LV3-1": ("app/a.py", "tests/test_a.py")},
        completion_conditions_sha256="c" * 64,
    )
    values.update(changes)
    return ApprovalBindings(**values)


class ProductionApprovalSchemaV2Tests(unittest.TestCase):
    def test_valid_v2_is_production_authorization(self):
        approved = evaluate_production_authorization([event()], bindings(), now=NOW)
        self.assertEqual(approved["event_id"], "APR-G1-20260829T000000Z")

    def test_missing_branch_baseline_mode_and_time_are_blocked(self):
        for field in ("branch", "baseline_head", "approval_mode", "approved_at", "recorded_at"):
            value = event(); del value[field]
            with self.subTest(field=field), self.assertRaisesRegex(ProductionApprovalError, "schema mismatch"):
                validate_v2_schema(value, now=NOW)

    def test_wrong_project_gate_plan_branch_and_head_are_blocked(self):
        cases = {
            "project_id": "other", "gate_id": "GATE-2", "plan_sha256": "d" * 64,
            "branch": "feature", "baseline_head": "e" * 40,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ProductionApprovalError, f"{field} binding mismatch"):
                evaluate_production_authorization([event()], bindings(**{field: value}), now=NOW)

    def test_naive_future_and_fixture_timestamp_are_blocked(self):
        for value in ("2026-08-29T00:00:00", "2026-08-29T00:00:01Z", "FIXTURE_NOW"):
            with self.subTest(value=value), self.assertRaises(ProductionApprovalError):
                validate_v2_schema(event(recorded_at=value), now=NOW)

    def test_tampered_hash_is_blocked(self):
        value = event(); value["gate_id"] = "GATE-2"
        with self.assertRaisesRegex(ProductionApprovalError, "record_hash mismatch"):
            validate_v2_schema(value, now=NOW)

    def test_broken_predecessor_supersedes_and_duplicate_are_blocked(self):
        first = event()
        broken = event(event_id="APR-2", predecessor="d" * 64)
        with self.assertRaisesRegex(ProductionApprovalError, "broken predecessor"):
            validate_v2_chain([first, broken], now=NOW)
        correction = event(event_id="APR-2", event_type="CORRECTION", predecessor=first["record_hash"], supersedes="MISSING")
        with self.assertRaisesRegex(ProductionApprovalError, "supersedes"):
            validate_v2_chain([first, correction], now=NOW)
        duplicate = event(predecessor=first["record_hash"])
        with self.assertRaisesRegex(ProductionApprovalError, "duplicate"):
            validate_v2_chain([first, duplicate], now=NOW)

    def test_valid_correction_event(self):
        first = event()
        corrected = event(
            event_id="APR-G1-CORRECTION-1", event_type="CORRECTION",
            predecessor=first["record_hash"], supersedes=first["event_id"],
            recorded_at="2026-08-29T00:00:00Z",
        )
        self.assertEqual(validate_v2_chain([first, corrected], now=NOW)[-1]["event_type"], "CORRECTION")

    def test_v1_is_historical_only(self):
        self.assertEqual(classify_approval_schema({"schema_version": "orchestration.gate-approval.v1"}), "HISTORICAL_READ_ONLY")
        with self.assertRaises(ProductionApprovalError):
            evaluate_production_authorization([{"schema_version": "orchestration.gate-approval.v1"}], bindings(), now=NOW)

    def test_traversal_and_secret_like_material_are_blocked(self):
        with self.assertRaisesRegex(ProductionApprovalError, "owned_file_scope"):
            validate_v2_schema(event(owned_file_scope={"G1-LV3-1": ["../outside.py"]}), now=NOW)
        with self.assertRaisesRegex(ProductionApprovalError, "secret-like"):
            validate_v2_schema(event(authorization_source="token=sk-abcdefghijklmnopqrstuvwxyz"), now=NOW)

    def test_validation_is_deterministic(self):
        value = event()
        first = validate_v2_schema(value, now=NOW)
        second = validate_v2_schema(value, now=NOW)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

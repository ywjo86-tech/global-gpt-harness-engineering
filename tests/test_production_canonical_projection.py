from __future__ import annotations

import hashlib
import unittest

from runtime.orchestrator.completion_contract import TaskEffectPolicy
from runtime.orchestrator.execution_contract import RunBinding
from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.production_canonical_authority import (
    ProductionCanonicalAuthorityError,
    build_worker_authority_extra_context,
    derive_approved_task_from_lv_manifest,
)
from runtime.orchestrator.tool_authorization import (
    DEC007_CONTRACT_IDS,
    DEC007_DECISION_REF,
    activate_contract,
    build_dec007_approved_contracts,
    owned_scope_digest,
)

PROJECT = "wallet-affiliate-collector"
GATE = "G1"
LV = "LV3-5"
RUN = "run-production-projection"
PLAN = "1" * 64
REQ = "2" * 64
OWNED = (
    "app/services/deduplicator.py",
    "tests/test_deduplicator.py",
)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def make_manifest():
    approved = build_dec007_approved_contracts(
        project_id=PROJECT,
        gate_id=GATE,
        lv_id=LV,
        run_id=RUN,
        canonical_plan_sha256=PLAN,
        owned_files=OWNED,
    )
    package_binding = "3" * 64
    active = [
        activate_contract(
            item,
            package_binding_sha256=package_binding,
            authorized_decisions={DEC007_DECISION_REF: "USER_DECISION"},
        ).to_dict()
        for item in approved
    ]
    projection = {
        "decision_ref": DEC007_DECISION_REF,
        "worker_task_id": "TASK-4A-08",
        "active_contract_count": len(active),
        "contract_ids": sorted(item["contract_id"] for item in active),
        "operation_class_ids": sorted(item["operation_class_id"] for item in active),
        "owned_scope_sha256": owned_scope_digest(OWNED),
        "package_binding_sha256": package_binding,
        "requirement_digests": {
            item["operation_class_id"]: item["requirement_digest"]
            for item in active
        },
    }
    return {
        "project_id": PROJECT,
        "gate_id": GATE,
        "lv_id": LV,
        "run_id": RUN,
        "canonical_plan_sha256": PLAN,
        "task": {"purpose": "deduplicator", "execution": "implementation"},
        "owned_files": list(OWNED),
        "completion_checks": [
            "키 안정성·중복 제거 테스트 통과",
            "중복키 규칙 → 키·중복 제거 / 안정성 테스트",
        ],
        "active_tool_authorization_contracts": active,
        "tool_authorization_projection": projection,
        "tool_authorization_projection_sha256": digest(projection),
    }


class _Package:
    def __init__(self):
        self.run_binding = RunBinding(
            project_id=PROJECT,
            gate_id=GATE,
            lv_id=LV,
            run_id=RUN,
            worker_task_id="TASK-4A-08",
            plan_version="DP-5.0-CANDIDATE",
            plan_digest=PLAN,
            requirement_version="RUN-REQUIREMENTS",
            requirement_digest=REQ,
            semantic_version="SC-1.0-FROZEN-LINEAGE",
            semantic_digest="4" * 64,
        )


class _Launch:
    def __init__(self):
        self.package = _Package()
        self.gateway_authority_binding = {"worker_task_id": "TASK-4A-08"}
        self.gateway_authority_binding_digest = "5" * 64


class ProductionCanonicalProjectionTests(unittest.TestCase):
    def test_derives_task_only_from_sealed_dec007_and_lv_manifest(self):
        value = derive_approved_task_from_lv_manifest(
            make_manifest(),
            project_id=PROJECT,
            gate_id=GATE,
            lv_id=LV,
            run_id=RUN,
            canonical_plan_sha256=PLAN,
        )
        self.assertEqual(value.plan_task_ref, "TASK-4A-08")
        self.assertIs(value.task_effect_policy, TaskEffectPolicy.MUTATING)
        self.assertEqual(value.owned_scope, OWNED)
        self.assertEqual(
            value.requirement_refs,
            ("REQ-002", "REQ-007", "REQ-008", "REQ-009", "REQ-010", "REQ-011", "REQ-013"),
        )
        self.assertEqual(set(value.allowed_capabilities), set(DEC007_CONTRACT_IDS))

    def test_tool_projection_digest_tamper_is_blocked(self):
        value = make_manifest()
        value["tool_authorization_projection_sha256"] = "0" * 64
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            derive_approved_task_from_lv_manifest(
                value,
                project_id=PROJECT,
                gate_id=GATE,
                lv_id=LV,
                run_id=RUN,
                canonical_plan_sha256=PLAN,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_TOOL_PROJECTION_DRIFT",
        )

    def test_contract_requirement_ref_tamper_is_blocked(self):
        value = make_manifest()
        value["active_tool_authorization_contracts"][0]["requirement_refs"] = ["REQ-FAKE"]
        with self.assertRaises(ProductionCanonicalAuthorityError):
            derive_approved_task_from_lv_manifest(
                value,
                project_id=PROJECT,
                gate_id=GATE,
                lv_id=LV,
                run_id=RUN,
                canonical_plan_sha256=PLAN,
            )

    def test_builds_exact_worker_authority_context(self):
        value = build_worker_authority_extra_context(
            manifest=make_manifest(),
            launch=_Launch(),
            requirements_sha256=REQ,
        )
        self.assertEqual(value["requirement_digest"], REQ)
        self.assertEqual(value["owned_files"], list(OWNED))
        self.assertEqual(
            value["tool_authorization_projection"]["worker_task_id"],
            "TASK-4A-08",
        )
        self.assertEqual(
            value["canonical_authority_binding"]["worker_task_id"],
            "TASK-4A-08",
        )
        self.assertEqual(value["canonical_authority_binding_digest"], "5" * 64)

    def test_worker_requirement_digest_drift_is_blocked(self):
        with self.assertRaises(ProductionCanonicalAuthorityError) as caught:
            build_worker_authority_extra_context(
                manifest=make_manifest(),
                launch=_Launch(),
                requirements_sha256="9" * 64,
            )
        self.assertEqual(
            caught.exception.reason_taxonomy,
            "PRODUCTION_CANONICAL_WORKER_REQUIREMENT_DRIFT",
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from runtime.orchestrator.approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationContractError,
    ApprovedFullPlanActivationRequestV1,
)


def executable_request():
    return {
        "schema_version": "orchestration.approved-full-plan-activation-request.v1",
        "activation_request_id": "FP-ACT-1",
        "project_alias": "demo",
        "approved_plan": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": "a" * 64},
        "approved_spec": {"path": "docs/spec.md", "sha256": "b" * 64},
        "expected_branch": "feature/demo",
        "expected_head": "c" * 40,
        "runtime_release_digest": "d" * 64,
        "approval_ref": "USER-APPROVAL-1",
        "gate_bindings": [{
            "gate_id": "GATE-001",
            "approval_evidence": {"path": "docs/approval-g1.json", "sha256": "e" * 64},
            "engine_requirement_evidence": {"path": "docs/engine-g1.json", "sha256": "f" * 64},
            "project_requirement_evidence_by_lv": [{
                "lv_id": "TASK-001", "path": "docs/req-task-001.json", "sha256": "1" * 64,
            }],
        }],
    }


class ApprovedFullPlanActivationContractTests(unittest.TestCase):
    def test_authority_refs_are_domain_neutral_safe_relative_names(self):
        value = executable_request()
        value["gate_bindings"][0]["approval_evidence"]["path"] = "approval-g1.json"
        value["gate_bindings"][0]["engine_requirement_evidence"]["path"] = "engine-g1.json"
        parsed = ApprovedFullPlanActivationRequestV1.from_mapping(value)
        self.assertEqual(parsed.gate_bindings[0].approval_evidence.path, "approval-g1.json")
        self.assertEqual(parsed.gate_bindings[0].engine_requirement_evidence.path, "engine-g1.json")

    def test_request_is_closed_and_digest_stable(self):
        request = ApprovedFullPlanActivationRequestV1.from_mapping(executable_request())
        self.assertEqual(request.to_dict(), executable_request())
        self.assertRegex(request.request_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(request.request_digest, ApprovedFullPlanActivationRequestV1.from_mapping(executable_request()).request_digest)

    def test_authority_bearing_caller_fields_are_rejected(self):
        for field in ("provider", "model", "backend", "command", "argv", "environment", "owned_scope", "editable_scope", "mapping_root"):
            with self.subTest(field=field):
                value = executable_request(); value[field] = "forbidden"
                with self.assertRaisesRegex(ApprovedFullPlanActivationContractError, "FIELDS_MISMATCH"):
                    ApprovedFullPlanActivationRequestV1.from_mapping(value)

    def test_artifact_paths_must_be_safe_project_relative(self):
        for path in ("/etc/passwd", "../secret", r"docs\\secret.json", ""):
            with self.subTest(path=path):
                value = executable_request(); value["approved_spec"] = {"path": path, "sha256": "b" * 64}
                with self.assertRaises(ApprovedFullPlanActivationContractError):
                    ApprovedFullPlanActivationRequestV1.from_mapping(value)

    def test_digests_and_head_must_be_lowercase_hex(self):
        for mutate in (
            lambda v: v["approved_plan"].update(sha256="A" * 64),
            lambda v: v.update(runtime_release_digest="d" * 63),
            lambda v: v.update(expected_head="C" * 40),
        ):
            value = executable_request(); mutate(value)
            with self.assertRaises(ApprovedFullPlanActivationContractError):
                ApprovedFullPlanActivationRequestV1.from_mapping(value)

    def test_gate_and_lv_ids_are_unique_and_order_is_preserved(self):
        value = executable_request()
        value["gate_bindings"].append(dict(value["gate_bindings"][0]))
        with self.assertRaisesRegex(ApprovedFullPlanActivationContractError, "GATE"):
            ApprovedFullPlanActivationRequestV1.from_mapping(value)

        value = executable_request()
        value["gate_bindings"][0]["project_requirement_evidence_by_lv"].append(
            {"lv_id": "TASK-001", "path": "docs/req-duplicate.json", "sha256": "2" * 64}
        )
        with self.assertRaisesRegex(ApprovedFullPlanActivationContractError, "LV"):
            ApprovedFullPlanActivationRequestV1.from_mapping(value)

    def test_branch_and_approval_provenance_are_required(self):
        for key, bad in (("expected_branch", "HEAD"), ("expected_branch", "feature//bad"), ("approval_ref", "")):
            value = executable_request(); value[key] = bad
            with self.assertRaises(ApprovedFullPlanActivationContractError):
                ApprovedFullPlanActivationRequestV1.from_mapping(value)

    def test_engine_requirement_may_be_absent_but_field_may_not_be_omitted(self):
        value = executable_request(); value["gate_bindings"][0]["engine_requirement_evidence"] = None
        parsed = ApprovedFullPlanActivationRequestV1.from_mapping(value)
        self.assertIsNone(parsed.gate_bindings[0].engine_requirement_evidence)
        del value["gate_bindings"][0]["engine_requirement_evidence"]
        with self.assertRaisesRegex(ApprovedFullPlanActivationContractError, "FIELDS_MISMATCH"):
            ApprovedFullPlanActivationRequestV1.from_mapping(value)


if __name__ == "__main__":
    unittest.main()

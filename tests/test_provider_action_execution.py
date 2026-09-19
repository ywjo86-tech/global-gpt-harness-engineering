from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.provider_action_execution import (
    PROPOSAL_SCHEMA_V1, ProviderActionExecutionError, _extract_json_object,
    _bounded_remediation_owned_context, _validation_feedback_for_target,
    _feedback_trace_paths, _remediation_priority_paths, build_action_proposal_prompt,
    execute_provider_action_proposal, select_action_context_files,
)
from runtime.orchestrator.context_sanitizer import sanitize_context
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1, RouterRequestV2, route_request,
)
from runtime.orchestrator.schemas import TaskSlice, WorkerRequest
from runtime.orchestrator.tool_authorization import (
    activate_contract, build_dec007_approved_contracts,
)

PLAN = "b" * 64
PACKAGE = "d" * 64
WORKER_TASK = "TASK_015_WORKER"


def decision(fallbacks=()):
    snapshot = ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, "S-ACTION", {"nvidia": True, "codex": False},
        {"nvidia": "nvidia/action-model"}, ("mprf",),
        model_fallback_refs={"nvidia": tuple(fallbacks)} if fallbacks else None,
        provider_capabilities={"nvidia": (
            "reasoning", "patch_generation", "implementation_generation", "test_design", "integration",
        )},
    )
    request = RouterRequestV2(
        ROUTER_REQUEST_SCHEMA_V2, "REQ-ACTION", "P", "R", "TASK-015", "E", "a" * 64,
        "ACTION", ("reasoning", "implementation", "test", "integration", "filesystem_write"),
        True, GOVERNED_POLICY_V1, snapshot,
    )
    return route_request(request)


def active_contracts(owned):
    approved = build_dec007_approved_contracts(
        project_id="P", gate_id="G", lv_id="TASK-015", run_id="R",
        canonical_plan_sha256=PLAN, owned_files=tuple(owned), worker_task_id=WORKER_TASK,
    )
    return [activate_contract(item, package_binding_sha256=PACKAGE,
                              authorized_decisions={"DEC-007": "USER_DECISION"}).to_dict()
            for item in approved]


def worker(root: Path, owned):
    task = TaskSlice(
        thread_id="TASK-015", assigned_agent="implementation_agent", input="implement project factory E2E",
        expected_output="tests", validation_criteria=["TEST-026", "TEST-027"],
        editable_scope=list(owned), forbidden_scope=[], merge_point="GATE_EXIT",
        required_capabilities=["reasoning", "implementation", "test", "integration", "filesystem_write"],
    )
    return WorkerRequest(
        project_root=str(root), task=task,
        contract_summary={"project_id": "P", "gate_id": "G", "lv_id": "TASK-015",
                          "canonical_plan_sha256": PLAN},
        state_snapshot={"branch": "main", "head": "a" * 40},
        extra_context={
            "run_id": "R", "attempt": 1, "requirement_digest": "c" * 64,
            "active_tool_authorization_contracts": active_contracts(owned),
            "tool_authorization_projection": {"worker_task_id": WORKER_TASK},
        },
    )


class ProviderActionExecutionTest(unittest.TestCase):
    def proposal(self, content="created\n", owned_id="OWNED_0001"):
        return {
            "schema_version": PROPOSAL_SCHEMA_V1, "project_id": "P", "run_id": "R",
            "gate_id": "G", "lv_id": "TASK-015", "plan_sha256": PLAN,
            "source_head": "a" * 40,
            "writes": [{"owned_file_id": owned_id, "relative_path": "", "content": content}],
            "summary": "implement bounded E2E fixture",
        }
    def test_extracts_single_fenced_proposal_from_provider_prose(self):
        proposal = self.proposal()
        raw = "Here is the requested proposal.\n```json\n" + json.dumps(proposal) + "\n```\nDone."
        self.assertEqual(dict(_extract_json_object(raw)), proposal)

    def test_extracts_single_embedded_proposal_but_rejects_multiple(self):
        proposal = self.proposal()
        one = "analysis before\n" + json.dumps(proposal) + "\nanalysis after"
        self.assertEqual(dict(_extract_json_object(one)), proposal)
        two = json.dumps(proposal) + "\n" + json.dumps(proposal)
        with self.assertRaisesRegex(ProviderActionExecutionError, "ambiguous"):
            _extract_json_object(two)

    def test_invalid_json_gets_one_bounded_correction_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            def provider_runner(**kwargs):
                calls.append(kwargs["prompt"])
                summary = "analysis only" if len(calls) == 1 else json.dumps(self.proposal())
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": summary, "context_metadata": {}}
            result = execute_provider_action_proposal(
                request, decision=decision(), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual(len(calls), 2)
            self.assertIn("CORRECTION RETRY", calls[1])
            self.assertEqual(result["proposal_generation_attempts"], 2)
            self.assertEqual((root / owned[0]).read_text(), "created\n")

    def test_invalid_python_gets_one_bounded_correction_before_any_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            invalid = self.proposal(content='value = (1 +\n')
            valid = self.proposal(content='value = 1\n')
            def provider_runner(**kwargs):
                calls.append(kwargs["prompt"])
                payload = invalid if len(calls) == 1 else valid
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(payload), "context_metadata": {}}
            result = execute_provider_action_proposal(
                request, decision=decision(), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual(len(calls), 2)
            self.assertIn("CORRECTION RETRY", calls[1])
            self.assertEqual(result["proposal_generation_attempts"], 2)
            self.assertEqual((root / owned[0]).read_text(), "value = 1\n")
            self.assertEqual(len(list((root / "run/provider-action-effects").glob("*.receipt.json"))), 1)

    def test_invalid_json_three_times_fails_without_persist_or_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            def provider_runner(**_kwargs):
                calls.append(1)
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": "not json", "context_metadata": {}}
            with self.assertRaisesRegex(ProviderActionExecutionError, "not valid JSON"):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda _raw: True, timeout=30,
                )
            self.assertEqual(len(calls), 3)
            self.assertFalse((root / "run/provider-action-proposal.json").exists())
            self.assertFalse((root / owned[0]).exists())

    def test_output_contract_retry_rotates_only_through_router_approved_models(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            routed = decision(("nvidia/fallback-a", "nvidia/fallback-b"))
            invalid = self.proposal(); invalid["unexpected"] = "metadata"
            def provider_runner(**kwargs):
                calls.append((kwargs["model"], tuple(kwargs["fallback_models"]), kwargs["prompt"]))
                payload = invalid if len(calls) == 1 else self.proposal(content="value = 1\n")
                return {
                    "status": "completed", "model": kwargs["model"], "provider_attempts": 1,
                    "model_attempts": {kwargs["model"]: 1}, "model_failover_used": False,
                    "summary": json.dumps(payload), "context_metadata": {},
                }
            result = execute_provider_action_proposal(
                request, decision=routed, baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual([item[0] for item in calls], ["nvidia/action-model", "nvidia/fallback-a"])
            self.assertNotIn("nvidia/action-model", calls[1][1])
            self.assertIn("schema mismatch", calls[1][2])
            self.assertEqual(result["proposal_generation_models"], ["nvidia/action-model", "nvidia/fallback-a"])
            self.assertEqual(result["provider_attempts"], 2)
            self.assertTrue(result["model_failover_used"])
            self.assertEqual((root / owned[0]).read_text(), "value = 1\n")

    def test_multiple_new_exact_owned_files_generate_atomic_segments(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_one.py", "tests/test_two.py"]
            request = worker(root, owned); calls = []
            def provider_runner(**kwargs):
                self.assertFalse((root / owned[0]).exists())
                self.assertFalse((root / owned[1]).exists())
                prompt = kwargs["prompt"]; calls.append(prompt)
                if "SEGMENT TARGET: Generate exactly one write for OWNED_0001" in prompt:
                    payload = self.proposal(content="def test_one():\n    assert True\n", owned_id="OWNED_0001")
                elif "SEGMENT TARGET: Generate exactly one write for OWNED_0002" in prompt:
                    payload = self.proposal(content="def test_two():\n    assert True\n", owned_id="OWNED_0002")
                else:
                    self.fail("segmented prompt target missing")
                return {"status":"completed","model":kwargs["model"],"provider_attempts":1,
                        "model_attempts":{kwargs["model"]:1},"model_failover_used":False,
                        "summary":json.dumps(payload),"context_metadata":{}}
            result = execute_provider_action_proposal(
                request, decision=decision(), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual(len(calls), 2)
            self.assertTrue(result["segmented_generation"])
            self.assertEqual(result["proposal_segment_count"], 2)
            self.assertEqual(result["proposal_generation_attempts"], 2)
            self.assertEqual((root / owned[0]).read_text(), "def test_one():\n    assert True\n")
            self.assertEqual((root / owned[1]).read_text(), "def test_two():\n    assert True\n")
            self.assertEqual(len(list((root / "run/provider-action-effects").glob("*.receipt.json"))), 2)

    def test_segment_failure_leaves_zero_product_effects(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_one.py", "tests/test_two.py"]
            request = worker(root, owned); calls = []
            def provider_runner(**kwargs):
                self.assertFalse((root / owned[0]).exists())
                self.assertFalse((root / owned[1]).exists())
                prompt = kwargs["prompt"]; calls.append(prompt)
                if "SEGMENT TARGET: Generate exactly one write for OWNED_0001" in prompt:
                    payload = self.proposal(content="def test_one():\n    assert True\n", owned_id="OWNED_0001")
                    summary = json.dumps(payload)
                else:
                    summary = "not-json"
                return {"status":"completed","model":kwargs["model"],"provider_attempts":1,
                        "model_attempts":{kwargs["model"]:1},"model_failover_used":False,
                        "summary":summary,"context_metadata":{}}
            with self.assertRaisesRegex(ProviderActionExecutionError, "not valid JSON"):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda _raw: True, timeout=30,
                )
            self.assertEqual(len(calls), 4)
            self.assertFalse((root / owned[0]).exists())
            self.assertFalse((root / owned[1]).exists())
            self.assertFalse((root / "run/provider-action-proposal.json").exists())
            self.assertFalse((root / "run/provider-action-effects").exists())

    def test_empty_new_python_test_retries_before_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            bad = self.proposal(content="")
            good = self.proposal(content="def test_generated():\n    assert True\n")
            def provider_runner(**kwargs):
                self.assertFalse((root / owned[0]).exists())
                calls.append(kwargs["prompt"]); payload = bad if len(calls) == 1 else good
                return {"status":"completed","model":kwargs["model"],"provider_attempts":1,
                        "model_attempts":{kwargs["model"]:1},"model_failover_used":False,
                        "summary":json.dumps(payload),"context_metadata":{}}
            result = execute_provider_action_proposal(
                request, decision=decision(("nvidia/fallback-a",)), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertIn("new Python content is empty", calls[1])
            self.assertEqual((root / owned[0]).read_text(), "def test_generated():\n    assert True\n")
            self.assertEqual(len(list((root / "run/provider-action-effects").glob("*.receipt.json"))), 1)
            self.assertEqual(result["proposal_generation_attempts"], 2)

    def test_validation_feedback_is_applied_to_remediation_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            (root / "tests").mkdir(); (root / owned[0]).write_text("def test_old():\n    assert False\n")
            request = worker(root, owned); prompts = []
            def provider_runner(**kwargs):
                prompts.append(kwargs["prompt"])
                return {"status":"completed","model":kwargs["model"],"provider_attempts":1,
                        "model_attempts":{kwargs["model"]:1},"model_failover_used":False,
                        "summary":json.dumps(self.proposal(content="def test_fixed():\n    assert True\n")),
                        "context_metadata":{}}
            result = execute_provider_action_proposal(
                request, decision=decision(), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
                validation_feedback="AttributeError: module unittest has no attribute mock",
            )
            self.assertIn("VALIDATION REMEDIATION", prompts[0])
            self.assertIn("AttributeError", prompts[0])
            self.assertTrue(result["validation_feedback_applied"])
            self.assertEqual((root / owned[0]).read_text(), "def test_fixed():\n    assert True\n")

    def test_write_binding_error_retries_with_router_approved_fallback_without_early_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            routed = decision(("nvidia/fallback-a",))
            bad = self.proposal(content="value = 0\n", owned_id="OWNED_9999")
            good = self.proposal(content="value = 1\n")
            def provider_runner(**kwargs):
                calls.append((kwargs["model"], kwargs["prompt"]))
                payload = bad if len(calls) == 1 else good
                return {
                    "status": "completed", "model": kwargs["model"], "provider_attempts": 1,
                    "model_attempts": {kwargs["model"]: 1}, "model_failover_used": False,
                    "summary": json.dumps(payload), "context_metadata": {},
                }
            result = execute_provider_action_proposal(
                request, decision=routed, baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual([item[0] for item in calls], ["nvidia/action-model", "nvidia/fallback-a"])
            self.assertIn("write binding is invalid", calls[1][1])
            self.assertEqual((root / owned[0]).read_text(), "value = 1\n")
            self.assertEqual(len(list((root / "run/provider-action-effects").glob("*.receipt.json"))), 1)
            self.assertEqual(result["proposal_generation_attempts"], 2)

    def test_relative_path_binding_error_is_retryable_but_never_broadens_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []
            bad = self.proposal(content="value = 0\n"); bad["writes"][0]["relative_path"] = "escape.py"
            good = self.proposal(content="value = 1\n")
            def provider_runner(**kwargs):
                calls.append(kwargs["prompt"]); payload = bad if len(calls) == 1 else good
                return {"status": "completed", "model": kwargs["model"], "provider_attempts": 1,
                        "model_attempts": {kwargs["model"]: 1}, "model_failover_used": False,
                        "summary": json.dumps(payload), "context_metadata": {}}
            result = execute_provider_action_proposal(
                request, decision=decision(("nvidia/fallback-a",)), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertIn("relative path binding is invalid", calls[1])
            self.assertFalse((root / "tests/escape.py").exists())
            self.assertEqual((root / owned[0]).read_text(), "value = 1\n")
            self.assertEqual(result["proposal_generation_attempts"], 2)

    def test_identity_mismatch_is_not_auto_corrected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); calls = []; bad = self.proposal(); bad["source_head"] = "f" * 40
            def provider_runner(**_kwargs):
                calls.append(1)
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(bad), "context_metadata": {}}
            with self.assertRaisesRegex(ProviderActionExecutionError, "identity mismatch"):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda _raw: True, timeout=30,
                )
            self.assertEqual(len(calls), 1)
            self.assertFalse((root / owned[0]).exists())

    def test_valid_proposal_writes_only_through_governed_broker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned)
            def provider_runner(**_kwargs):
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(self.proposal()), "context_metadata": {}}
            result = execute_provider_action_proposal(
                request, decision=decision(), baseline="a" * 40, owned=owned,
                output_dir=root / "run", provider_runner=provider_runner,
                security_scan=lambda _raw: True, timeout=30,
            )
            self.assertEqual((root / owned[0]).read_text(), "created\n")
            self.assertEqual(result["provider"], "nvidia")
            self.assertTrue(result["governed_effect_evidence"])
            intents = list((root / "run/provider-action-effects").glob("*.intent.json"))
            self.assertEqual(len(intents), 1)
            identity = json.loads(intents[0].read_text())["identity"]
            self.assertEqual(identity["operation_callsite_id"], "PROVIDER_ACTION_PROPOSAL_V1")

    def test_invalid_owned_identity_fails_before_any_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned)
            def provider_runner(**_kwargs):
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(self.proposal(owned_id="OWNED_9999")), "context_metadata": {}}
            with self.assertRaises(ProviderActionExecutionError):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda _raw: True, timeout=30,
                )
            self.assertFalse((root / owned[0]).exists())

    def test_context_selection_is_bounded_and_excludes_runtime_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "runtime/ai_office").mkdir(parents=True)
            (root / "tests").mkdir(); (root / "_workspace").mkdir()
            (root / "runtime/ai_office/foundry.py").write_text("def project_factory(): pass\n")
            (root / "tests/test_foundry.py").write_text("def test_project_factory(): pass\n")
            (root / "_workspace/secret.py").write_text("project_factory secret\n")
            request = worker(root, ["tests/test_project_factory_e2e.py"])
            selected = select_action_context_files(root, request, request.task.editable_scope)
            self.assertLessEqual(len(selected), 8)
            self.assertTrue(any("foundry" in item for item in selected))
            self.assertFalse(any(item.startswith("_workspace/") for item in selected))

    def test_semantic_alias_keeps_factory_foundry_context_inside_sanitizer_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "tests").mkdir()
            owned = ["tests/test_project_factory_e2e.py"]
            request = worker(root, owned)
            request.task.input = "Implement project factory integration coverage"
            (root / "tests/test_foundry.py").write_text("def test_foundry_project(): pass\n")
            for index in range(12):
                (root / f"tests/test_project_{index:02d}.py").write_text("def test_project(): pass\n")
            selected = select_action_context_files(root, request, owned)
            self.assertLessEqual(len(selected), 8)
            self.assertIn("tests/test_foundry.py", selected)

    def test_dependency_aware_context_prefers_matching_local_source_modules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "tests").mkdir(); (root / "runtime/ai_office").mkdir(parents=True)
            owned = ["tests/test_project_factory_e2e.py", "tests/test_daily_loop_e2e.py"]
            request = worker(root, owned)
            request.task.input = "Cover project factory and daily loop workflow integration"
            (root / "runtime/ai_office/foundry.py").write_text("def create_operating_contract(): pass\n")
            (root / "runtime/ai_office/workflow.py").write_text("def next_state(): pass\n")
            (root / "runtime/ai_office/state_store.py").write_text("class Store: pass\n")
            (root / "tests/test_ai_office_foundry.py").write_text(
                "from runtime.ai_office.foundry import create_operating_contract\n"
            )
            (root / "tests/test_ai_office_workflow.py").write_text(
                "from runtime.ai_office.state_store import Store\n"
                "from runtime.ai_office.workflow import next_state\n"
            )
            for index in range(10):
                (root / f"tests/test_project_context_{index:02d}.py").write_text("def test_project(): pass\n")
            selected = select_action_context_files(root, request, owned)
            self.assertLessEqual(len(selected), 8)
            self.assertIn("runtime/ai_office/foundry.py", selected)
            self.assertIn("runtime/ai_office/workflow.py", selected)

    def test_remediation_context_excludes_oversized_owned_file_but_prompt_keeps_bounded_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "tests").mkdir(); (root / "runtime/ai_office").mkdir(parents=True)
            owned = ["tests/test_large.py", "tests/test_small.py"]
            (root / owned[0]).write_text("def test_large():\n    assert True\n" + "# filler\n" * 2500)
            (root / owned[1]).write_text("def test_small():\n    assert True\n")
            (root / "runtime/ai_office/foundry.py").write_text("def create_operating_contract(): return {}\n")
            request = worker(root, owned)
            selected = select_action_context_files(root, request, owned, exclude_paths=set(owned))
            self.assertNotIn(owned[0], selected); self.assertNotIn(owned[1], selected)
            prompt = build_action_proposal_prompt(
                request, baseline="a" * 40, owned=owned,
                validation_feedback=f"TRACE {owned[0]} line 2 | AssertionError",
                target_owned_file_id="OWNED_0001",
            )
            self.assertIn("CURRENT TARGET FILE CONTEXT", prompt)
            self.assertIn("def test_large", prompt)
            sanitized = sanitize_context(prompt, selected, root)
            self.assertLessEqual(sanitized.metadata["file_count"], 8)

    def test_oversized_remediation_context_is_bounded_around_trace_line(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "tests").mkdir()
            path = root / "tests/test_huge.py"
            lines = [f"line_{index} = {index}" for index in range(5000)]
            path.write_text("\n".join(lines) + "\n")
            excerpt = _bounded_remediation_owned_context(
                root, "tests/test_huge.py", "TRACE tests/test_huge.py line 2500 | AssertionError",
            )
            self.assertLessEqual(len(excerpt.encode("utf-8")), 32 * 1024)
            self.assertIn("02500:", excerpt)
            self.assertNotIn("00001: line_0", excerpt)

    def test_feedback_trace_paths_rejects_traversal_candidates(self):
        feedback = (
            "TRACE runtime/ai_office/workflow.py line 10 | "
            "TRACE runtime/../../outside.py line 20 | "
            "TRACE tests/../outside.py line 30"
        )
        self.assertEqual(_feedback_trace_paths(feedback), ("runtime/ai_office/workflow.py",))


    def test_validation_feedback_isolated_per_owned_target(self):
        feedback = (
            "ERROR: one | TRACE tests/test_one.py line 12 | TRACE runtime/ai_office/workflow.py line 120 | "
            "WorkflowContractError: undeclared workflow transition | "
            "ERROR: two | TRACE tests/test_two.py line 79 | TRACE runtime/orchestrator/office_execution_backend_adapter.py line 72 | "
            "OfficeExecutionBackendAdapterError: runtime result identity binding mismatch"
        )
        first = _validation_feedback_for_target(feedback, "tests/test_one.py")
        second = _validation_feedback_for_target(feedback, "tests/test_two.py")
        self.assertIn("workflow transition", first)
        self.assertNotIn("identity binding mismatch", first)
        self.assertIn("identity binding mismatch", second)
        self.assertNotIn("workflow transition", second)

    def test_remediation_priority_includes_authoritative_import_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "tests").mkdir(); (root / "runtime/orchestrator").mkdir(parents=True)
            target = root / "tests/test_one.py"
            target.write_text(
                "from runtime.orchestrator.office_execution_contract import OfficeExecutionRequestV1\n"
                "from runtime.orchestrator.office_execution_backend_adapter import OfficeExecutionBackendAdapter\n"
            )
            (root / "runtime/orchestrator/office_execution_contract.py").write_text("class OfficeExecutionRequestV1: pass\n")
            (root / "runtime/orchestrator/office_execution_backend_adapter.py").write_text("class OfficeExecutionBackendAdapter: pass\n")
            priority = _remediation_priority_paths(
                root, "tests/test_one.py",
                "TRACE tests/test_one.py line 2 | TRACE runtime/orchestrator/office_execution_backend_adapter.py line 10 | TypeError: bad signature",
            )
            self.assertEqual(priority[0], "runtime/orchestrator/office_execution_backend_adapter.py")
            self.assertIn("runtime/orchestrator/office_execution_contract.py", priority)
            request = worker(root, ["tests/test_one.py", "tests/test_two.py"]); (root / "tests/test_two.py").write_text("pass\n")
            selected = select_action_context_files(
                root, request, ["tests/test_one.py"], exclude_paths={"tests/test_one.py", "tests/test_two.py"},
                priority_paths=priority,
            )
            self.assertIn("runtime/orchestrator/office_execution_contract.py", selected)
            self.assertNotIn("tests/test_one.py", selected)
            self.assertNotIn("tests/test_two.py", selected)


    def test_identity_mismatch_fails_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned); bad = self.proposal(); bad["source_head"] = "f" * 40
            def provider_runner(**_kwargs):
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(bad), "context_metadata": {}}
            with self.assertRaisesRegex(ProviderActionExecutionError, "identity mismatch"):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda _raw: True, timeout=30,
                )
            self.assertFalse((root / owned[0]).exists())


    def test_security_rejected_proposal_is_never_persisted_or_applied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); owned = ["tests/test_generated.py"]
            request = worker(root, owned)
            def provider_runner(**_kwargs):
                return {"status": "completed", "model": "nvidia/action-model", "provider_attempts": 1,
                        "summary": json.dumps(self.proposal(content="api_key=generated-secret\n")),
                        "context_metadata": {}}
            with self.assertRaisesRegex(ProviderActionExecutionError, "security validation"):
                execute_provider_action_proposal(
                    request, decision=decision(), baseline="a" * 40, owned=owned,
                    output_dir=root / "run", provider_runner=provider_runner,
                    security_scan=lambda raw: b"generated-secret" not in raw, timeout=30,
                )
            self.assertFalse((root / "run/provider-action-proposal.json").exists())
            self.assertFalse((root / owned[0]).exists())
            self.assertFalse((root / "run/provider-action-effects").exists())

    def test_context_selection_excludes_history_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "docs/history").mkdir(parents=True)
            (root / "runtime/ai_office").mkdir(parents=True)
            (root / "docs/history/old_foundry.py").write_text("project_factory historical\n")
            (root / "runtime/ai_office/foundry.py").write_text("def project_factory(): pass\n")
            request = worker(root, ["tests/test_project_factory_e2e.py"])
            selected = select_action_context_files(root, request, request.task.editable_scope)
            self.assertFalse(any(item.startswith("docs/history/") for item in selected))
            self.assertIn("runtime/ai_office/foundry.py", selected)


if __name__ == "__main__":
    unittest.main()

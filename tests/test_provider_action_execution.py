from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.provider_action_execution import (
    PROPOSAL_SCHEMA_V1, ProviderActionExecutionError, _extract_json_object,
    execute_provider_action_proposal, select_action_context_files,
)
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


def decision():
    snapshot = ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, "S-ACTION", {"nvidia": True, "codex": False},
        {"nvidia": "nvidia/action-model"}, ("mprf",),
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

    def test_invalid_json_twice_fails_without_persist_or_effect(self):
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
            self.assertEqual(len(calls), 2)
            self.assertFalse((root / "run/provider-action-proposal.json").exists())
            self.assertFalse((root / owned[0]).exists())

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
            self.assertLessEqual(len(selected), 12)
            self.assertTrue(any("foundry" in item for item in selected))
            self.assertFalse(any(item.startswith("_workspace/") for item in selected))

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

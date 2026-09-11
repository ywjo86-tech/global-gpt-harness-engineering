import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.orchestrator.tool_authorization import (
    ContractGovernedToolBroker,
    ToolAuthorizationContract,
    ToolAuthorizationError,
    ToolAuthorizationRequest,
    activate_contract,
    authorize_tool_operation,
    build_contract_candidate,
    build_dec007_approved_contracts,
    DEC007_CONTRACT_IDS,
    ClosedOperationRegistry,
    OperationIdentity,
    RegisteredOperation,
    SingleToolBroker,
    ToolEffectJournal,
)


PACKAGE = "a" * 64
SCOPE = "d" * 64
DECISIONS = {"DEC_003": "USER_DECISION"}


def approved(**changes):
    value = ToolAuthorizationContract(
        contract_id="TAC_1", contract_version="tool-authorization.v1",
        contract_status="APPROVED", worker_task_id="TASK_1",
        requirement_refs=("REQ_1",), plan_task_refs=("PLAN_TASK_1",),
        operation_class_id="REGISTERED_TEST_RUNNER", capability_class="TEST",
        operation_intent="VALIDATE", requirement_binding="REQUIRED",
        scope_binding="IN_SCOPE", scope_authorization_source="MULTIPLE",
        authorization_decision_ref="DEC_003", validity_scope="TASK_ONLY",
        security_obligation_profile="SECRET_SCAN_REQUIRED",
        approval_authority="USER_DECISION",
        project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
        canonical_plan_sha256="b" * 64, requirement_digest="c" * 64,
        owned_scope_sha256=SCOPE,
    )
    return replace(value, **changes).sealed()


def request(**changes):
    value = ToolAuthorizationRequest(
        worker_task_id="TASK_1", worker_action_id="COMMAND_EXECUTION_1",
        operation_class_id="REGISTERED_TEST_RUNNER", capability_class="TEST",
        operation_intent="VALIDATE", scope_binding="IN_SCOPE",
        package_binding_sha256=PACKAGE,
        project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
        canonical_plan_sha256="b" * 64, requirement_digest="c" * 64,
        owned_scope_sha256=SCOPE,
    )
    return replace(value, **changes)


class ToolAuthorizationTests(unittest.TestCase):
    def test_no_candidate_and_approved_contracts_block(self):
        self.assertEqual(authorize_tool_operation(None, request())["authorization_status"], "BLOCK")
        candidate = approved(contract_status="CANDIDATE")
        self.assertEqual(authorize_tool_operation(candidate, request())["authorization_status"], "BLOCK")
        self.assertEqual(authorize_tool_operation(approved(), request())["authorization_status"], "BLOCK")

    def test_active_exact_match_authorizes(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        result = authorize_tool_operation(active, request())
        self.assertEqual(result["authorization_status"], "AUTHORIZED")

    def test_task_operation_scope_and_terminal_status_mismatch_block(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        cases = (
            request(worker_task_id="TASK_2"),
            request(operation_class_id="REGISTERED_BUILD_TOOL"),
            request(scope_binding="OUT_OF_SCOPE"),
        )
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(authorize_tool_operation(active, item)["authorization_status"], "BLOCK")
        for status in ("REVOKED", "EXPIRED", "SUPERSEDED"):
            terminal = replace(active, contract_status=status, contract_digest="").sealed()
            self.assertEqual(authorize_tool_operation(terminal, request())["authorization_status"], "BLOCK")

    def test_all_lifecycle_and_scope_binding_drift_blocks(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        cases = (
            request(project_id="PROJECT_2"), request(gate_id="GATE_2"), request(lv_id="LV_2"),
            request(run_id="RUN_2"), request(canonical_plan_sha256="e" * 64),
            request(requirement_digest="f" * 64), request(owned_scope_sha256="0" * 64),
            request(package_binding_sha256="1" * 64),
        )
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(authorize_tool_operation(active, item)["authorization_status"], "BLOCK")

    def test_dec007_contract_set_is_exact_stable_and_not_self_approved(self):
        contracts = build_dec007_approved_contracts(
            project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
            canonical_plan_sha256="b" * 64, owned_files=("owned.txt",))
        self.assertEqual(len(contracts), 3)
        self.assertEqual({item.contract_id for item in contracts}, set(DEC007_CONTRACT_IDS.values()))
        self.assertEqual({item.operation_class_id for item in contracts}, set(DEC007_CONTRACT_IDS))
        self.assertTrue(all(item.contract_status == "APPROVED" for item in contracts))
        self.assertTrue(all(item.worker_task_id == "TASK-4A-08" for item in contracts))
        self.assertTrue(all(item.authorization_decision_ref == "DEC-007" for item in contracts))
        self.assertTrue(all(item.approval_authority == "USER_DECISION" for item in contracts))

    def test_unknown_operation_and_worker_self_approval_block(self):
        with self.assertRaises(ToolAuthorizationError):
            approved(operation_class_id="UNBOUND_OPERATION_CLASS")
        with self.assertRaises(ToolAuthorizationError):
            approved(approval_authority="WORKER")
        with self.assertRaises(ToolAuthorizationError):
            activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions={})
        with self.assertRaises(ToolAuthorizationError):
            activate_contract(approved(), package_binding_sha256=PACKAGE,
                              authorized_decisions={"DEC_003": "WORKER"})

    def test_broker_enforces_before_spawn_and_secret_scan_after_spawn(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        calls = []
        broker = ContractGovernedToolBroker(lambda: calls.append("spawned") or {"status": "completed"}, lambda _: True)
        with self.assertRaises(ToolAuthorizationError):
            broker.execute(None, request())
        self.assertEqual(calls, [])
        result, trace = broker.execute(active, request())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(trace["authorization_result"], "AUTHORIZED")
        self.assertEqual(trace["security_result"], "PASS")
        secret_broker = ContractGovernedToolBroker(lambda: {"status": "completed"}, lambda _: False)
        with self.assertRaises(ToolAuthorizationError):
            secret_broker.execute(active, request())

    def test_candidate_is_bounded_raw_free_and_decision_required(self):
        candidate = build_contract_candidate({
            "worker_task_id": "TASK_1", "worker_action_id": "COMMAND_EXECUTION_1",
            "security_operation_class_id": "UNBOUND_OPERATION_CLASS",
            "security_tool_capability": "OTHER", "security_tool_operation_intent": "EXECUTE",
            "tool_operation_requirement_binding": "UNKNOWN", "tool_scope_binding": "UNKNOWN",
        })
        self.assertEqual(candidate["contract_status"], "CANDIDATE")
        self.assertEqual(candidate["authorization_status"], "BLOCK")
        self.assertEqual(candidate["candidate_status"], "DECISION_REQUIRED")
        self.assertEqual(candidate["missing_authority_fields"], [
            "OPERATION_CLASS_ID", "REQUIREMENT_BINDING", "SCOPE_BINDING", "AUTHORIZATION_DECISION_REF",
        ])
        serialized = json.dumps(candidate)
        for forbidden in ("command", "argv", "stdout", "stderr", "api-key"):
            self.assertNotIn(forbidden, serialized)

    def _registered(self):
        return RegisteredOperation(
            operation_registration_id="REG_TEST_1", operation_class_id="REGISTERED_TEST_RUNNER",
            capability_class="TEST", operation_intent="VALIDATE", effect_class="LOCAL_PROCESS",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={"type": "object", "properties": {"status": {"type": "string"}},
                           "additionalProperties": False})

    def _identity(self):
        return OperationIdentity(
            operation_registration_id="REG_TEST_1", operation_dispatch_id="DISPATCH_1",
            operation_callsite_id="CALLSITE_1", operation_class_id="REGISTERED_TEST_RUNNER",
            worker_task_id="TASK_1", worker_action_id="COMMAND_EXECUTION_1",
            project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
            plan_digest="b" * 64, requirement_digest="c" * 64, package_digest=PACKAGE,
            owned_scope_sha256=SCOPE)

    def test_single_broker_journals_once_and_resume_does_not_rerun(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            journal = ToolEffectJournal(directory)
            broker = SingleToolBroker(registry=ClosedOperationRegistry([self._registered()]),
                contracts={"REGISTERED_TEST_RUNNER": active}, journal=journal,
                launchers={"REGISTERED_TEST_RUNNER": lambda _: calls.append("effect") or b"safe"},
                security_scan=lambda _: True)
            result = broker.execute(self._identity(), {})
            self.assertEqual(result["security_status"], "PASS")
            self.assertEqual(calls, ["effect"])
            self.assertEqual(journal.recovery_state(self._identity()), "COMPLETED_NO_RERUN")
            with self.assertRaises(ToolAuthorizationError): broker.execute(self._identity(), {})
            self.assertEqual(calls, ["effect"])

    def test_unauthorized_sensitive_and_ambiguous_paths_fail_closed(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            journal = ToolEffectJournal(directory)
            registry = ClosedOperationRegistry([self._registered()])
            denied = SingleToolBroker(registry=registry, contracts={}, journal=journal,
                launchers={"REGISTERED_TEST_RUNNER": lambda _: calls.append("effect")}, security_scan=lambda _: True)
            with self.assertRaises(ToolAuthorizationError): denied.execute(self._identity(), {})
            self.assertEqual(calls, [])
            sensitive = SingleToolBroker(registry=registry,
                contracts={"REGISTERED_TEST_RUNNER": active}, journal=journal,
                launchers={"REGISTERED_TEST_RUNNER": lambda _: calls.append("effect") or b"sensitive-fixture"},
                security_scan=lambda _: False)
            with self.assertRaises(ToolAuthorizationError): sensitive.execute(self._identity(), {})
            self.assertEqual(calls, ["effect"])
            self.assertEqual(journal.recovery_state(self._identity()), "COMPLETED_NO_RERUN")
        with tempfile.TemporaryDirectory() as directory:
            journal = ToolEffectJournal(directory)
            journal.begin(self._identity(), {"authorization_status": "AUTHORIZED"})
            self.assertEqual(journal.recovery_state(self._identity()), "BLOCKED_RECOVERY_AMBIGUOUS")
            with self.assertRaises(ToolAuthorizationError): journal.begin(
                self._identity(), {"authorization_status": "AUTHORIZED"})

    def test_concurrent_duplicate_has_one_launcher_invocation(self):
        active = activate_contract(approved(), package_binding_sha256=PACKAGE, authorized_decisions=DECISIONS)
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            broker = SingleToolBroker(registry=ClosedOperationRegistry([self._registered()]),
                contracts={"REGISTERED_TEST_RUNNER": active}, journal=ToolEffectJournal(directory),
                launchers={"REGISTERED_TEST_RUNNER": lambda _: calls.append("effect") or b"safe"},
                security_scan=lambda _: True)
            barrier = threading.Barrier(2); outcomes = []
            def invoke():
                barrier.wait()
                try: broker.execute(self._identity(), {}); outcomes.append("PASS")
                except ToolAuthorizationError: outcomes.append("BLOCK")
            threads = [threading.Thread(target=invoke) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(sorted(outcomes), ["BLOCK", "PASS"])
            self.assertEqual(calls, ["effect"])


if __name__ == "__main__":
    unittest.main()

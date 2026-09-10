import tempfile
import os
import json
import unittest
from pathlib import Path

from runtime.orchestrator.codex_dynamic_transport import ToolRequestEnvelope
from runtime.orchestrator.effect_evidence_bridge import verify_single_governed_write_effect
from runtime.orchestrator.production_tool_transport import ProductionToolTransport, production_operations
from runtime.orchestrator.tool_authorization import activate_contract, build_dec007_approved_contracts


PACKAGE = "a" * 64
PROOF97_PACKAGE = "d" * 64
PROOF97_PROJECT = "PROJECT_1"
PROOF97_GATE = "G-4A-ACTUAL"
PROOF97_LV = "TASK-4A-08"
PROOF97_RUN = "proof97-g4a-actual-20260910-01"
PROOF97_PLAN = "b" * 64


def active(operation):
    approved = build_dec007_approved_contracts(
        project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
        canonical_plan_sha256="b" * 64, owned_files=("owned.txt",))
    contract = next(item for item in approved if item.operation_class_id == operation.operation_class_id)
    return activate_contract(contract, package_binding_sha256=PACKAGE,
                             authorized_decisions={"DEC-007": "USER_DECISION"}).to_dict()


def proof97_active(operation):
    approved = build_dec007_approved_contracts(
        project_id=PROOF97_PROJECT, gate_id=PROOF97_GATE, lv_id=PROOF97_LV, run_id=PROOF97_RUN,
        canonical_plan_sha256=PROOF97_PLAN, owned_files=("owned.txt",))
    contract = next(item for item in approved if item.operation_class_id == operation.operation_class_id)
    return activate_contract(contract, package_binding_sha256=PROOF97_PACKAGE,
                             authorized_decisions={"DEC-007": "USER_DECISION"}).to_dict()


class ProductionToolTransportTests(unittest.TestCase):
    def request(self, root, contracts):
        return {"project_id": "PROJECT_1", "run_id": "RUN_1", "gate_id": "GATE_1", "lv_id": "LV_1",
                "canonical_plan_sha256": "b" * 64, "requirement_digest": "c" * 64,
                "owned_files": ["owned.txt"], "active_tool_authorization_contracts": contracts}

    def proof97_request(self, root, contracts):
        return {"project_id": PROOF97_PROJECT, "run_id": PROOF97_RUN,
                "gate_id": PROOF97_GATE, "lv_id": PROOF97_LV,
                "canonical_plan_sha256": PROOF97_PLAN, "requirement_digest": "c" * 64,
                "owned_files": ["owned.txt"], "active_tool_authorization_contracts": contracts}

    def test_exact_active_read_and_write_use_single_broker(self):
        operations = production_operations()
        contracts = [active(item) for item in operations]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "owned.txt"; target.write_text("initial", encoding="utf-8")
            transport = ProductionToolTransport(request=self.request(root, contracts), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            read = transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_READ", "TASK-4A-08",
                "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001"}, "CALL_1"))
            self.assertEqual(read.security_status, "PASS")
            self.assertEqual(read.bounded_payload["content"], "initial")
            write = transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "changed"}, "CALL_2"))
            self.assertEqual(write.status, "COMPLETED")
            self.assertEqual(target.read_text(encoding="utf-8"), "changed")
            self.assertEqual(len(list((root / "journal").glob("*.intent.json"))), 2)
            self.assertEqual(len(list((root / "journal").glob("*.receipt.json"))), 2)

    def test_missing_contract_and_unknown_operation_have_zero_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "owned.txt"; target.write_text("initial", encoding="utf-8")
            transport = ProductionToolTransport(request=self.request(root, []), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            with self.assertRaises(Exception):
                transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "changed"}, "CALL_1"))
            with self.assertRaises(Exception):
                transport.handle(ToolRequestEnvelope("UNKNOWN_OPERATION", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {}, "CALL_2"))
            self.assertEqual(target.read_text(encoding="utf-8"), "initial")
            self.assertEqual(list((root / "journal").glob("*.json")), [])

    def test_unowned_traversal_sensitive_and_generic_operation_sources_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "owned.txt").write_text("initial", encoding="utf-8")
            contracts = [active(item) for item in production_operations()]
            transport = ProductionToolTransport(request=self.request(root, contracts), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            for operation, arguments in (
                ("PROJECT_OWNED_FILE_READ", {"owned_file_id": "OWNED_9999"}),
                ("GENERIC_SHELL", {}), ("NATIVE_COMMAND_RUNTIME", {}), ("DIRECT_MCP_EFFECT", {}),
            ):
                with self.subTest(operation=operation), self.assertRaises(Exception):
                    transport.handle(ToolRequestEnvelope(operation, "TASK-4A-08",
                        "PRODUCTION_WORKER_TURN", arguments, f"CALL_{operation}"))
            self.assertEqual((root / "owned.txt").read_text(encoding="utf-8"), "initial")
        for unsafe in ("../escape", ".git/config", ".env", "credentials.json"):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                bad = self.request(root, []); bad["owned_files"] = [unsafe]
            with self.assertRaises(Exception):
                ProductionToolTransport(request=bad, workspace_root=root,
                                            journal_root=root / "journal", security_scan=lambda _: True)

    def test_same_run_write_resume_blocks_new_provider_call_id_duplicate(self):
        operations = production_operations()
        contracts = [active(item) for item in operations]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "owned.txt"; target.write_text("initial", encoding="utf-8")
            transport = ProductionToolTransport(request=self.request(root, contracts), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            first = transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "changed"},
                "CALL_1"))
            self.assertEqual(first.status, "COMPLETED")
            with self.assertRaises(Exception):
                transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "duplicate"},
                    "CALL_2"))
            self.assertEqual(target.read_text(encoding="utf-8"), "changed")
            self.assertEqual(len(list((root / "journal").glob("*.intent.json"))), 1)
            self.assertEqual(len(list((root / "journal").glob("*.receipt.json"))), 1)

    def test_proof97_crash_after_durable_write_resume_blocks_duplicate_effect(self):
        operations = production_operations()
        contracts = [proof97_active(item) for item in operations]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "owned.txt"; journal = root / "journal"
            target.write_text("before", encoding="utf-8")
            first = ProductionToolTransport(request=self.proof97_request(root, contracts), workspace_root=root,
                                            journal_root=journal, security_scan=lambda _: True)
            with self.assertRaisesRegex(RuntimeError, "injected crash after durable write"):
                first.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "proof97 first write"},
                    "CALL_FIRST"))
                raise RuntimeError("injected crash after durable write")
            restarted = ProductionToolTransport(request=self.proof97_request(root, contracts), workspace_root=root,
                                                journal_root=journal, security_scan=lambda _: True)
            with self.assertRaises(Exception):
                restarted.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "proof97 duplicate write"},
                    "CALL_AFTER_CRASH"))
            self.assertEqual(target.read_text(encoding="utf-8"), "proof97 first write")
            self.assertEqual(len(list(journal.glob("*.intent.json"))), 1)
            self.assertEqual(len(list(journal.glob("*.receipt.json"))), 1)
            self.assertEqual(len(restarted.governed_effect_evidence()), 1)
            verifier = verify_single_governed_write_effect(
                journal,
                active_write_contract=next(
                    item for item in restarted.contracts.values()
                    if item.operation_class_id == "PROJECT_OWNED_FILE_WRITE"
                ),
                expected_owned_scope=("owned.txt",),
                expected_scope_ref="owned.txt",
            )
            self.assertEqual(verifier["status"], "PASS")
            self.assertEqual(verifier["effect_count"], 1)
            intent = json.loads(next(journal.glob("*.intent.json")).read_text(encoding="utf-8"))
            identity = intent["identity"]
            self.assertEqual(identity["gate_id"], PROOF97_GATE)
            self.assertEqual(identity["lv_id"], PROOF97_LV)
            self.assertEqual(identity["run_id"], PROOF97_RUN)

    def test_dynamic_registry_can_be_closed_to_required_operation_subset(self):
        contracts = [active(item) for item in production_operations()]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = ProductionToolTransport(request=self.request(root, contracts), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            specs = transport.registry.dynamic_specs(("PROJECT_OWNED_FILE_WRITE",))
            self.assertEqual([item["name"] for item in specs], ["PROJECT_OWNED_FILE_WRITE"])
            self.assertIn("approved write effects", specs[0]["description"])
            self.assertIn("do not use native filesystem", specs[0]["description"])
            with self.assertRaises(Exception):
                transport.registry.dynamic_specs(("PROJECT_OWNED_FILE_WRITE", "PROJECT_OWNED_FILE_WRITE"))
            with self.assertRaises(Exception):
                transport.registry.dynamic_specs(("UNKNOWN_OPERATION",))

    def test_authorized_sensitive_result_blocks_after_one_effect_and_is_not_journaled_raw(self):
        operation = production_operations()[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "owned.txt").write_text("fixture", encoding="utf-8")
            transport = ProductionToolTransport(request=self.request(root, [active(operation)]), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: False)
            with self.assertRaises(Exception):
                transport.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_READ", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001"}, "CALL_1"))
            receipt = next((root / "journal").glob("*.receipt.json")).read_text(encoding="utf-8")
            self.assertNotIn("fixture", receipt)
            self.assertIn('"security_status":"BLOCK"', receipt)

    @unittest.skipUnless(os.environ.get("HARNESS_RUN_ACTUAL_CODEX_TRANSPORT") == "1",
                         "actual installed Codex broker integration is opt-in")
    def test_installed_codex_uses_dec007_active_broker_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "owned.txt").write_text("safe fixture", encoding="utf-8")
            contracts = [active(item) for item in production_operations()]
            transport = ProductionToolTransport(request=self.request(root, contracts), workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            result = transport.run(prompt=(
                "Use PROJECT_OWNED_FILE_READ exactly once with owned_file_id OWNED_0001, "
                "then finish without any other tool."), timeout=180)
            self.assertEqual(result["completion"], "COMPLETED")
            self.assertEqual(len(list((root / "journal").glob("*.intent.json"))), 1)
            self.assertEqual(len(list((root / "journal").glob("*.receipt.json"))), 1)
            self.assertEqual(result["registry"]["native_command_runtime_count"], 0)
            self.assertEqual(result["registry"]["native_file_runtime_count"], 0)
            self.assertEqual(result["registry"]["direct_mcp_effect_source_count"], 0)

    @unittest.skipUnless(os.environ.get("HARNESS_RUN_ACTUAL_CODEX_TRANSPORT") == "1",
                         "actual installed Codex duplicate-write proof is opt-in")
    def test_installed_codex_duplicate_write_after_restart_is_broker_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "owned.txt"; journal = root / "journal"
            target.write_text("before", encoding="utf-8")
            contracts = [proof97_active(item) for item in production_operations()]
            first = ProductionToolTransport(request=self.proof97_request(root, contracts), workspace_root=root,
                                            journal_root=journal, security_scan=lambda _: True)
            with self.assertRaisesRegex(RuntimeError, "injected crash after durable write"):
                first.handle(ToolRequestEnvelope("PROJECT_OWNED_FILE_WRITE", "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN", {"owned_file_id": "OWNED_0001", "content": "proof97 first write"},
                    "CALL_FIRST"))
                raise RuntimeError("injected crash after durable write")
            restarted = ProductionToolTransport(request=self.proof97_request(root, contracts), workspace_root=root,
                                                journal_root=journal, security_scan=lambda _: True)
            calls = []
            original = restarted.handle
            def handle(envelope):
                calls.append(envelope.operation_class_id)
                return original(envelope)
            restarted.handle = handle
            result = restarted.run(prompt=(
                "Call PROJECT_OWNED_FILE_WRITE exactly once with owned_file_id OWNED_0001 "
                "and content \"proof97 duplicate write\". Then finish."),
                timeout=90, dynamic_operation_class_ids=("PROJECT_OWNED_FILE_WRITE",))
            self.assertEqual(result["completion"], "BROKER_BLOCKED")
            self.assertEqual(calls, ["PROJECT_OWNED_FILE_WRITE"])
            self.assertEqual(target.read_text(encoding="utf-8"), "proof97 first write")
            self.assertEqual(len(list(journal.glob("*.intent.json"))), 1)
            self.assertEqual(len(list(journal.glob("*.receipt.json"))), 1)
            self.assertEqual(len(restarted.governed_effect_evidence()), 1)
            verifier = verify_single_governed_write_effect(
                journal,
                active_write_contract=next(
                    item for item in restarted.contracts.values()
                    if item.operation_class_id == "PROJECT_OWNED_FILE_WRITE"
                ),
                expected_owned_scope=("owned.txt",),
                expected_scope_ref="owned.txt",
            )
            self.assertEqual(verifier["status"], "PASS")
            self.assertEqual(verifier["effect_count"], 1)
            intent = json.loads(next(journal.glob("*.intent.json")).read_text(encoding="utf-8"))
            identity = intent["identity"]
            self.assertEqual(identity["project_id"], PROOF97_PROJECT)
            self.assertEqual(identity["gate_id"], PROOF97_GATE)
            self.assertEqual(identity["lv_id"], PROOF97_LV)
            self.assertEqual(identity["run_id"], PROOF97_RUN)
            self.assertEqual(identity["package_digest"], PROOF97_PACKAGE)
            self.assertEqual(identity["operation_class_id"], "PROJECT_OWNED_FILE_WRITE")


if __name__ == "__main__": unittest.main()

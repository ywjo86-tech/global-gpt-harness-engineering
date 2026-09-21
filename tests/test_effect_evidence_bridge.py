from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.codex_dynamic_transport import ToolRequestEnvelope
from runtime.orchestrator.effect_evidence_bridge import (
    EffectEvidenceBridgeError,
    collect_governed_write_effect_evidence,
    verify_single_governed_write_effect,
    verify_auto_effect_reconciliation,
)
from runtime.orchestrator.production_tool_transport import ProductionToolTransport
from runtime.orchestrator.gate_continuation_contract import GateContinuationContract
from runtime.orchestrator.tool_authorization import (
    activate_contract,
    build_dec007_approved_contracts,
)


PACKAGE = "a" * 64
PLAN = "b" * 64


def active_contracts():
    approved = build_dec007_approved_contracts(
        project_id="PROJECT_1",
        gate_id="GATE_1",
        lv_id="LV_1",
        run_id="RUN_1",
        canonical_plan_sha256=PLAN,
        owned_files=("owned.txt",),
    )
    return tuple(
        activate_contract(
            contract,
            package_binding_sha256=PACKAGE,
            authorized_decisions={"DEC-007": "USER_DECISION"},
        )
        for contract in approved
    )


def write_contract():
    return next(
        item
        for item in active_contracts()
        if item.operation_class_id == "PROJECT_OWNED_FILE_WRITE"
    )


def request():
    return {
        "project_id": "PROJECT_1",
        "run_id": "RUN_1",
        "gate_id": "GATE_1",
        "lv_id": "LV_1",
        "canonical_plan_sha256": PLAN,
        "owned_files": ["owned.txt"],
        "active_tool_authorization_contracts": [
            item.to_dict() for item in active_contracts()
        ],
    }


def continuation_contract(*, effect_policy: str, evidence_classes=("TEST_RESULT", "EFFECT_RECONCILIATION")):
    return GateContinuationContract.from_mapping({
        "schema_version": "orchestration.gate-continuation-contract.v1",
        "gate_id": "GATE_1",
        "continuation_policy": "AUTO_WITHIN_APPROVED_CONTRACT",
        "approved_base_head": "c" * 40,
        "source_lineage_policy": "APPROVED_DESCENDANT_CHAIN",
        "allowed_write_paths": ["owned.txt"],
        "forbidden_paths": [".git/"],
        "required_verifiers": ["UNITTEST"],
        "required_evidence_classes": list(evidence_classes),
        "commit_policy": "LOCAL_COMMIT_ALLOWED",
        "risk_classes": ["REPOSITORY_WRITE"],
        "approval_coverage_ref": "approval://test",
        "approval_coverage_digest": "d" * 64,
        "external_effect_policy": effect_policy,
        "runtime_migration_policy": "NO_RUNTIME_MIGRATION",
    })


class EffectEvidenceBridgeTests(unittest.TestCase):
    def _transport(self, root: Path, *, security_scan=lambda _: True):
        return ProductionToolTransport(
            request=request(),
            workspace_root=root,
            journal_root=root / "journal",
            security_scan=security_scan,
        )

    def test_write_projects_exact_governed_effect_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "changed"},
                    "CALL_WRITE_1",
                )
            )
            evidence = collect_governed_write_effect_evidence(
                root / "journal",
                active_write_contract=write_contract(),
                expected_owned_scope=("owned.txt",),
            )
            self.assertEqual(len(evidence), 1)
            item = evidence[0]
            self.assertEqual(item.operation, "PROJECT_OWNED_FILE_WRITE")
            self.assertEqual(item.scope_ref, "owned.txt")
            self.assertTrue(item.authorized)
            self.assertTrue(item.mutation_performed)
            self.assertTrue(item.security_passed)
            self.assertTrue(item.intent_receipt_consistent)
            self.assertEqual((root / "owned.txt").read_text(encoding="utf-8"), "changed")

    def test_directory_child_scope_projects_as_governed_effect_evidence(self):
        owned_files = ("android-app/",)
        approved = build_dec007_approved_contracts(
            project_id="PROJECT_1", gate_id="GATE_1", lv_id="LV_1", run_id="RUN_1",
            canonical_plan_sha256=PLAN, owned_files=owned_files,
        )
        active = tuple(activate_contract(
            contract, package_binding_sha256=PACKAGE, authorized_decisions={"DEC-007": "USER_DECISION"}
        ) for contract in approved)
        write = next(item for item in active if item.operation_class_id == "PROJECT_OWNED_FILE_WRITE")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "project_id": "PROJECT_1", "run_id": "RUN_1", "gate_id": "GATE_1", "lv_id": "LV_1",
                "canonical_plan_sha256": PLAN, "owned_files": list(owned_files),
                "active_tool_authorization_contracts": [item.to_dict() for item in active],
            }
            transport = ProductionToolTransport(request=payload, workspace_root=root,
                                                journal_root=root / "journal", security_scan=lambda _: True)
            transport.handle(ToolRequestEnvelope(
                "PROJECT_OWNED_FILE_WRITE", "TASK-4A-08", "PRODUCTION_WORKER_TURN",
                {"owned_file_id": "OWNED_0001", "relative_path": "src/main/Main.kt", "content": "class Main\n"},
                "CALL_DIR_WRITE",
            ))
            evidence = collect_governed_write_effect_evidence(
                root / "journal", active_write_contract=write, expected_owned_scope=owned_files,
            )
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].scope_ref, "android-app/src/main/Main.kt")
            self.assertTrue(evidence[0].mutation_performed)

    def test_read_is_not_promoted_to_mutation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_READ",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001"},
                    "CALL_READ_1",
                )
            )
            evidence = collect_governed_write_effect_evidence(
                root / "journal",
                active_write_contract=write_contract(),
                expected_owned_scope=("owned.txt",),
            )
            self.assertEqual(evidence, ())

    def test_receipt_intent_digest_tamper_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "changed"},
                    "CALL_WRITE_2",
                )
            )
            receipt_path = next((root / "journal").glob("*.receipt.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["intent_digest"] = "f" * 64
            receipt_path.write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaises(EffectEvidenceBridgeError) as caught:
                collect_governed_write_effect_evidence(
                    root / "journal",
                    active_write_contract=write_contract(),
                    expected_owned_scope=("owned.txt",),
                )
            self.assertEqual(
                caught.exception.reason_taxonomy,
                "EFFECT_EVIDENCE_RECEIPT_DRIFT",
            )

    def test_unowned_file_id_blocks_before_journal_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            with self.assertRaises(Exception):
                transport.handle(
                    ToolRequestEnvelope(
                        "PROJECT_OWNED_FILE_WRITE",
                        "TASK-4A-08",
                        "PRODUCTION_WORKER_TURN",
                        {"owned_file_id": "OWNED_9999", "content": "changed"},
                        "CALL_BAD_SCOPE",
                    )
                )
            self.assertEqual(list((root / "journal").glob("*.json")), [])
            self.assertEqual(
                (root / "owned.txt").read_text(encoding="utf-8"),
                "initial",
            )

    def test_blocked_write_intent_gets_bounded_terminal_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root, security_scan=lambda _: False)
            with self.assertRaises(Exception):
                transport.handle(
                    ToolRequestEnvelope(
                        "PROJECT_OWNED_FILE_WRITE",
                        "TASK-4A-08",
                        "PRODUCTION_WORKER_TURN",
                        {"owned_file_id": "OWNED_0001", "content": "blocked"},
                        "CALL_BLOCKED_WRITE",
                    )
                )
            self.assertEqual(
                len(list((root / "journal").glob("*.intent.json"))),
                1,
            )
            self.assertEqual(
                len(list((root / "journal").glob("*.receipt.json"))),
                1,
            )
            evidence = collect_governed_write_effect_evidence(
                root / "journal",
                active_write_contract=write_contract(),
                expected_owned_scope=("owned.txt",),
            )
            self.assertEqual(len(evidence), 1)
            self.assertFalse(evidence[0].security_passed)
            self.assertFalse(evidence[0].mutation_performed)

    def test_single_governed_write_verifier_passes_only_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "changed"},
                    "CALL_WRITE_VERIFY",
                )
            )
            result = verify_single_governed_write_effect(
                root / "journal",
                active_write_contract=write_contract(),
                expected_owned_scope=("owned.txt",),
                expected_scope_ref="owned.txt",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["effect_count"], 1)
            self.assertTrue(result["evidence_refs"])

    def test_single_governed_write_verifier_fails_wrong_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            transport = self._transport(root)
            transport.handle(
                ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE",
                    "TASK-4A-08",
                    "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "changed"},
                    "CALL_WRITE_VERIFY",
                )
            )
            result = verify_single_governed_write_effect(
                root / "journal",
                active_write_contract=write_contract(),
                expected_owned_scope=("owned.txt",),
                expected_scope_ref="other.txt",
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["reason_taxonomy"], "EFFECT_EVIDENCE_COUNT_OR_SCOPE_MISMATCH")


    def test_auto_no_external_effect_accepts_empty_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify_auto_effect_reconciliation(
                Path(directory) / "journal",
                contract=continuation_contract(effect_policy="NO_EXTERNAL_EFFECT", evidence_classes=("TEST_RESULT",)),
            )
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.retry_disposition, "NO_EFFECT")
            self.assertEqual(result.effect_count, 0)
            self.assertRegex(result.evidence_sha256, r"^[0-9a-f]{64}$")

    def test_auto_no_external_effect_blocks_any_effect_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            self._transport(root).handle(ToolRequestEnvelope(
                "PROJECT_OWNED_FILE_WRITE", "TASK-4A-08", "PRODUCTION_WORKER_TURN",
                {"owned_file_id": "OWNED_0001", "content": "changed"}, "CALL_NO_EFFECT_POLICY",
            ))
            result = verify_auto_effect_reconciliation(
                root / "journal",
                contract=continuation_contract(effect_policy="NO_EXTERNAL_EFFECT", evidence_classes=("TEST_RESULT",)),
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.reason_taxonomy, "UNEXPECTED_EFFECT_EVIDENCE")

    def test_auto_governed_effect_requires_exact_safe_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            self._transport(root).handle(ToolRequestEnvelope(
                "PROJECT_OWNED_FILE_WRITE", "TASK-4A-08", "PRODUCTION_WORKER_TURN",
                {"owned_file_id": "OWNED_0001", "content": "changed"}, "CALL_GOVERNED_AUTO",
            ))
            result = verify_auto_effect_reconciliation(
                root / "journal", contract=continuation_contract(effect_policy="GOVERNED_REPOSITORY_EFFECTS_ONLY"),
                active_write_contract=write_contract(), expected_owned_scope=("owned.txt",), expected_scope_ref="owned.txt",
            )
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.retry_disposition, "COMPLETED")
            self.assertEqual(result.effect_count, 1)

    def test_auto_governed_effect_blocks_begun_intent_without_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            self._transport(root).handle(ToolRequestEnvelope(
                "PROJECT_OWNED_FILE_WRITE", "TASK-4A-08", "PRODUCTION_WORKER_TURN",
                {"owned_file_id": "OWNED_0001", "content": "changed"}, "CALL_AMBIGUOUS_AUTO",
            ))
            next((root / "journal").glob("*.receipt.json")).unlink()
            result = verify_auto_effect_reconciliation(
                root / "journal", contract=continuation_contract(effect_policy="GOVERNED_REPOSITORY_EFFECTS_ONLY"),
                active_write_contract=write_contract(), expected_owned_scope=("owned.txt",), expected_scope_ref="owned.txt",
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.reason_taxonomy, "AMBIGUOUS_EFFECT_EVIDENCE")

    def test_auto_governed_effect_blocks_security_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owned.txt").write_text("initial", encoding="utf-8")
            with self.assertRaises(Exception):
                self._transport(root, security_scan=lambda _: False).handle(ToolRequestEnvelope(
                    "PROJECT_OWNED_FILE_WRITE", "TASK-4A-08", "PRODUCTION_WORKER_TURN",
                    {"owned_file_id": "OWNED_0001", "content": "blocked"}, "CALL_BLOCKED_AUTO",
                ))
            result = verify_auto_effect_reconciliation(
                root / "journal", contract=continuation_contract(effect_policy="GOVERNED_REPOSITORY_EFFECTS_ONLY"),
                active_write_contract=write_contract(), expected_owned_scope=("owned.txt",), expected_scope_ref="owned.txt",
            )
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.reason_taxonomy, "EFFECT_EVIDENCE_NOT_SAFE")


if __name__ == "__main__":
    unittest.main()

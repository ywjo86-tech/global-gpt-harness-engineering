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
)
from runtime.orchestrator.production_tool_transport import ProductionToolTransport
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

    def test_incomplete_write_intent_is_recovery_ambiguous(self):
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
                0,
            )
            with self.assertRaises(EffectEvidenceBridgeError) as caught:
                collect_governed_write_effect_evidence(
                    root / "journal",
                    active_write_contract=write_contract(),
                    expected_owned_scope=("owned.txt",),
                )
            self.assertEqual(
                caught.exception.reason_taxonomy,
                "EFFECT_EVIDENCE_RECOVERY_AMBIGUOUS",
            )

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


if __name__ == "__main__":
    unittest.main()

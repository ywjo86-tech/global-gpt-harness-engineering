from __future__ import annotations

import ast
import inspect
import unittest

from runtime.ai_office import foundry
from runtime.ai_office.foundry import (
    PROJECT_DEFINITION_SCHEMA_V1,
    FoundryError,
    OfficeProjectDefinitionV1,
    advance_lifecycle,
    create_operating_contract,
    create_scaffold_intent,
)

DIGEST = "a" * 64


class AIOfficeFoundryTest(unittest.TestCase):
    def definition(self, target="/workspace/project/office-a"):
        return OfficeProjectDefinitionV1(
            PROJECT_DEFINITION_SCHEMA_V1,
            "office-project-001",
            "CEO",
            target,
            "/workspace/project",
            "requirement:approved",
            "context:approved",
            "template:approved",
            DIGEST,
            ("policy:office",),
        )
    def test_019_definition_contract_and_scaffold_intent_are_versioned_and_effect_free(self) -> None:
        definition = self.definition()
        contract = create_operating_contract(
            definition,
            governance_decision_ref="governance:allow-001",
            allowed_scaffold_scope=("runtime/office_a", "tests/office_a"),
        )
        intent = create_scaffold_intent(
            contract,
            intended_paths=("runtime/office_a/main.py", "tests/office_a/test_main.py"),
            expected_changes=("create runtime module", "create test module"),
            validation_refs=("test:unit",),
        )
        self.assertEqual(contract.lifecycle_state, "GOVERNED")
        self.assertEqual(len(intent.intent_digest), 64)
        self.assertEqual(advance_lifecycle("GOVERNED", "SCAFFOLD_PENDING"), "SCAFFOLD_PENDING")

    def test_019_sibling_root_and_scope_escape_are_rejected(self) -> None:
        with self.assertRaises(FoundryError):
            self.definition("/workspace/other-project")
        contract = create_operating_contract(
            self.definition(), governance_decision_ref="governance:allow-001",
            allowed_scaffold_scope=("runtime/office_a",),
        )
        with self.assertRaises(FoundryError):
            create_scaffold_intent(
                contract, intended_paths=("../escape.py",),
                expected_changes=("escape",), validation_refs=("test:unit",),
            )
    def test_019_foundry_contains_no_direct_filesystem_or_git_effects(self) -> None:
        tree = ast.parse(inspect.getsource(foundry))
        imports = []
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    calls.append(fn.id)
                elif isinstance(fn, ast.Attribute):
                    calls.append(fn.attr)
        self.assertFalse({"os", "subprocess", "shutil"}.intersection(imports))
        self.assertFalse({"mkdir", "write_text", "write_bytes", "unlink", "replace", "run", "Popen"}.intersection(calls))


if __name__ == "__main__":
    unittest.main()

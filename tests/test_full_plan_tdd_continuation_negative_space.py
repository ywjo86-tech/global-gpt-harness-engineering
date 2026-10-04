import ast
import unittest
from pathlib import Path


class TDDContinuationNegativeSpaceTests(unittest.TestCase):
    def test_continuation_module_has_no_execution_or_approval_authority(self):
        path = Path("runtime/orchestrator/implementation_continuation.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_import_fragments = ("provider_router", "mprf", "full_mcp", "production_worker", "gate_approval")
        forbidden_calls = {"route_request", "execute_gate", "register_job", "resume_wait", "subprocess", "system", "Popen"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(any(part in alias.name for part in forbidden_import_fragments), alias.name)
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertFalse(any(part in module for part in forbidden_import_fragments), module)
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                self.assertNotIn(name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()

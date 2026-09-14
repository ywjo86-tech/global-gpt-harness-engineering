from __future__ import annotations

import unittest

from poc.graphify.contracts import CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES
from poc.graphify.current_repository_boundary import verify_current_repository_boundary


class CurrentRepositoryBoundaryTests(unittest.TestCase):
    def test_approved_capabilities_pass(self) -> None:
        record = verify_current_repository_boundary(CURRENT_REPOSITORY_INTELLIGENCE_CAPABILITIES)
        self.assertTrue(record["verified"])
        self.assertEqual(record["unsupported_capabilities"], [])

    def test_memory_or_execution_capability_fails(self) -> None:
        record = verify_current_repository_boundary([
            "symbol_lookup", "memory_persistence", "execution_backend_control"
        ])
        self.assertFalse(record["verified"])
        self.assertIn("memory_persistence", record["forbidden_capabilities"])
        self.assertIn("execution_backend_control", record["forbidden_capabilities"])


if __name__ == "__main__":
    unittest.main()

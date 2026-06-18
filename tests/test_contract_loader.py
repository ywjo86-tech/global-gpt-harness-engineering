from __future__ import annotations

import unittest

from runtime.orchestrator.contract_loader import load_contract

from tests.helpers import cloned_sample_project


class ContractLoaderTest(unittest.TestCase):
    def test_loads_required_project_contract_files(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            self.assertEqual(contract.current_phase, "runtime orchestration smoke test")
            self.assertEqual(contract.missing_files, [])
            self.assertIn("Documentation Stabilization", contract.development_plan_text)


if __name__ == "__main__":
    unittest.main()

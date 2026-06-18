from __future__ import annotations

from dataclasses import replace
import unittest

from runtime.orchestrator.contract_loader import load_contract
from runtime.orchestrator.state_store import StateStore
from runtime.orchestrator.task_router import route_tasks

from tests.helpers import cloned_sample_project


class TaskRouterTest(unittest.TestCase):
    def test_routes_documentation_and_qa_workers(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            state = StateStore(project).state
            tasks = route_tasks(contract, state)
            agents = [task.assigned_agent for task in tasks]
            self.assertGreaterEqual(len(tasks), 3)
            self.assertIn("documentation_agent", agents)
            self.assertIn("qa_reviewer_agent", agents)

    def test_routes_multiple_general_sections_without_deduping_agents(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            expanded_plan = contract.development_plan_text + """

### Documentation Follow-up
- Update the handoff summary and related docs.

### QA Follow-up
- Add another validation pass for the same project slice.

### Release Handoff
- Prepare the release notes and milestone summary.

### Implementation Refactor
- Refine the runtime execution module and routing layer.
"""
            contract = replace(contract, development_plan_text=expanded_plan)
            state = StateStore(project).state
            tasks = route_tasks(contract, state)
            agents = [task.assigned_agent for task in tasks]
            self.assertGreaterEqual(len(tasks), 3)
            self.assertGreaterEqual(agents.count("documentation_agent"), 2)
            self.assertGreaterEqual(agents.count("qa_reviewer_agent"), 1)
            self.assertGreaterEqual(agents.count("implementation_agent"), 1)


if __name__ == "__main__":
    unittest.main()

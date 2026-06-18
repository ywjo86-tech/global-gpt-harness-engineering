from __future__ import annotations

import re
from dataclasses import dataclass

from .approval_gate import classify_task
from .schemas import ExecutionContract, RuntimeState, TaskSlice


@dataclass(slots=True)
class SectionPlan:
    title: str
    body: str


SECTION_PATTERNS = [
    ("documentation_agent", ["documentation", "docs", "markdown", "readme", "log", "state", "summary", "overview", "handoff", "workflow", "milestone", "release"]),
    ("qa_reviewer_agent", ["qa", "quality", "validation", "test", "gate", "review", "readiness", "check", "verify", "acceptance", "criteria"]),
    ("implementation_agent", ["implementation", "implement", "runtime", "code", "feature", "build", "executor", "dispatch", "module", "refactor"]),
]


def _extract_sections(plan_text: str) -> list[SectionPlan]:
    sections: list[SectionPlan] = []
    current_title = "Overview"
    current_body: list[str] = []
    for line in plan_text.splitlines():
        if re.match(r"^#{1,3}\s+", line):
            if current_body:
                sections.append(SectionPlan(current_title, "\n".join(current_body).strip()))
            current_title = re.sub(r"^#{1,3}\s+", "", line).strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        sections.append(SectionPlan(current_title, "\n".join(current_body).strip()))
    return [section for section in sections if section.body or section.title]


def _match_agent(section: SectionPlan) -> str | None:
    haystack = f"{section.title}\n{section.body}".lower()
    for agent_name, keywords in SECTION_PATTERNS:
        if any(keyword in haystack for keyword in keywords):
            return agent_name
    return None


def _build_task(contract: ExecutionContract, state: RuntimeState, thread_id: str, agent_name: str, section: SectionPlan) -> TaskSlice:
    if agent_name == "documentation_agent":
        editable_scope = [
            "docs/",
            "logs/",
        ]
        forbidden_scope = [
            "runtime/",
            ".claude/",
        ]
    elif agent_name == "qa_reviewer_agent":
        editable_scope = [
            "logs/",
            "docs/",
        ]
        forbidden_scope = [
            "runtime code",
            ".claude/",
        ]
    else:
        editable_scope = [
            "runtime/",
        ]
        forbidden_scope = [
            ".claude/",
        ]

    task = TaskSlice(
        thread_id=thread_id,
        assigned_agent=agent_name,
        input=f"{section.title}\n\n{section.body}",
        expected_output=f"{agent_name} review notes and handoff summary",
        validation_criteria=[
            "Output is saved to a per-thread handoff file",
            "Findings are explicit",
            "Scope remains bounded",
        ],
        editable_scope=editable_scope,
        forbidden_scope=forbidden_scope,
        merge_point="fanin",
        status="pending",
    )
    assessment = classify_task(task, contract.paths.project_root)
    task.risk_class = assessment.classification
    return task


def route_tasks(contract: ExecutionContract, state: RuntimeState) -> list[TaskSlice]:
    sections = _extract_sections(contract.development_plan_text)
    planned: list[TaskSlice] = []
    thread_index = 1

    for section in sections:
        agent_name = _match_agent(section)
        if not agent_name:
            continue
        planned.append(_build_task(contract, state, f"T{thread_index}", agent_name, section))
        thread_index += 1

    if not planned:
        overview_section = SectionPlan("Overview", contract.development_plan_text[:1200])
        planned.append(_build_task(contract, state, "T1", "documentation_agent", overview_section))
        planned.append(_build_task(contract, state, "T2", "qa_reviewer_agent", overview_section))

    return planned

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import TaskSlice


GENERAL = "general"
CAUTION = "caution"
DANGEROUS = "dangerous"


@dataclass(slots=True)
class ApprovalAssessment:
    classification: str
    reason: str
    matched_rules: list[str] = field(default_factory=list)


CAUTION_TOKENS = [
    "AGENTS.md",
    ".gitignore",
    ".agents/skills/",
    ".codex/agents/",
    "docs/harness/",
    "git add",
    "git commit",
    "shared rule",
    "common-template",
]

DANGEROUS_TOKENS = [
    "git push",
    "force push",
    "git reset",
    "git rebase",
    "git clean",
    "delete",
    "package install",
    "external network",
    "api key",
    "token",
    "password",
    "secret",
    ".git/",
    "outside workspace",
]


def classify_task(task: TaskSlice | dict[str, object], project_root: str | None = None) -> ApprovalAssessment:
    if isinstance(task, TaskSlice):
        payload = task.as_request_payload()
    else:
        payload = dict(task)

    scope_haystack = " ".join(
        [
            " ".join(payload.get("editable_scope", []) or []),
            " ".join(payload.get("forbidden_scope", []) or []),
        ]
    ).lower()
    haystack = " ".join(
        [
            str(payload.get("thread_id", "")),
            str(payload.get("input", "")),
            str(payload.get("expected_output", "")),
        ]
    ).lower()
    scope = [str(item) for item in payload.get("editable_scope", []) or []]
    matched_rules: list[str] = []

    if project_root:
        normalized_root = str(project_root).replace("\\", "/").rstrip("/")
        for item in scope:
            normalized_item = item.replace("\\", "/")
            if normalized_item.startswith("..") or (":/" in normalized_item and not normalized_item.lower().startswith(normalized_root.lower())):
                matched_rules.append("workspace-outside-scope")
                return ApprovalAssessment(DANGEROUS, "Task touches files outside the current workspace.", matched_rules)

    for token in DANGEROUS_TOKENS:
        if token.lower() in haystack or token.lower() in scope_haystack:
            matched_rules.append(token)

    if matched_rules:
        return ApprovalAssessment(DANGEROUS, "Task contains dangerous work items.", matched_rules)

    for token in CAUTION_TOKENS:
        if token.lower() in scope_haystack:
            matched_rules.append(token)

    if matched_rules:
        return ApprovalAssessment(CAUTION, "Task contains caution work items.", matched_rules)

    return ApprovalAssessment(GENERAL, "Task is within general work scope.", [])


def approval_prompt_for(classification: str) -> str:
    if classification == CAUTION:
        return "승인"
    if classification == DANGEROUS:
        return "위험 확인 후 승인"
    return ""

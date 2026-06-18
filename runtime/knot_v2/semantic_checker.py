from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


STALE_MARKERS = [
    "tbd",
    "todo",
    "placeholder",
    "to be decided",
    "later",
    "deferred",
    "not started",
    "draft",
]

COMPLETE_MARKERS = [
    "completed",
    "complete",
    "done",
    "shipped",
    "approved",
    "accepted",
    "ready",
    "closed",
    "finished",
]

ACTIVE_MARKERS = [
    "in progress",
    "working",
    "ongoing",
    "reviewing",
    "implementing",
    "preparing",
]

BLOCKED_MARKERS = [
    "blocked",
    "no-go",
    "deferred",
    "not started",
    "pending",
    "paused",
    "hold",
]

MISLEADING_SUMMARY_MARKERS = [
    "looks good",
    "looks fine",
    "probably ready",
    "likely ready",
    "seems ready",
    "probably done",
    "seems done",
    "should be fine",
    "should be okay",
    "all good",
    "good to go",
    "ready soon",
    "mostly done",
    "almost done",
]

CONDITIONAL_DECISION_MARKERS = [
    "conditional go",
    "approved with conditions",
    "go with conditions",
    "accepted with conditions",
]

GO_DECISION_MARKERS = [
    "go",
    "approved",
    "accepted",
]

NEGATIVE_DECISION_MARKERS = [
    "no-go",
    "rejected",
    "blocked",
    "deferred",
    "hold",
]


def _normalize_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _extract_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)")
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _extract_links(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _relpath_token(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _page_kind(relative_path: str) -> str:
    if relative_path.startswith("wiki/projects/"):
        return "project"
    if relative_path.startswith("wiki/decisions/"):
        return "decision"
    if relative_path.startswith("wiki/concepts/"):
        return "concept"
    if relative_path.startswith("indexes/"):
        return "index"
    return "other"


def _decision_drift_severity(page_kind: str, related_page_kind: str | None = None) -> str:
    kinds = {page_kind}
    if related_page_kind:
        kinds.add(related_page_kind)
    if "project" in kinds:
        return "high"
    if "decision" in kinds:
        return "medium"
    if kinds & {"concept", "index"}:
        return "low"
    return "medium"


def _handoff_drift_severity(page_kind: str, related_page_kind: str | None = None) -> str:
    kinds = {page_kind}
    if related_page_kind:
        kinds.add(related_page_kind)
    if "project" in kinds:
        return "high"
    if "decision" in kinds:
        return "medium"
    if kinds & {"concept", "index"}:
        return "low"
    return "medium"


def _contradiction_severity(page_kind: str, related_page_kind: str | None = None) -> str:
    kinds = {page_kind}
    if related_page_kind:
        kinds.add(related_page_kind)
    if "project" in kinds:
        return "high"
    if "decision" in kinds:
        return "medium"
    if kinds & {"concept", "index"}:
        return "low"
    return "medium"


def _merge_candidate_severity(page_kinds: Iterable[str]) -> str:
    kinds = set(page_kinds)
    if "project" in kinds:
        return "high"
    if "decision" in kinds:
        return "medium"
    if kinds & {"concept", "index"}:
        return "low"
    return "medium"


def _stale_status_severity(page_kind: str) -> str:
    if page_kind == "project":
        return "high"
    if page_kind == "decision":
        return "medium"
    if page_kind in {"concept", "index"}:
        return "low"
    return "medium"


def _handoff_quality_severity(page_kind: str) -> str:
    if page_kind == "project":
        return "high"
    if page_kind == "decision":
        return "medium"
    if page_kind in {"concept", "index"}:
        return "low"
    return "medium"


def _misleading_summary_severity(page_kind: str) -> str:
    if page_kind == "project":
        return "high"
    if page_kind == "decision":
        return "medium"
    if page_kind in {"concept", "index"}:
        return "low"
    return "medium"


def _coverage_gap_severity(page_kind: str, gap_kind: str | None = None) -> str:
    if gap_kind == "decision_section" and page_kind == "decision":
        return "high"
    if gap_kind == "current_status" and page_kind == "project":
        return "high"
    if page_kind == "project":
        return "high"
    if page_kind == "decision":
        return "medium"
    if page_kind in {"concept", "index"}:
        return "low"
    return "medium"


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _status_signal(text: str) -> str:
    if _contains_any(text, COMPLETE_MARKERS):
        return "complete"
    if _contains_any(text, BLOCKED_MARKERS):
        return "blocked"
    if _contains_any(text, ACTIVE_MARKERS):
        return "active"
    return "unknown"


def _decision_state(text: str) -> str:
    if _contains_any(text, CONDITIONAL_DECISION_MARKERS):
        return "conditional_go"
    if _contains_any(text, GO_DECISION_MARKERS):
        return "go"
    if _contains_any(text, NEGATIVE_DECISION_MARKERS):
        return "no_go"
    return "unknown"


def _has_condition_language(text: str) -> bool:
    return _contains_any(
        text,
        [
            "condition",
            "conditional",
            "follow-up",
            "follow up",
            "deferred item",
            "unless",
            "pending review",
            "subject to",
            "caveat",
        ],
    )


def _has_semantic_conflict(left: str, right: str) -> bool:
    conflict_pairs = {
        ("complete", "blocked"),
        ("complete", "active"),
        ("blocked", "complete"),
        ("blocked", "active"),
        ("active", "complete"),
        ("active", "blocked"),
    }
    return (left, right) in conflict_pairs


@dataclass(slots=True)
class SemanticFinding:
    finding_id: str
    finding_type: str
    severity: str
    pages: list[str]
    evidence: list[str]
    why_it_matters: str
    suggested_action: str
    human_review_required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SemanticReport:
    scan_scope: str
    pages_reviewed: list[str]
    findings: list[SemanticFinding] = field(default_factory=list)
    contradiction_findings: list[str] = field(default_factory=list)
    handoff_drift_findings: list[str] = field(default_factory=list)
    handoff_quality_findings: list[str] = field(default_factory=list)
    decision_drift_findings: list[str] = field(default_factory=list)
    misleading_summary_findings: list[str] = field(default_factory=list)
    confirmed_semantic_risks: list[str] = field(default_factory=list)
    merge_candidates: list[str] = field(default_factory=list)
    stale_status_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scan_scope": self.scan_scope,
            "pages_reviewed": list(self.pages_reviewed),
            "findings": [finding.to_dict() for finding in self.findings],
            "contradiction_findings": list(self.contradiction_findings),
            "handoff_drift_findings": list(self.handoff_drift_findings),
            "handoff_quality_findings": list(self.handoff_quality_findings),
            "decision_drift_findings": list(self.decision_drift_findings),
            "misleading_summary_findings": list(self.misleading_summary_findings),
            "confirmed_semantic_risks": list(self.confirmed_semantic_risks),
            "merge_candidates": list(self.merge_candidates),
            "stale_status_findings": list(self.stale_status_findings),
        }

    def render_markdown(self) -> str:
        lines = [
            "# Knot v2 Semantic Report",
            "",
            f"Scan scope: {self.scan_scope}",
            f"Pages reviewed: {', '.join(self.pages_reviewed) or 'none'}",
            "",
            "Findings",
        ]
        if self.findings:
            for finding in self.findings:
                lines.extend(
                    [
                        f"- {finding.finding_id}: {finding.finding_type} ({finding.severity})",
                        f"  - pages: {', '.join(finding.pages)}",
                        f"  - evidence: {', '.join(finding.evidence)}",
                        f"  - why_it_matters: {finding.why_it_matters}",
                        f"  - suggested_action: {finding.suggested_action}",
                    ]
                )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "Confirmed Semantic Risks",
                ", ".join(self.confirmed_semantic_risks) or "none",
                "",
                "Contradiction Findings",
                ", ".join(self.contradiction_findings) or "none",
                "",
                "Handoff Drift Findings",
                ", ".join(self.handoff_drift_findings) or "none",
                "",
                "Handoff Quality Findings",
                ", ".join(self.handoff_quality_findings) or "none",
                "",
                "Decision Drift Findings",
                ", ".join(self.decision_drift_findings) or "none",
                "",
                "Misleading Summary Findings",
                ", ".join(self.misleading_summary_findings) or "none",
                "",
                "Merge Candidates",
                ", ".join(self.merge_candidates) or "none",
                "",
                "Stale Status Findings",
                ", ".join(self.stale_status_findings) or "none",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"


class KnotV2SemanticChecker:
    def discover_pages(self, vault_root: str | Path, scope: Iterable[str | Path] | None = None) -> list[Path]:
        root = Path(vault_root)
        candidates = sorted(
            [*root.joinpath("wiki").rglob("*.md"), *root.joinpath("indexes").rglob("*.md")]
        )
        if scope is None:
            return candidates
        scoped: list[Path] = []
        scope_paths = {Path(item).resolve() for item in scope}
        for path in candidates:
            resolved = path.resolve()
            if resolved in scope_paths or any(str(resolved).endswith(str(item)) for item in scope_paths):
                scoped.append(path)
        return scoped

    def scan(self, vault_root: str | Path, scope: Iterable[str | Path] | None = None) -> SemanticReport:
        root = Path(vault_root)
        pages = self.discover_pages(root, scope)
        page_data: list[dict[str, object]] = []
        findings: list[SemanticFinding] = []
        pages_reviewed = [_relpath_token(path, root) for path in pages]

        for path in pages:
            text = path.read_text(encoding="utf-8")
            title = _extract_title(text, path)
            current_status = _extract_section(text, "Current Status")
            history = _extract_section(text, "History")
            open_questions = _extract_section(text, "Open Questions")
            handoff_summary = _extract_section(text, "Handoff Summary")
            next_step = _extract_section(text, "Next Step")
            decision_text = _extract_section(text, "Decision")
            related = _extract_section(text, "Related Pages")
            links = _extract_links(text)
            current_signal = _status_signal(current_status)
            history_signal = _status_signal(history)
            handoff_signal = _status_signal(handoff_summary)
            next_signal = _status_signal(next_step)
            decision_state = _decision_state(f"{decision_text}\n{current_status}\n{history}")
            condition_signal = _has_condition_language(
                f"{decision_text}\n{current_status}\n{history}\n{handoff_summary}\n{next_step}"
            )
            page_data.append(
                {
                    "path": path,
                    "relative_path": _relpath_token(path, root),
                    "page_kind": _page_kind(_relpath_token(path, root)),
                    "title": title,
                    "normalized_title": _normalize_title(title),
                    "text": text,
                    "current_status": current_status,
                    "history": history,
                    "open_questions": open_questions,
                    "handoff_summary": handoff_summary,
                    "next_step": next_step,
                    "decision_text": decision_text,
                    "related": related,
                    "links": links,
                    "status_signal": current_signal or _status_signal(f"{history}\n{handoff_summary}\n{next_step}"),
                    "current_signal": current_signal,
                    "history_signal": history_signal,
                    "handoff_signal": handoff_signal,
                    "next_signal": next_signal,
                    "decision_state": decision_state,
                    "condition_signal": condition_signal,
                }
            )

        by_normalized: dict[str, list[dict[str, object]]] = {}
        for item in page_data:
            by_normalized.setdefault(item["normalized_title"], []).append(item)

        for index, (normalized, entries) in enumerate(by_normalized.items(), start=1):
            if len(entries) > 1:
                page_names = [str(entry["relative_path"]) for entry in entries]
                merged_kinds = [str(entry["page_kind"]) for entry in entries]
                findings.append(
                    SemanticFinding(
                        finding_id=f"merge-{index}",
                        finding_type="merge_candidate",
                        severity=_merge_candidate_severity(merged_kinds),
                        pages=page_names,
                        evidence=[f"duplicate normalized title: {entries[0]['title']}"],
                        why_it_matters="Pages with the same normalized title may represent the same topic.",
                        suggested_action="Review the duplicate pages and decide whether to merge or differentiate them.",
                    )
                )

        for index, item in enumerate(page_data, start=1):
            page_name = str(item["relative_path"])
            current_status = str(item["current_status"]).strip()
            history = str(item["history"]).strip()
            handoff_summary = str(item["handoff_summary"]).strip()
            next_step = str(item["next_step"]).strip()
            decision_text = str(item["decision_text"]).strip()
            page_kind = str(item["page_kind"])
            current_signal = str(item["current_signal"])
            history_signal = str(item["history_signal"])
            handoff_signal = str(item["handoff_signal"])
            next_signal = str(item["next_signal"])
            decision_state = str(item["decision_state"])
            condition_signal = bool(item["condition_signal"])
            if page_kind == "project":
                if not current_status:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"coverage-{index}",
                            finding_type="coverage_gap",
                            severity=_coverage_gap_severity(page_kind, "current_status"),
                            pages=[page_name],
                            evidence=["Current Status section missing or empty"],
                            why_it_matters="Project pages need a current state to drive orchestration and handoff review.",
                            suggested_action="Add a concise Current Status section with the latest confirmed state.",
                        )
                    )
            elif page_kind == "decision":
                if not decision_text:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decision-coverage-{index}",
                            finding_type="coverage_gap",
                            severity=_coverage_gap_severity(page_kind, "decision_section"),
                            pages=[page_name],
                            evidence=["Decision section missing or empty"],
                            why_it_matters="Decision pages need an explicit decision record to prevent drift.",
                            suggested_action="Add a Decision section that states the outcome in plain language.",
                        )
                    )
                elif decision_state == "conditional_go" and not condition_signal:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decision-conditional-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Decision text '{decision_text}' lacks condition language"],
                            why_it_matters="Conditional approvals should state the condition or deferred item that keeps the work from being a plain GO.",
                            suggested_action="Add the condition, follow-up item, or acceptance constraint directly in the decision record.",
                        )
                    )
            elif page_kind == "concept":
                if decision_text:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"concept-decision-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Concept page contains an operational Decision section"],
                            why_it_matters="Concept pages should stay descriptive instead of carrying operational approval language.",
                            suggested_action="Move the decision to a project or decision page and leave the concept page explanatory.",
                        )
                    )
                if handoff_summary and _contains_any(
                    handoff_summary,
                    ["ready for handoff", "ready to hand off", "blocked", "pending", "deferred", "continue", "implement"],
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"concept-handoff-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Concept page contains handoff language"],
                            why_it_matters="Concept pages should not look like active execution handoff records.",
                            suggested_action="Move execution handoff language to the owning project page.",
                        )
                    )
                if next_step and _contains_any(next_step, ["continue", "implement", "resume", "handoff", "close"]):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"concept-next-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Concept page contains execution Next Step language"],
                            why_it_matters="Concept pages should not carry forward-looking implementation instructions.",
                            suggested_action="Keep the concept page descriptive and move implementation steps to the project page.",
                        )
                    )
            elif page_kind == "index":
                if decision_text:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"index-decision-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Index page contains an operational Decision section"],
                            why_it_matters="Index pages should remain navigational and not encode approval state.",
                            suggested_action="Move the decision to a decision record and keep the index as a map.",
                        )
                    )
                if handoff_summary:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"index-handoff-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Index page contains handoff summary language"],
                            why_it_matters="Index pages should point to pages, not narrate execution handoffs.",
                            suggested_action="Move handoff language into the relevant project or decision page.",
                        )
                    )
                if next_step:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"index-next-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=["Index page contains Next Step language"],
                            why_it_matters="Index pages should not read like active work trackers.",
                            suggested_action="Move next-step language to the owning project page.",
                        )
                    )
            stale_hits = [marker for marker in STALE_MARKERS if marker in current_status.lower()]
            if stale_hits:
                finding = SemanticFinding(
                    finding_id=f"stale-{index}",
                    finding_type="stale_status",
                    severity=_stale_status_severity(page_kind),
                    pages=[page_name],
                    evidence=[f"stale markers: {', '.join(stale_hits)}"],
                    why_it_matters="The page may still describe provisional or outdated state.",
                    suggested_action="Replace provisional wording with the latest confirmed state or move it to History.",
                )
                findings.append(finding)
            if current_status and "completed" in current_status.lower() and not history:
                findings.append(
                    SemanticFinding(
                        finding_id=f"history-{index}",
                        finding_type="handoff_quality_issue",
                        severity=_handoff_quality_severity(page_kind),
                        pages=[page_name],
                        evidence=["Completed page without History section"],
                        why_it_matters="Completed pages should preserve what changed and what was superseded.",
                        suggested_action="Add a short History section or decision note.",
                    )
                )
            if current_signal != "unknown" and history_signal != "unknown" and _has_semantic_conflict(current_signal, history_signal):
                findings.append(
                    SemanticFinding(
                        finding_id=f"status-history-{index}",
                        finding_type="contradiction",
                        severity=_contradiction_severity(page_kind),
                        pages=[page_name],
                        evidence=[
                            f"Current Status signal={current_signal}",
                            f"History signal={history_signal}",
                        ],
                        why_it_matters="A page should not describe itself as both current and historical conflict.",
                        suggested_action="Align Current Status and History or move the older state into History only.",
                    )
                )
            if current_signal != "unknown" and handoff_signal != "unknown" and _has_semantic_conflict(current_signal, handoff_signal):
                findings.append(
                    SemanticFinding(
                        finding_id=f"status-handoff-{index}",
                        finding_type="handoff_drift",
                        severity=_handoff_drift_severity(page_kind),
                        pages=[page_name],
                        evidence=[
                            f"Current Status signal={current_signal}",
                            f"Handoff Summary signal={handoff_signal}",
                        ],
                        why_it_matters="The current page state and handoff summary point in different directions.",
                        suggested_action="Align Current Status with the handoff summary or preserve the prior state in History.",
                    )
                )
            if current_signal != "unknown" and next_signal != "unknown" and _has_semantic_conflict(current_signal, next_signal):
                findings.append(
                    SemanticFinding(
                        finding_id=f"status-next-{index}",
                        finding_type="handoff_drift",
                        severity=_handoff_drift_severity(page_kind),
                        pages=[page_name],
                        evidence=[
                            f"Current Status signal={current_signal}",
                            f"Next Step signal={next_signal}",
                        ],
                        why_it_matters="The current state and next step imply different readiness states.",
                        suggested_action="Align the page status with the next step or move the older action into History.",
                    )
                )
            if page_kind == "decision" and "decision" not in current_status.lower():
                findings.append(
                    SemanticFinding(
                        finding_id=f"decision-{index}",
                        finding_type="decision_drift",
                        severity=_decision_drift_severity(page_kind),
                        pages=[page_name],
                        evidence=["Decision page without explicit decision text in Current Status"],
                        why_it_matters="Decision pages should make the decision outcome easy to inspect.",
                        suggested_action="State the decision in Current Status or an explicit Decision section.",
                    )
                )
            if page_name.startswith("wiki/") and not item["open_questions"] and "open" in current_status.lower():
                findings.append(
                    SemanticFinding(
                        finding_id=f"question-{index}",
                        finding_type="handoff_quality_issue",
                        severity=_handoff_quality_severity(page_kind),
                        pages=[page_name],
                        evidence=["Open status with no Open Questions section"],
                        why_it_matters="Open work should say what still needs confirmation.",
                        suggested_action="Add an Open Questions section or resolve the open status.",
                    )
                )

            if handoff_summary and _contains_any(handoff_summary, MISLEADING_SUMMARY_MARKERS):
                if current_signal in {"active", "blocked"} or bool(item["open_questions"]):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"misleading-{index}",
                            finding_type="misleading_summary",
                            severity=_misleading_summary_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Handoff Summary uses vague readiness language: '{handoff_summary}'"],
                            why_it_matters="Summaries should not sound more certain than the current status or open questions allow.",
                            suggested_action="Replace vague readiness language with a confirmed summary that matches the page state.",
                        )
                    )

            if handoff_summary and next_step:
                handoff_text = f"{handoff_summary}\n{next_step}".lower()
                if _contains_any(handoff_text, ["ready for handoff", "ready to hand off", "ready to close"]) and _contains_any(
                    next_step, ["continue", "implement", "keep working", "resume"]
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"handoff-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[
                                f"Handoff summary says '{handoff_summary}' but next step says '{next_step}'",
                            ],
                            why_it_matters="The handoff message and next action point in different directions.",
                            suggested_action="Align the handoff summary and next step, or move one of them into History.",
                        )
                    )
                elif _contains_any(handoff_text, ["pending", "blocked", "deferred"]) and _contains_any(
                    next_step, ["ready", "handoff", "close", "complete"]
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"handoff-{index}",
                            finding_type="handoff_drift",
                            severity=_handoff_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[
                                f"Handoff summary says '{handoff_summary}' but next step says '{next_step}'",
                            ],
                            why_it_matters="The handoff message and next action imply different readiness states.",
                            suggested_action="Make the readiness state explicit and consistent across sections.",
                        )
                    )

            if page_kind == "decision":
                if decision_state == "go" and (
                    _contains_any(current_status, BLOCKED_MARKERS) or _contains_any(history, BLOCKED_MARKERS)
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Decision '{decision_text}' conflicts with current status '{current_status}'"],
                            why_it_matters="Decision pages should not read as GO while the page status still says blocked.",
                            suggested_action="Align the decision state with the page status or record the reason for the mismatch.",
                        )
                    )
                elif decision_state == "conditional_go" and _contains_any(current_status, BLOCKED_MARKERS) and not condition_signal:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-conditional-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Decision '{decision_text}' lacks condition language while status is '{current_status}'"],
                            why_it_matters="Conditional GO should name the condition or follow-up item that keeps the page from being a plain blocked state.",
                            suggested_action="Add the condition language or move the conditional note into History with a clearer decision trail.",
                        )
                    )
                elif decision_state == "no_go" and (
                    _contains_any(current_status, COMPLETE_MARKERS) or _contains_any(history, COMPLETE_MARKERS)
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Decision '{decision_text}' conflicts with current status '{current_status}'"],
                            why_it_matters="Decision pages should not read as NO-GO while the page status is already complete.",
                            suggested_action="Clarify whether the decision applies to the page, the project, or a prior state.",
                        )
                    )
                elif decision_state == "go" and _contains_any(f"{handoff_summary}\n{next_step}", ["deferred", "blocked", "pending"]):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-handoff-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Decision '{decision_text}' conflicts with handoff text '{handoff_summary} / {next_step}'"],
                            why_it_matters="A GO decision should not be paired with a handoff that still signals blocked or pending work.",
                            suggested_action="Align the decision record with the handoff wording or record the outstanding blocker in History.",
                        )
                    )

            if page_kind == "project" and decision_text:
                if decision_state == "go" and (
                    _contains_any(current_status, BLOCKED_MARKERS) or _contains_any(history, BLOCKED_MARKERS)
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-proj-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Project page decision '{decision_text}' conflicts with current status '{current_status}'"],
                            why_it_matters="Project pages should not imply GO while current status says blocked or deferred.",
                            suggested_action="Update the project status or move the approval note into History.",
                        )
                    )
                elif decision_state == "conditional_go" and _contains_any(current_status, BLOCKED_MARKERS) and not condition_signal:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-proj-cond-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Project page decision '{decision_text}' lacks condition language while current status is '{current_status}'"],
                            why_it_matters="Conditional GO on a project page should explain the condition that still needs resolution.",
                            suggested_action="Add the condition language or move the partial approval into History.",
                        )
                    )
                elif decision_state == "no_go" and (
                    _contains_any(current_status, COMPLETE_MARKERS) or _contains_any(history, COMPLETE_MARKERS)
                ):
                    findings.append(
                        SemanticFinding(
                            finding_id=f"decisiondrift-proj-neg-{index}",
                            finding_type="decision_drift",
                            severity=_decision_drift_severity(page_kind),
                            pages=[page_name],
                            evidence=[f"Project page decision '{decision_text}' conflicts with completion markers in status/history"],
                            why_it_matters="Project pages should not read as NO-GO if the record already states the work is complete.",
                            suggested_action="Clarify whether the decision refers to a previous state or move the decision into History.",
                        )
                    )

        for item in page_data:
            page_name = str(item["relative_path"])
            for link in item["links"]:
                normalized_link = _normalize_title(link)
                linked_pages = by_normalized.get(normalized_link, [])
                if not linked_pages:
                    findings.append(
                        SemanticFinding(
                            finding_id=f"link-{len(findings)+1}",
                            finding_type="coverage_gap",
                            severity=_coverage_gap_severity(str(item["page_kind"])),
                            pages=[page_name],
                            evidence=[f"broken semantic reference: [[{link}]]"],
                            why_it_matters="The linked page name does not exist in the reviewed scope.",
                            suggested_action="Create the referenced page or adjust the link.",
                        )
                    )

        for index, left in enumerate(page_data, start=1):
            left_name = str(left["relative_path"])
            linked_targets = {_normalize_title(link) for link in left["links"]}
            for right in page_data[index:]:
                right_name = str(right["relative_path"])
                related = left["normalized_title"] == right["normalized_title"] or right["normalized_title"] in linked_targets or left["normalized_title"] in {
                    _normalize_title(link) for link in right["links"]
                }
                if not related:
                    continue

                left_kind = str(left["page_kind"])
                right_kind = str(right["page_kind"])
                if _has_semantic_conflict(str(left["status_signal"]), str(right["status_signal"])):
                    contradiction_id = f"contradiction-{len(findings)+1}"
                    findings.append(
                        SemanticFinding(
                            finding_id=contradiction_id,
                            finding_type="contradiction",
                            severity=_contradiction_severity(left_kind, right_kind),
                            pages=[left_name, right_name],
                            evidence=[
                                f"{left_name} status={left['status_signal']}",
                                f"{right_name} status={right['status_signal']}",
                            ],
                            why_it_matters="Related pages describe mutually incompatible state.",
                            suggested_action="Review the linked pages and reconcile the conflicting state in Current Status or History.",
                        )
                    )

                if str(left["decision_state"]) != "unknown" and str(right["status_signal"]) != "unknown":
                    left_state = str(left["decision_state"])
                    right_status = str(right["status_signal"])
                    if left_state == "go" and right_status in {"blocked", "complete"}:
                        findings.append(
                            SemanticFinding(
                                finding_id=f"decisiondrift-link-{len(findings)+1}",
                                finding_type="decision_drift",
                                severity=_decision_drift_severity(left_kind, right_kind),
                                pages=[left_name, right_name],
                                evidence=[
                                    f"{left_name} decision={left_state}",
                                    f"{right_name} status={right_status}",
                                ],
                                why_it_matters="Decision pages and linked pages should agree on whether work is approved or blocked.",
                                suggested_action="Align the decision outcome with the linked page state or document the transition in History.",
                            )
                        )
                    elif left_state == "conditional_go" and right_status == "blocked" and not (
                        _has_condition_language(str(left["text"])) or _has_condition_language(str(right["text"]))
                    ):
                        findings.append(
                            SemanticFinding(
                                finding_id=f"decisiondrift-link-{len(findings)+1}",
                                finding_type="decision_drift",
                                severity=_decision_drift_severity(left_kind, right_kind),
                                pages=[left_name, right_name],
                                evidence=[
                                    f"{left_name} decision={left_state}",
                                    f"{right_name} status={right_status}",
                                ],
                                why_it_matters="Conditional GO should carry the condition that explains why the linked page is still blocked.",
                                suggested_action="Add the condition language to the decision or project page, or move the uncertainty into History.",
                            )
                        )
                    elif left_state == "no_go" and right_status in {"complete", "active"}:
                        findings.append(
                            SemanticFinding(
                                finding_id=f"decisiondrift-link-{len(findings)+1}",
                                finding_type="decision_drift",
                                severity=_decision_drift_severity(left_kind, right_kind),
                                pages=[left_name, right_name],
                                evidence=[
                                    f"{left_name} decision={left_state}",
                                    f"{right_name} status={right_status}",
                                ],
                                why_it_matters="Decision pages and linked pages should agree on whether work is approved, conditional, or blocked.",
                                suggested_action="Align the decision outcome with the linked page state or document the reason for the mismatch.",
                            )
                        )

        merge_candidates = [finding.finding_id for finding in findings if finding.finding_type == "merge_candidate"]
        stale_status_findings = [finding.finding_id for finding in findings if finding.finding_type == "stale_status"]
        contradiction_findings = [finding.finding_id for finding in findings if finding.finding_type == "contradiction"]
        handoff_drift_findings = [finding.finding_id for finding in findings if finding.finding_type == "handoff_drift"]
        handoff_quality_findings = [finding.finding_id for finding in findings if finding.finding_type == "handoff_quality_issue"]
        decision_drift_findings = [finding.finding_id for finding in findings if finding.finding_type == "decision_drift"]
        misleading_summary_findings = [finding.finding_id for finding in findings if finding.finding_type == "misleading_summary"]
        confirmed_semantic_risks = [finding.finding_id for finding in findings if finding.severity in {"medium", "high"}]
        return SemanticReport(
            scan_scope=str(root),
            pages_reviewed=pages_reviewed,
            findings=findings,
            contradiction_findings=contradiction_findings,
            handoff_drift_findings=handoff_drift_findings,
            handoff_quality_findings=handoff_quality_findings,
            decision_drift_findings=decision_drift_findings,
            misleading_summary_findings=misleading_summary_findings,
            confirmed_semantic_risks=confirmed_semantic_risks,
            merge_candidates=merge_candidates,
            stale_status_findings=stale_status_findings,
        )

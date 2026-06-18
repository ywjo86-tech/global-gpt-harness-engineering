# Knot v2 Semantic Check Standard

## Purpose

Knot v2 is the semantic review layer for an LLM Wiki vault. It builds on the mechanical checks from knot v1 and reviews whether pages still agree with each other and with the current project state.

## Operating Boundaries

- Knot v2 is a file-based review standard, not an Obsidian app configuration guide.
- Do not configure Obsidian app settings, sync settings, plugins, or workspace preferences as part of knot v2.
- Do not require the vault to be opened in Obsidian for the checker itself; vault opening is a separate manual action that the user may do later.
- Treat the on-disk vault contents as the review source of truth.

## Relationship to Knot v1

- Knot v1 checks structure, links, naming, registration, and folder placement.
- Knot v2 checks meaning, consistency, drift, and review quality.
- Knot v2 should never replace knot v1; it should run after or alongside a successful v1 scan when semantic review is needed.

## Semantic Review Principles

- Keep the review evidence-based.
- Separate confirmed issues from suggestions and open questions.
- Do not auto-edit pages based only on semantic suspicion.
- Keep human review in the loop for any semantic change that could alter the vault meaning.

## Semantic Scope

Knot v2 should review:

- project pages for Current Status, History, Handoff Summary, and Next Step drift
- decision pages for decision consistency against linked project pages
- concept pages for accidental operational or approval language
- index pages for navigational consistency without operational drift
- outdated information
- contradictions between pages
- contradictions between Current Status and History on the same page
- contradictions between Current Status and Handoff Summary or Next Step on the same page
- contradiction between status and handoff language
- handoff drift between the summary and the next step
- decision drift between decision text and page state, including GO, CONDITIONAL GO, and NO-GO distinctions
- decision drift between decision text and History, Handoff Summary, or Next Step
- duplicate topic merge opportunities
- `Current Status` inconsistencies
- `History` drift
- decision record consistency
- handoff summary quality
- handoff summary quality issues that sound complete while History or Open Questions remain unfinished
- misleading summaries that sound more certain than the documented status or open questions allow
- concept linkage quality
- page coverage gaps across closely related pages
- stale or misleading summary language

## Non-Goals

Knot v2 should not:

- replace the mechanical checks from knot v1
- auto-write page fixes
- configure Obsidian app settings or sync settings
- open the vault in Obsidian on behalf of the user
- depend on Obsidian UI automation or plugin state
- introduce Notion as a primary backend
- introduce vector DB retrieval
- modify runtime code
- connect memory retrieval to Jarvis main brain

## Review Inputs

Use these inputs when available:

- curated wiki pages
- index pages
- recent decision records
- handoff summaries
- related project context notes
- optional source snippets that explain why a semantic change happened

## Review Scope Selection

Before reviewing content, knot v2 should narrow the scope to a bounded set of pages or clusters such as:

- one project page and its directly related concept or decision pages
- one decision record and the project pages it affects
- one handoff summary and the pages it summarizes
- one topic cluster around a specific concept or business rule

This prevents semantic review from becoming an unbounded vault-wide search when a narrower review slice is enough.

## Review Outputs

The semantic report should include:

- scan scope
- pages reviewed
- semantic findings
- page pairs or clusters that conflict
- merge candidates
- stale-status findings
- decision-consistency findings
- handoff-quality findings
- misleading-summary findings
- suggested human review actions

## Semantic Finding Record

Each finding should be recorded with a structured shape so the report is easy to review later:

- `finding_id`
- `finding_type`
- `severity`
- `pages`
- `evidence`
- `why_it_matters`
- `suggested_action`
- `human_review_required`

Suggested `finding_type` values:

- `outdated_information`
- `contradiction`
- `merge_candidate`
- `stale_status`
- `contradiction`
- `handoff_drift`
- `decision_drift`
- `handoff_quality_issue`
- `coverage_gap`
- `misleading_summary`

Page-type-aware review examples:

- project pages should keep Current Status, History, Handoff Summary, and Next Step aligned
- project pages should treat contradiction as higher severity because they are execution surfaces
- project pages should treat handoff drift as higher severity because they are execution surfaces
- project pages should treat decision drift as higher severity because they are execution surfaces
- project pages should treat merge candidate, stale status, and coverage gap findings as higher severity when they affect active execution pages
- project pages should treat handoff quality issues and misleading summaries as higher severity because they can hide unresolved execution work
- decision pages should keep the decision text aligned with linked project state and distinguish GO, CONDITIONAL GO, and NO-GO clearly
- concept pages should stay descriptive and avoid operational Decision or handoff language
- index pages should stay navigational and avoid acting like project or decision records

## Decision Handling

- Record semantic issues as findings, suggestions, or open questions until a human confirms them.
- Use a separate section for confirmed semantic risks.
- Keep mechanical errors separate from semantic concerns.
- Do not blur a semantic suggestion into a structural error.

## Review Sequence

1. Confirm that knot v1 passed for the same scope.
2. Load the curated wiki pages, index pages, decision pages, and handoff summaries in scope.
3. Group related pages by topic or dependency.
4. Compare current status, history, decisions, and summary language.
5. Record findings with evidence and suggested action.
6. Separate confirmed risks from open questions.
7. Keep the report read-only.
8. Escalate any meaning-changing issue for human review before page edits.

## Output Expectations

The semantic report should be able to answer:

- What scope was reviewed?
- Which pages were compared?
- Which pages conflict or drift apart?
- Which topics are likely duplicates or merge candidates?
- Which summaries or statuses look stale?
- Which pages show contradiction, handoff drift, or decision drift?
- Which pages conflict internally between Current Status, History, Handoff Summary, Next Step, and Decision?
- What must a human review next?

## Human Review

- Human review is required before semantic findings become page edits.
- If a semantic change would alter meaning or history, preserve the previous state in `History` or a decision record first.
- Do not silently rewrite wiki pages based only on semantic analysis.

## Validation Checklist

- Confirm knot v1 passed before relying on v2 semantic review.
- Confirm semantic findings are separated from structural findings.
- Confirm output highlights conflicts, merge candidates, and stale-status issues.
- Confirm output highlights contradiction, handoff drift, and decision drift issues.
- Confirm decision drift can distinguish GO, CONDITIONAL GO, and NO-GO language.
- Confirm project, decision, concept, and index pages receive page-type-appropriate drift checks.
- Confirm project pages are treated as higher-severity handoff-quality and misleading-summary surfaces than decision pages.
- Confirm merge candidate, stale status, and coverage gap findings are also page-type-aware.
- Confirm the report remains read-only and human-reviewed.
- Confirm the checker does not configure Obsidian app settings, sync settings, or plugin state.
- Confirm vault opening in Obsidian remains a user action outside the checker.
- Confirm the finding record shape is structured enough for later review and comparison.
- Confirm the review sequence starts with a successful v1 scan and a bounded scope.

## Reference Implementation

- `runtime/knot_v2/semantic_checker.py`
- `runtime/knot_v2/__init__.py`

## Last Updated
2026-06-18

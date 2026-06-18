# Knot Health Check Standard

## Purpose

Knot is the quality-control layer for an LLM Wiki vault. It checks structure, links, naming, and content consistency so memory pages stay usable as the vault grows.

## Vault Model

- Knot scans Obsidian-compatible Markdown files in the memory vault.
- Raw inbox material is treated as source input, not as curated wiki content.
- Curated wiki pages are the primary targets for link, section, and index validation.

## Mechanical Checks vs Semantic Checks

- Mechanical checks verify file structure and Markdown hygiene.
- Semantic checks verify whether the content still makes sense relative to other pages and the current project state.
- Mechanical checks can be run deterministically.
- Semantic checks may require model-assisted review, but the final report still needs human review.
- Semantic findings should be recorded as suggestions or open questions until confirmed.

## Knot v1 Scope

Knot v1 is the local, mechanical checker. It should detect:

- Broken `[[wiki links]]`
- Duplicate page names
- Empty Markdown files
- Missing required sections
- Missing `Last Updated` fields
- Missing index registration
- Orphan pages
- Invalid folder placement

## Knot v2 Scope

Knot v2 extends the checker with semantic review. It should detect:

- Outdated information
- Contradictions between pages
- Contradictions between Current Status and History on the same page
- Contradictions between Current Status and Handoff Summary or Next Step on the same page
- Contradiction between status and handoff language
- Handoff drift between summary and next step
- Decision drift between decision text and page state
- Decision drift between decision text and History, Handoff Summary, or Next Step
- Decision drift that distinguishes GO, CONDITIONAL GO, and NO-GO semantics
- Project pages surface decision drift more aggressively than decision pages
- Project pages surface handoff drift more aggressively than decision pages
- Project pages surface contradiction more aggressively than decision pages
- Project pages surface merge candidate, stale status, and coverage gap findings more aggressively than concept or index pages
- Project pages surface handoff quality issues and misleading summaries more aggressively than decision pages
- Duplicate topic merge opportunities
- `Current Status` inconsistencies
- Decision history inconsistencies
- Handoff summary quality issues
- Misleading summaries that sound more certain than the page state allows
- Page-type-aware drift checks for project, decision, concept, and index pages

The detailed semantic review standard lives in `docs/harness/memory/knot-v2-semantic-check-standard.md`.
The reference implementation lives in `runtime/knot_v2/semantic_checker.py`.
Knot v2 remains a file-based review layer only; it does not configure Obsidian app settings, sync settings, or plugin state, and it does not open the vault on the user's behalf.

## Report Format

Each knot run should produce a report that includes:

1. Scan scope and timestamp
2. Files checked
3. Passing checks
4. Warnings
5. Errors
6. Suggested fixes
7. Human review notes

The report should separate mechanical failures from semantic concerns.

## Human Review Requirement

- Knot reports are advisory, not auto-fixes.
- Human review is required before major memory changes are accepted.
- Semantic findings should be treated as suggestions until confirmed by a person.
- Do not silently rewrite wiki pages based only on knot output.
- Jarvis Assistant main-brain integration remains deferred and out of scope for knot itself.

## Validation Checklist

- Confirm the scan targets curated wiki files rather than raw inbox input.
- Confirm v1 checks remain mechanical and deterministic.
- Confirm v2 checks implement page-type-aware semantic review without becoming an Obsidian UI automation layer.
- Confirm decision drift distinguishes GO, CONDITIONAL GO, and NO-GO semantics.
- Confirm project pages are treated as higher-severity decision-drift surfaces than decision pages.
- Confirm project pages are treated as higher-severity handoff-drift surfaces than decision pages.
- Confirm project pages are treated as higher-severity contradiction surfaces than decision pages.
- Confirm project pages are treated as higher-severity handoff-quality and misleading-summary surfaces than decision pages.
- Confirm merge candidate, stale status, and coverage gap findings are page-type-aware.
- Confirm handoff-quality and misleading-summary findings are reported explicitly.
- Confirm the report separates findings from suggested fixes and human review notes.
- Confirm the semantic checker does not depend on Obsidian UI setup or sync configuration.

---
name: knot-health-check-harness
description: Inspect an LLM Wiki vault for broken links, missing sections, duplicates, or semantic drift and produce a human-reviewed health report.
---

# Knot Health Check Harness

Use this skill when you need to inspect a memory vault for structural or semantic quality issues.

## When to Use

- A vault or wiki section has grown enough to need quality review.
- Broken links, duplicate pages, or missing sections may exist.
- Current status may have drifted from the rest of the vault.
- A handoff or decision history needs consistency review.

## Required Inputs

- Vault root or scan scope
- Required sections and index rules
- Known canonical pages
- Optional semantic review context
- Inbox material is not the primary scan target; curated wiki pages are.

## Workflow

1. Scan the Markdown files in scope.
2. Extract `[[wiki links]]` and compare them to existing pages.
3. Detect broken links, duplicate names, empty files, missing sections, missing `Last Updated`, orphan pages, and missing index entries.
4. Review for outdated, contradictory, or duplicated topic content when semantic context is available.
5. Generate a report with findings, severity, and suggested fixes.
6. Do not auto-apply changes unless a separate approval is given.
7. Escalate major inconsistencies for human review.

## Outputs

- Health report
- Broken link list
- Missing section list
- Duplicate and orphan findings
- Semantic drift notes
- Suggested fixes

## Validation

- Report distinguishes mechanical issues from semantic concerns.
- Findings are specific and actionable.
- No automatic file edits are made.
- Human review is clearly required before accepting major changes.
- The report is suitable for knotted wiki content rather than runtime code changes.

## Karpathy-Style AI Coding Principles

- Think Before Coding: define the scan scope, required sections, and expected false-positive risk before running checks.
- Simplicity First: keep the checker lightweight and deterministic where possible.
- Surgical Changes: report issues only; do not auto-edit vault files.
- Goal-Driven Execution: return a clear report with findings, severity, and follow-up actions.

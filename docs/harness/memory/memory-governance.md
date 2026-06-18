# Memory Governance

## Purpose

This document defines what should be stored in long-term memory, what should stay out, and how to handle uncertainty, stale information, and handoffs.

## Memory Model

- Raw inbox material is the source surface.
- Curated LLM Wiki pages are the durable memory surface.
- Obsidian-compatible Markdown is the storage format for curated memory.
- Internal links should use `[[Page Name]]` where related pages should be connected.

## What Should Be Stored

- Important decisions
- Project state changes
- Known errors and fixes
- Stable facts
- Operational constraints
- Handoff notes
- Key links to related pages and source context

## What Should Not Be Stored

- Secrets, credentials, tokens, or passwords
- Unconfirmed rumors
- Raw speculative analysis without confirmation
- Duplicate copies of the same source material
- Personal data that is not needed for the project
- Transient chat noise that does not affect future work

## Sensitive Information Handling

- Do not store secrets in wiki pages.
- Redact sensitive values before writing a page.
- Store only the minimum necessary detail for the task.
- If a sensitive item is required for context, describe it at a high level instead of copying it verbatim.

## Outdated Information Handling

- Do not overwrite history just because the latest state changed.
- Move superseded information into `History` or `Past Issues`.
- Mark deprecated instructions clearly.
- Keep current and historical states separate.

## Uncertain Information Handling

- Mark uncertainty as `Open Questions`.
- Do not present assumptions as confirmed facts.
- Capture what still needs verification and who should confirm it.

## Updating Project Status

- Update project pages when a milestone changes state.
- Keep `Current Status` aligned with the latest confirmed result.
- Add a date when the status changes materially.
- Link the status change to the relevant decision or handoff page.

## Creating Handoff Notes

- Summarize what changed, what remains open, and what should happen next.
- Include the location of supporting pages and source material.
- Preserve the final review state, not just the work-in-progress state.
- Add knot follow-up if the handoff affects a large portion of the vault.
- Jarvis Assistant main-brain integration stays deferred until the memory contract is ready.

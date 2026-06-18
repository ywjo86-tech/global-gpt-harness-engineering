---
name: llm-wiki-memory-harness
description: Convert chats, logs, handoffs, and decisions into Obsidian-compatible LLM Wiki pages with stable links and preserved history.
---

# LLM Wiki Memory Harness

Use this skill when you need to turn raw project material into durable wiki pages that can be maintained over time.

## When to Use

- A project chat, log, or handoff needs to become reusable memory.
- A page should be created or updated in an Obsidian-compatible vault.
- Related pages and index entries need to be kept in sync.
- Historical facts must be preserved instead of overwritten.

## Required Inputs

- Raw source material
- Target project or topic
- Existing wiki pages, if any
- Known facts versus uncertain items
- Vault structure or index conventions
- Inbox material when available, rather than only chat history

## Workflow

1. Read the raw input and identify the project, topic, decision, issue, and current status.
2. Check whether a canonical page already exists before creating a new one.
3. Treat inbox material as the raw source surface and update the canonical wiki page instead of creating duplicates.
4. Add `[[Page Name]]` links to related pages and record supporting context.
5. Preserve history, deprecated facts, and prior decisions in the right sections.
6. Mark anything unverified as an `Open Question`.
7. Update indexes that should point to the page.
8. Request a knot v1 health check after large memory updates.

## Outputs

- Updated or new wiki page content
- Related page links
- Index update notes
- History preserved from prior state
- Open questions list

## Validation

- The page uses Obsidian-compatible Markdown.
- The page has a clear title and stable structure.
- Historical facts are not lost.
- Uncertainty is separated from confirmed status.
- Related pages and indexes are updated when needed.
- The canonical page is preferred over duplicate topic pages.
- The result is prepared for knot v1 review before larger memory updates continue.

## Karpathy-Style AI Coding Principles

- Think Before Coding: confirm the raw input, existing pages, and unresolved questions before writing.
- Simplicity First: keep the transformation local to Markdown files and avoid unnecessary tooling.
- Surgical Changes: update only the canonical page and related index entries; do not touch runtime code.
- Goal-Driven Execution: finish with the updated page, the links used, and the verification notes.

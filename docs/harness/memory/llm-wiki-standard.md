# LLM Wiki Standard

## Purpose

LLM Wiki is the curated, Obsidian-compatible Markdown layer for durable project memory. It exists to turn raw chats, logs, handoffs, and decisions into stable wiki pages that can be linked, reviewed, and maintained over time.

## Raw Inbox vs Curated Wiki

- Raw inbox stores unprocessed source material.
- Curated wiki stores reviewed, deduplicated, and linked knowledge.
- Raw entries should not be treated as authoritative project memory until they are converted into wiki pages.
- Curated wiki pages should preserve the source context, but only the confirmed interpretation belongs in `Current Status` and `Key Facts`.

## Markdown Rules

- Use plain Markdown that works in Obsidian.
- Use `[[Page Name]]` links for wiki relationships.
- Prefer one topic per page.
- Avoid duplicating the same fact across multiple pages unless the page context requires a short summary.
- Use stable page titles and consistent naming.

## Required Page Structure

Every wiki page should use the following structure when applicable:

```md
# Page Title

## Summary
Short explanation of the topic.

## Current Status
Latest confirmed state.

## Key Facts
Stable facts, decisions, and known constraints.

## History
Past issues, resolved problems, and deprecated information.

## Related Pages
- [[Related Page 1]]
- [[Related Page 2]]

## Open Questions
Items that need later confirmation.

## Last Updated
YYYY-MM-DD
```

## Required Metadata

- Page title must be clear and specific.
- `Last Updated` is required for maintained pages.
- Related pages should be linked explicitly.
- If the page captures a decision, record the decision date and the reasoning context.

## Historical Facts

- Do not delete important historical facts when the current state changes.
- Move superseded facts into `History`.
- Mark obsolete guidance as deprecated instead of rewriting it as if it never existed.
- Keep time-sensitive statements separated from stable facts.

## Current Status Rules

- `Current Status` must describe the latest confirmed state only.
- Do not include speculation in `Current Status`.
- If the state is uncertain, move the uncertainty into `Open Questions`.

## Decision Records

- Record what was decided, when it was decided, and why.
- Include the alternatives that were rejected when they matter for later review.
- Link the decision to related issue, project, or handoff pages.

## Duplicate Page Avoidance

- Check for an existing page before creating a new one.
- Prefer updating the canonical page over creating parallel topic pages.
- If two pages overlap, merge the authoritative content and preserve history.
- Use redirects or related links when a renamed page must remain discoverable.

## Relationship to Other Standards

- This standard works with `obsidian-vault-structure.md` for folder layout and navigation.
- This standard works with `knot-health-check-standard.md` for structural and semantic validation.
- This standard works with `memory-governance.md` for what belongs in long-term memory.
- Raw inbox material remains separate from curated wiki pages until it is reviewed.
- Jarvis Assistant main-brain memory integration remains deferred to a later phase.

## Validation Checklist

- Confirm the page clearly separates raw input from curated wiki content.
- Confirm current status, history, and open questions are not merged together.
- Confirm related pages use `[[Page Name]]` links.
- Confirm outdated facts move to `History` instead of replacing older context.

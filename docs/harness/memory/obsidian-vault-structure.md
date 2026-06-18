# Obsidian Vault Structure Standard

## Purpose

This standard defines how the memory vault should be organized so Obsidian, Global GPT Harness Engineering, knot, and future Jarvis Assistant memory workflows can share the same durable structure.

## Content Model

- LLM Wiki pages are the curated memory layer.
- Inbox folders hold raw, uncurated source material.
- Obsidian-compatible Markdown is the primary storage format for the curated layer.
- Current status, historical facts, and open questions should remain separated in the wiki layer.
- Jarvis Assistant main-brain integration stays deferred until the memory contract is approved.

## Recommended Folder Structure

```text
memory-vault/
  inbox/
    raw_chats/
    raw_documents/
    raw_logs/
    raw_emails/
  wiki/
    projects/
    concepts/
    decisions/
    business/
  indexes/
  templates/
  knot/
    config/
    reports/
```

## Naming Rules

- Use descriptive, human-readable file names.
- Prefer lowercase kebab-case or clear canonical Markdown titles consistently within a vault.
- Keep page titles stable once they are linked broadly.
- Use one canonical page per concept or project.

## Link Rules

- Use `[[Page Name]]` for internal wiki links.
- Link from raw inputs to the curated page that will own the topic.
- Add related links on project, concept, and decision pages.
- Avoid dead-end pages with no related context.

## Index Page Rules

- Maintain indexes for discoverability.
- Register new canonical pages in the appropriate index.
- Keep project and concept indexes small enough to scan quickly.
- Update indexes when a page is renamed, merged, or retired.

## Inbox-to-Wiki Workflow

1. Capture raw material in the inbox.
2. Review the content for topic, decisions, issues, and status.
3. Check for an existing canonical page.
4. Update the canonical page or create a new one if needed.
5. Add related links and index entries.
6. Preserve history and note unresolved questions.
7. Run knot after larger updates.

## Relationship to Obsidian, Global Harness, knot, and Jarvis Assistant

- Obsidian is the editing and navigation layer for the vault.
- Global GPT Harness Engineering defines the standards and workflows.
- Knot validates structure and consistency.
- Jarvis Assistant should only consume the memory contract after the dedicated integration phase.
- The vault may live outside this repository, but the standards for it live here.

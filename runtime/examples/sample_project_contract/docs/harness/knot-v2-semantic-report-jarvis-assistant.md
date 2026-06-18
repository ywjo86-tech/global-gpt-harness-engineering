# Knot v2 Semantic Report

## Scope

- `wiki/projects/jarvis-assistant.md`
- `wiki/projects/global-gpt-harness-engineering.md`
- `wiki/concepts/llm-wiki.md`
- `wiki/concepts/knot.md`
- `wiki/concepts/memory-vault.md`

## Counts

- Pages reviewed: 5
- Findings: 7
- Confirmed semantic risks: 4
- Contradiction findings: 2
- Handoff drift findings: 0
- Handoff quality findings: 0
- Decision drift findings: 1
- Misleading summary findings: 0
- Merge candidates: 0
- Stale status findings: 1


Scan scope: C:\Users\ywjo8\Documents\AI-Workspace\memory-vault
Pages reviewed: wiki/concepts/knot.md, wiki/concepts/llm-wiki.md, wiki/concepts/memory-vault.md, wiki/projects/global-gpt-harness-engineering.md, wiki/projects/jarvis-assistant.md

Findings
- stale-5: stale_status (high)
  - pages: wiki/projects/jarvis-assistant.md
  - evidence: stale markers: not started
  - why_it_matters: The page may still describe provisional or outdated state.
  - suggested_action: Replace provisional wording with the latest confirmed state or move it to History.
- link-2: coverage_gap (low)
  - pages: wiki/concepts/knot.md
  - evidence: broken semantic reference: [[Obsidian]]
  - why_it_matters: The linked page name does not exist in the reviewed scope.
  - suggested_action: Create the referenced page or adjust the link.
- link-3: coverage_gap (low)
  - pages: wiki/concepts/llm-wiki.md
  - evidence: broken semantic reference: [[Obsidian]]
  - why_it_matters: The linked page name does not exist in the reviewed scope.
  - suggested_action: Create the referenced page or adjust the link.
- link-4: coverage_gap (low)
  - pages: wiki/concepts/memory-vault.md
  - evidence: broken semantic reference: [[Obsidian]]
  - why_it_matters: The linked page name does not exist in the reviewed scope.
  - suggested_action: Create the referenced page or adjust the link.
- contradiction-5: contradiction (high)
  - pages: wiki/concepts/memory-vault.md, wiki/projects/global-gpt-harness-engineering.md
  - evidence: wiki/concepts/memory-vault.md status=complete, wiki/projects/global-gpt-harness-engineering.md status=blocked
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- contradiction-6: contradiction (high)
  - pages: wiki/concepts/memory-vault.md, wiki/projects/jarvis-assistant.md
  - evidence: wiki/concepts/memory-vault.md status=complete, wiki/projects/jarvis-assistant.md status=blocked
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- decisiondrift-link-7: decision_drift (high)
  - pages: wiki/projects/global-gpt-harness-engineering.md, wiki/projects/jarvis-assistant.md
  - evidence: wiki/projects/global-gpt-harness-engineering.md decision=go, wiki/projects/jarvis-assistant.md status=blocked
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.

Confirmed Semantic Risks
stale-5, contradiction-5, contradiction-6, decisiondrift-link-7

Contradiction Findings
contradiction-5, contradiction-6

Handoff Drift Findings
none

Handoff Quality Findings
none

Decision Drift Findings
decisiondrift-link-7

Misleading Summary Findings
none

Merge Candidates
none

Stale Status Findings
stale-5

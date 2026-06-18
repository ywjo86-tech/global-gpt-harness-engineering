# Knot v2 Semantic Report

Generated for the sample project contract using the current `memory-vault` snapshot.

## Scan Scope

- `C:\Users\ywjo8\Documents\AI-Workspace\memory-vault`

## Pages Reviewed

- `indexes/business-index.md`
- `indexes/concept-index.md`
- `indexes/decision-index.md`
- `indexes/project-index.md`
- `wiki/business/harness-standards.md`
- `wiki/business/vault-adoption-criteria.md`
- `wiki/business/vault-governance-policy.md`
- `wiki/concepts/knot.md`
- `wiki/concepts/llm-wiki.md`
- `wiki/concepts/memory-vault.md`
- `wiki/concepts/obsidian.md`
- `wiki/decisions/memory-vault-bootstrap-decision.md`
- `wiki/projects/codex-orchestrator.md`
- `wiki/projects/global-gpt-harness-engineering.md`
- `wiki/projects/jarvis-assistant.md`

## Findings

- `stale-6`: `stale_status` (`medium`)
  - pages: `wiki/business/vault-adoption-criteria.md`
  - evidence: stale markers: draft
  - why_it_matters: The page may still describe provisional or outdated state.
  - suggested_action: Replace provisional wording with the latest confirmed state or move it to History.
- `decision-12`: `decision_drift` (`medium`)
  - pages: `wiki/decisions/memory-vault-bootstrap-decision.md`
  - evidence: Decision page without explicit decision text in Current Status
  - why_it_matters: Decision pages should make the decision outcome easy to inspect.
  - suggested_action: State the decision in Current Status or an explicit Decision section.
- `stale-15`: `stale_status` (`high`)
  - pages: `wiki/projects/jarvis-assistant.md`
  - evidence: stale markers: not started
  - why_it_matters: The page may still describe provisional or outdated state.
  - suggested_action: Replace provisional wording with the latest confirmed state or move it to History.
- `link-4`: `coverage_gap` (`medium`)
  - pages: `wiki/business/vault-adoption-criteria.md`
  - evidence: broken semantic reference: `[[wiki links]]`
  - why_it_matters: The linked page name does not exist in the reviewed scope.
  - suggested_action: Create the referenced page or adjust the link.
- `link-5`: `coverage_gap` (`low`)
  - pages: `wiki/concepts/obsidian.md`
  - evidence: broken semantic reference: `[[wiki links]]`
  - why_it_matters: The linked page name does not exist in the reviewed scope.
  - suggested_action: Create the referenced page or adjust the link.
- `decisiondrift-link-6`: `decision_drift` (`low`)
  - pages: `wiki/business/vault-governance-policy.md`, `wiki/concepts/memory-vault.md`
  - evidence: `wiki/business/vault-governance-policy.md decision=go`, `wiki/concepts/memory-vault.md status=complete`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.
- `decisiondrift-link-7`: `decision_drift` (`high`)
  - pages: `wiki/business/vault-governance-policy.md`, `wiki/projects/global-gpt-harness-engineering.md`
  - evidence: `wiki/business/vault-governance-policy.md decision=go`, `wiki/projects/global-gpt-harness-engineering.md status=blocked`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.
- `decisiondrift-link-8`: `decision_drift` (`high`)
  - pages: `wiki/business/vault-governance-policy.md`, `wiki/projects/jarvis-assistant.md`
  - evidence: `wiki/business/vault-governance-policy.md decision=go`, `wiki/projects/jarvis-assistant.md status=blocked`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.
- `contradiction-9`: `contradiction` (`high`)
  - pages: `wiki/concepts/memory-vault.md`, `wiki/projects/global-gpt-harness-engineering.md`
  - evidence: `wiki/concepts/memory-vault.md status=complete`, `wiki/projects/global-gpt-harness-engineering.md status=blocked`
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- `contradiction-10`: `contradiction` (`high`)
  - pages: `wiki/concepts/memory-vault.md`, `wiki/projects/jarvis-assistant.md`
  - evidence: `wiki/concepts/memory-vault.md status=complete`, `wiki/projects/jarvis-assistant.md status=blocked`
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- `contradiction-11`: `contradiction` (`high`)
  - pages: `wiki/decisions/memory-vault-bootstrap-decision.md`, `wiki/projects/global-gpt-harness-engineering.md`
  - evidence: `wiki/decisions/memory-vault-bootstrap-decision.md status=complete`, `wiki/projects/global-gpt-harness-engineering.md status=blocked`
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- `decisiondrift-link-12`: `decision_drift` (`high`)
  - pages: `wiki/decisions/memory-vault-bootstrap-decision.md`, `wiki/projects/global-gpt-harness-engineering.md`
  - evidence: `wiki/decisions/memory-vault-bootstrap-decision.md decision=go`, `wiki/projects/global-gpt-harness-engineering.md status=blocked`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.
- `contradiction-13`: `contradiction` (`high`)
  - pages: `wiki/decisions/memory-vault-bootstrap-decision.md`, `wiki/projects/jarvis-assistant.md`
  - evidence: `wiki/decisions/memory-vault-bootstrap-decision.md status=complete`, `wiki/projects/jarvis-assistant.md status=blocked`
  - why_it_matters: Related pages describe mutually incompatible state.
  - suggested_action: Review the linked pages and reconcile the conflicting state in Current Status or History.
- `decisiondrift-link-14`: `decision_drift` (`high`)
  - pages: `wiki/decisions/memory-vault-bootstrap-decision.md`, `wiki/projects/jarvis-assistant.md`
  - evidence: `wiki/decisions/memory-vault-bootstrap-decision.md decision=go`, `wiki/projects/jarvis-assistant.md status=blocked`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.
- `decisiondrift-link-15`: `decision_drift` (`high`)
  - pages: `wiki/projects/global-gpt-harness-engineering.md`, `wiki/projects/jarvis-assistant.md`
  - evidence: `wiki/projects/global-gpt-harness-engineering.md decision=go`, `wiki/projects/jarvis-assistant.md status=blocked`
  - why_it_matters: Decision pages and linked pages should agree on whether work is approved or blocked.
  - suggested_action: Align the decision outcome with the linked page state or document the transition in History.

## Confirmed Semantic Risks

`stale-6`, `decision-12`, `stale-15`, `link-4`, `decisiondrift-link-7`, `decisiondrift-link-8`, `contradiction-9`, `contradiction-10`, `contradiction-11`, `decisiondrift-link-12`, `contradiction-13`, `decisiondrift-link-14`, `decisiondrift-link-15`

## Contradiction Findings

`contradiction-9`, `contradiction-10`, `contradiction-11`, `contradiction-13`

## Handoff Drift Findings

none

## Handoff Quality Findings

none

## Decision Drift Findings

`decision-12`, `decisiondrift-link-6`, `decisiondrift-link-7`, `decisiondrift-link-8`, `decisiondrift-link-12`, `decisiondrift-link-14`, `decisiondrift-link-15`

## Misleading Summary Findings

none

## Merge Candidates

none

## Stale Status Findings

`stale-6`, `stale-15`


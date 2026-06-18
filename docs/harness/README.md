# Harness Documentation

This directory contains detailed operating standards for the Global Harness Engineering PMO.

## Purpose

The PMO defines reusable Codex project workflows, agent role patterns, skills, templates, QA standards, and release handoff rules.

## Document Map

- `global-operating-principles.md`: Global Harness-wide operating principles, including the Karpathy-style working standard and report requirements.
- `orchestration-execution-standard.md`: Source-of-truth execution standard for preflight, fan-out/fan-in, stage gates, and reporting.
- `orchestration-operating-rules-summary.md`: One-page quick reference for orchestration flow, roles, fan-out/fan-in, and stage gates.
- `orchestration-capabilities-and-boundaries.md`: What orchestration can and cannot do, and how the local runtime stays controlled.
- `orchestration-runtime-engine.md`: CLI-invoked runtime implementation that executes the orchestration standards locally.
- `orchestration-approval-rules.md`: Risk classification, approval prompts, delegated documentation stabilization, and stage-gate boundaries.
- `orchestration-jarvis-bridge.md`: File-based bridge contract between the runtime and Jarvis Assistant.
- `orchestration-jarvis-bridge-readiness.md`: Readiness checklist for connecting the existing bridge contract to Jarvis.
- `stage-gate-reviewer.md`: Stage boundary reviewer role and phase-transition decision rules.
- `stage-gate-final-report-template.md`: One-page final report template for stage gate decisions.
- `memory/knot-v2-semantic-check-standard.md`: Semantic review design for the knot v2 memory-vault checker; file-based only, with no Obsidian app or sync setup.
- `project-patterns/new-project-orchestration.md`: New-project startup pattern, approval rules, and threaded orchestration flow.
- `operating-model.md`: PMO responsibilities and repository boundaries.
- `project-lifecycle.md`: Standard project phases and outputs.
- `project-harness-generation-guide.md`: Step-by-step guide for creating a project harness.
- `agent-team-design-guide.md`: How to design small, useful agent teams.
- `agent-toml-schema.md`: `.codex/agents/*.toml` writing standard and examples.
- `skill-design-guide.md`: How to create reusable skills.
- `template-usage-guide.md`: How to use project harness templates.
- `handoff-artifacts.md`: How to use `_workspace/` safely.
- `qa-standards.md`: Review and verification expectations.
- `release-review-checklist.md`: Pre-release and pre-push checklist.
- `github-workflow.md`: GitHub issue, PR, commit, and release guidance.
- `security-and-secrets.md`: Sensitive-data and secret-handling rules.
- `codex-skill-mirror.md`: Relationship between `.agents/skills/harness/` and `.codex/skills/harness/`.
- `loop-engineering/`: Loop Engineering operating rules, policies, templates, and logs.
- `domain-candidates/`: Future domain-specific skill candidates.

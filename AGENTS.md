# Global GPT Harness Engineering

## Purpose

This repository acts as the Global Harness Engineering PMO for managing Codex-based agent teams, reusable skills, project templates, QA standards, and release workflows.

## Operating Principles

- Understand the user's business purpose before making changes.
- Before editing files, present the plan and target files.
- Split large work into requirements, design, implementation, test, documentation, and QA.
- Keep AGENTS.md concise. Put detailed standards in docs/harness/.
- Store reusable workflows as skills under .agents/skills/.
- Store Codex-specific agent definitions under .codex/agents/.
- Store project templates under templates/.
- Store temporary handoff artifacts under _workspace/.
- Do not store API keys, tokens, passwords, or secrets in the repository.
- Do not use .claude/ paths in this Codex-based repository.

## Project Lifecycle

1. Project intake
2. Requirements analysis
3. Agent team design
4. Skill design
5. Implementation plan
6. Development
7. Testing
8. Documentation
9. Release review
10. Deployment handoff

## Harness Usage

Use the harness skill when designing a new project team, creating reusable skills, defining QA handoffs, or building a project-specific workflow.

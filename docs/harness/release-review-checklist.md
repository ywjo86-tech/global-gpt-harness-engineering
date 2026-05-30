# Release Review Checklist

Use this checklist before committing, pushing, or handing off PMO or project harness work.

## Repository Safety

- [ ] No `.claude/` path was created.
- [ ] `_workspace/` is excluded from default commits.
- [ ] No secrets, API keys, tokens, passwords, or private keys are committed.
- [ ] No raw customer data, raw emails, or confidential procurement data are committed.

## Harness Structure

- [ ] `AGENTS.md` is concise and not overloaded with detailed rules.
- [ ] Detailed operating standards live under `docs/harness/`.
- [ ] Reusable workflows live under `.agents/skills/`.
- [ ] Codex custom agents live under `.codex/agents/` as `.toml`.
- [ ] Domain-specific skills remain candidates unless explicitly approved.

## Documentation

- [ ] `docs/harness/README.md` points to the relevant standards.
- [ ] Project lifecycle guidance exists.
- [ ] Agent design guidance exists.
- [ ] Skill design guidance exists.
- [ ] Security and secrets guidance exists.
- [ ] GitHub workflow guidance exists.

## QA and Testing

- [ ] Changed files were reviewed.
- [ ] Test or manual verification results were recorded.
- [ ] Internal links and paths were checked.
- [ ] Release readiness is marked as Ready, Ready with follow-up, or Blocked.

## Before GitHub Push

- [ ] `git status` shows only intended changes.
- [ ] Commit message describes the PMO or harness change clearly.
- [ ] Remote URL points to the intended GitHub repository.
- [ ] Branch name is correct.
- [ ] No ignored local files need to be preserved elsewhere.

# Security and Secrets

## Do Not Commit

- API keys
- Tokens
- Passwords
- Private keys
- `.env` files
- Raw customer data
- Raw business email content
- Confidential procurement data
- Private supplier contracts or quotes

## Sensitive Working Material

Use `_workspace/` for temporary analysis and handoff files, but treat it as local-only by default.

## Review Expectations

Before committing, inspect changed files for secrets, sensitive data, and accidental raw source material.

## Repository Boundary

This repository defines reusable operating standards. Project-specific confidential data belongs in controlled project systems, not in the PMO repository.

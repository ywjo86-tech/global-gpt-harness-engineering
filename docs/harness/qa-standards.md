# QA Standards

## Review Priorities

1. Security and secret handling
2. Correct repository paths
3. Internal consistency
4. Test or verification coverage
5. Documentation completeness
6. Release readiness

## Required Checks

- `.codex/agents/` files use TOML.
- `.agents/skills/` contains only approved skills.
- `_workspace/` is ignored by default.
- No `.claude/` paths exist.
- Sensitive data is not committed.
- Templates and docs use matching lifecycle language.

## Release Decision

Use one of:

- Ready
- Ready with follow-up
- Blocked

Blocked decisions require a concrete reason and a next action.

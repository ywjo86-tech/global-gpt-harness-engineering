# Codex Skill Mirror

This repository currently keeps the harness skill in two locations:

- `.agents/skills/harness/`
- `.codex/skills/harness/`

## Current Policy

Keep both directories for now as a Codex compatibility mirror.

`.agents/skills/harness/` is the PMO-standard location for reusable repository skills. `.codex/skills/harness/` is retained so Codex-specific discovery or runtime behavior can continue to work if it expects skills under `.codex/skills/`.

## Operating Rule

When changing the harness skill, review both copies and keep their intent aligned. Do not delete either location during routine PMO work.

## Future Review

Whether this mirror is still necessary should be reviewed separately after confirming the active Codex skill discovery behavior.

Possible future outcomes:

- Keep both paths as a documented mirror.
- Move to `.agents/skills/` only.
- Replace one path with generated or scripted synchronization.

Do not make that decision as part of ordinary project harness generation.

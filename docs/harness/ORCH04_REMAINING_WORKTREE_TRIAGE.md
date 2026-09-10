# ORCH04 Remaining Worktree Triage

> Status: **TRIAGED — COMMIT GROUPING RECOMMENDED**
>
> Recorded: `2026-09-11`
>
> Scope: uncommitted worktree state after proof97 `CONDITIONAL GO` commit/push

## 1. Purpose

This document classifies the remaining uncommitted worktree after the proof97
`CONDITIONAL GO` packet was committed and pushed.

It is a triage record only. It does not authorize deleting files, rewriting history,
deployment, or pushing additional commits.

## 2. Current Baseline

Latest committed and pushed proof97 checkpoint:

```text
3439438246b4f6d95b2efb2a74b364f34f41682b
feat(orchestrator): seal proof97 conditional go
```

Current branch:

```text
migration/hamonikr-linux
```

Latest directly executed full regression in the dirty worktree:

```text
Ran 1067 tests in 50.559s
OK (skipped=5)
```

## 3. High-Level Classification

The remaining worktree is not a simple temporary residue. It contains the larger ORCH04
integration body that predates or surrounds the proof97 evidence packet.

Recommended grouping:

| Group | Classification | Examples | Recommended handling |
|---|---|---|---|
| A | R4/R4.1/R4.2 authority and stage evidence docs | `R4_AUTHORITY_INDEX.md`, `G_ORCH_01_STAGE_GATE_DECISION.md`, `G_ORCH_02_STAGE_GATE_DECISION.md`, `G_ORCH_03_STAGE_GATE_DECISION.md`, `G_4A_ACTUAL_STAGE_GATE_DECISION.md` | Commit as an authority/evidence documentation packet after checking stale labels. |
| B | ORCH04 canonical/runtime implementation body | `canonical_*`, `completion_*`, `migration_*`, `production_*`, `worker_authority.py`, related tests | Commit as one or more implementation packets only after focused regression grouping. |
| C | Imported source packages / working roots | `R4 Architecture Freeze/`, `global-gpt-harness-orch02/`, `global-gpt-harness-orch03/`, `global-gpt-harness-orch04/` | Do not commit blindly; contains nested `.git` directories and transfer archives. Decide whether to keep as local reference, package selectively, or ignore. |
| D | New reusable skill candidate | `.agents/skills/generate-reference-diagram/` | Caution item because it modifies skill inventory. Review separately before commit. |

## 4. Modified Tracked Runtime/Test Files

Tracked files with unstaged modifications:

- `runtime/orchestrator/canonical_paths.py`
- `runtime/orchestrator/cli.py`
- `runtime/orchestrator/completeness.py`
- `runtime/orchestrator/gate_controller.py`
- `runtime/orchestrator/gate_orchestrator.py`
- `runtime/orchestrator/lv_execution_package.py`
- `runtime/orchestrator/lv_preview.py`
- `runtime/orchestrator/lv_review.py`
- `runtime/orchestrator/production_context.py`
- `runtime/orchestrator/production_decision.py`
- `runtime/orchestrator/production_gate_runner.py`
- `runtime/orchestrator/production_worker_executor.py`
- `runtime/orchestrator/resume_store.py`
- related tests under `tests/`

Observed diff size:

```text
25 files changed, 9003 insertions(+), 234 deletions(-)
```

Interpretation:

- This is a large implementation packet, not a cleanup-only change.
- It should not be mixed with imported candidate packages or skill inventory changes.
- It already participated in the latest 1,067-test regression, but focused grouping
  should still be used before commit.

## 5. Untracked Documentation and Authority Files

Untracked authority/evidence docs include:

- `DEC-011_ISSUE-095_MIGRATION_QUALITY_AUTHORITY_DECIDED.md`
- `G_ORCH_01_STAGE_GATE_DECISION.md`
- `G_ORCH_02_STAGE_GATE_DECISION.md`
- `G_ORCH_03_STAGE_GATE_DECISION.md`
- `G_4A_ACTUAL_STAGE_GATE_DECISION.md`
- `G_4A_ACTUAL_READINESS_PLAN.md`
- `G_4A_ACTUAL_LIVE_READINESS_COMMAND_PACKAGE.md`
- `G_4A_ACTUAL_PROOF97_FIXTURE_PLAN.md`
- `G_4A_ACTUAL_DESIGN_DIAGNOSIS.md`
- `R4_AUTHORITY_INDEX.md`
- R4.1/R4.2 authority amendment files
- working DP/SC candidate files

Interpretation:

- These files explain the authority trail that led to proof97.
- They should likely be committed before, or together with, the large implementation
  packet so future reviewers can understand why the runtime changed.
- Existing historical `NO-GO` documents should remain append-only and not be overwritten
  by the later proof97 `CONDITIONAL GO` artifact.

## 6. Imported Working Roots and Archive Risk

The following untracked directories are high-risk commit candidates:

- `global-gpt-harness-orch02/`
- `global-gpt-harness-orch03/`
- `global-gpt-harness-orch04/`

Observed risk:

- They contain nested `.git` entries.
- They contain transfer archives such as `.zip` packages.
- They appear to be source/reference working roots rather than clean repository files.

Recommendation:

- Do not add these directories wholesale.
- If they are needed as evidence, extract only deliberate docs/checksums into a curated
  `docs/harness/` or archive-manifest record.
- If they are local reference material only, leave them uncommitted or add a future
  ignore rule only after explicit caution-work approval.

## 7. Skill Candidate Risk

Untracked skill:

- `.agents/skills/generate-reference-diagram/`

Observed files:

- `SKILL.md`
- `agents/openai.yaml`

Recommendation:

- Review separately as a reusable skill inventory change.
- Do not bundle with ORCH04 runtime implementation unless the Gate requires this skill.

## 8. Recommended Next Execution Order

1. Run a stale-state scan over untracked authority/evidence docs.
2. Commit Group A: R4/R4.1/R4.2 and ORCH01~G-4A authority/evidence docs.
3. Run focused implementation tests for the remaining runtime/test implementation body.
4. Commit Group B: ORCH04 canonical/runtime implementation body.
5. Separately decide whether to keep, ignore, or curate Group C imported working roots.
6. Separately review Group D skill candidate.
7. Only after the worktree is clean enough, prepare the next Gate handoff.

## 9. Current Recommendation

Proceed next with Group A documentation/evidence packet.

Reason:

- It is the least risky remaining commit.
- It preserves the authority trail for the already pushed proof97 decision.
- It gives reviewers context before the larger runtime implementation packet is committed.

Current Gate posture:

```text
proof97: CONDITIONAL GO committed and pushed
remaining worktree: triaged, not yet clean
next safe step: Group A documentation/evidence packet
```

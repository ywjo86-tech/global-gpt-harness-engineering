# TASK-003 Publication Safety Test Matrix

TEST-009 git_stage: exact pathspec only; candidate/worktree/HEAD/index digests; unrelated scope and extra staged entries blocked.
TEST-010 git_commit: requires sealed stage/index evidence; exact HEAD/parent; bounded subject; extra index content blocked.
TEST-011 git_push: exact remote/branch/local commit/expected remote head; URL fingerprint/protected branch/NFF checks; force/delete/tag/refspec expansion unavailable.
TEST-012 guards: authorization/policy/scope/digest mismatches and unrelated changes fail closed.
TEST-013 ambiguity: ambiguous push never auto-replays; remote ref reconciliation precedes retry decision.

Negative-space assertions: no generic git command passthrough; no force/reset/rebase/history rewrite; no implicit remote/branch discovery authority; no provider/model logic; no MPRF internal access; no duplicate action-effect source of truth.

# TASK-003 EXEC-AUTH-EXT-001 Publication Authority Specification

Status: FOUNDATION_COMPLETE / READY_FOR_TASK-004_AND_TASK-005
Date: 2026-09-17
Authority: GATE-001 GO; TASK-003 is non-activating design/patch foundation.

## Closed publication operation set
Exactly three new state-changing publication operations are permitted by this extension proposal: `git_stage`, `git_commit`, `git_push`. No generic `git argv`, force, reset, rebase, history rewrite, ref deletion, tag publication, or arbitrary refspec operation is added.

## GitPublicationAuthorization.v1
Required bindings: project/repository identity digest, approved branch, approved remote name and URL fingerprint, allowed path digest, expected remote head, protected-branch policy reference, approval reference, issued/expiry timestamps, exact operation set, and immutable policy digest.
Publication calls require InvocationContext.v2 to contain the exact publication policy digest in `operation_policy_digests`.

## GitStageIntent.v1
Inputs: exact path list, expected worktree digest, expected HEAD, candidate diff digest, publication policy digest.
Output evidence: staged paths, index digest before/after, staged diff digest.
Fail closed on unapproved path, unrelated index drift, worktree/HEAD drift, candidate digest mismatch, symlink/path-policy escape, or extra staged entries.

## GitCommitIntent.v1
Inputs: expected staged diff digest, expected index digest, expected HEAD/parent, bounded one-line subject, publication policy digest.
Output evidence: commit SHA, tree SHA, parent SHA, committed diff digest.
Fail closed if the index differs from sealed stage evidence, parent/HEAD moved, message is invalid, or extra staged content exists.

## GitPushIntent.v1
Inputs: exact remote, exact branch, local commit SHA, expected remote head, publication policy digest.
Output evidence: pre/post remote head, push status, remote reconciliation evidence.
Only non-force fast-forward push of the approved branch is allowed. Stale remote, wrong remote URL fingerprint, protected-branch policy failure, non-fast-forward, delete/tag/other refspec, or force flags are blocked.
Transport ambiguity transitions to `ACTION_SIDE_EFFECT_AMBIGUOUS`; remote state is reconciled before any retry decision and automatic replay is prohibited.

## Effect semantics
Full MCP remains canonical owner of action/effect truth. Publication evidence references effect/audit records but does not duplicate the canonical ToolEffectJournal. Stage/commit/push use distinct operation request identities so each side effect is replay-protected and reconcilable.

## Compatibility
Existing git read/status/diff/branch/restore/prepare_commit contracts remain unchanged. InvocationContext.v1 remains valid for existing operations; publication operations require InvocationContext.v2 and exact policy binding.

# TASK-005 Controlled Authority Extension Qualification

Status: PASS_CANDIDATE_FOR_GATE003
Date: 2026-09-17
Scope: TASK-005 Full MCP controlled publication/public-boundary extension only.

## Implemented authority
- InvocationContext.v1 remains compatible and cannot bind operation policies.
- InvocationContext.v2 binds exact `operation_policy_digests` for publication authority.
- Exactly three new publication operations exist when a v2 publication authorization is supplied: `git_stage`, `git_commit`, `git_push`.
- No force/reset/rebase/history rewrite/ref deletion/tag publication/generic git argv operation exists.
- GitPublicationAuthorization.v1 binds repository identity, exact branch/remote URL fingerprint, exact allowed-path digest, expected remote head, protected-branch policy ref, approval ref, validity window, and exact operation set.

## Exact side-effect chain
`git_stage` requires clean index delta, exact changed path set, HEAD/worktree/candidate digest match, then returns pre/post index and staged-diff digests.
`git_commit` requires sealed staged-diff/index/HEAD/parent evidence and bounded one-line subject, then returns commit/tree/parent/committed-diff evidence.
`git_push` uses a fixed non-force refspec, exact remote/branch/local commit/fresh remote head, fast-forward proof, remote URL fingerprint, and post-push reconciliation. Automatic ambiguous replay is not implemented.

## Authority/effect preservation
All three operations pass through the existing Full MCP authorization contract, replay guard, ToolEffectJournal and ObservabilityStore. PublicationEvidence is a digest-bound projection only and does not replace canonical effect truth.
The public DTO layer projects only public arguments/status/effect/reconciliation/error/audit references; no MPRF import of Full MCP internals or Provider Router is introduced.
HOST-GATEWAY wire code remains unchanged.

## Validation
Focused suite: `tests.test_public_execution_contract`, `tests.full_mcp.test_git_publication`, `tests.full_mcp.test_git`, `tests.full_mcp.test_observability_recovery`.
Result: 17 PASS, 0 FAIL, 0 ERROR.
Python compile for controlled modules: PASS.
`git diff --check` for controlled modules/tests: PASS.
Static forbidden-surface scan: no force/reset/rebase/delete publication command surface found.

## Environment limitation
The pre-existing MCP stdio adapter tests still require the external `mcp` Python package, which is absent from the system Python environment. The adapter module compiles, and the public-to-AdapterToolCall bridge is implemented, but stdio integration regression remains explicitly deferred to the later Full MCP regression gate where that dependency must be restored.

## Disposition
TEST-007: PASS for TASK-005 scope.
TEST-008: PASS for TASK-005 scope.
TEST-009: PASS for exact git_stage scope/digest/index guards.
TEST-010: PASS for exact git_commit staged-tree/index/parent guards.
TEST-011~014 are not claimed here; they belong to TASK-006 / GATE-004 ordered security qualification.

# TASK-003 Controlled Patch Proposal

This package proposes, but does not yet activate, the following TASK-005 changes:
1. `runtime/full_mcp/contracts.py`: add InvocationContext.v2 with `operation_policy_digests` and publication authorization/intent DTO validation while retaining v1 compatibility.
2. `runtime/full_mcp/authorization.py`: require exact publication policy digest binding for publication operations.
3. `runtime/full_mcp/git_service.py`: add dedicated `stage`, `commit`, `push` primitives with exact digest/freshness/NFF/remote guards; no arbitrary argv surface.
4. `runtime/full_mcp/runtime.py`: register exactly `git_stage`, `git_commit`, `git_push`, wire closed schemas and dispatch, preserve existing operation set.
5. `runtime/full_mcp/publication_evidence.py`: immutable publication evidence helpers and ambiguous push reconciliation projection.
6. `tests/full_mcp/test_git.py` + `test_git_publication.py`: contract/safety/negative-space tests.

Application is deferred to TASK-005 after TASK-004 public-boundary contract is complete, as required by the approved task graph.

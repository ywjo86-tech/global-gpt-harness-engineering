# G-4A-ACTUAL Stage Gate Decision

> Decision: **NO-GO**
>
> Phase: `G-4A-ACTUAL`
>
> Decision date: `2026-09-10`
>
> Reviewer: independent `stage-gate-reviewer`

## Accepted Partial Evidence

- pre-proof full local regression: 1,060 PASS / 3 skipped.
- installed Codex dynamic transport: 1 PASS.
- initial DEC-007 broker path timeout retained as negative evidence.
- remediated DEC-007 focused rerun: 1 PASS.
- actual Codex worker fixture: 1 PASS.
- post-remediation focused suite: 10 PASS / 2 skipped.
- post-remediation full local regression: 1,060 PASS / 3 skipped.

These results prove partial actual-readiness only: installed Codex reachability, one closed
dynamic transport path, one actual DEC-007 READ broker path after remediation, and one
actual worker fixture path.

## Blocking G-4A Criteria

The submitted evidence does not prove the R4 immutable A-to-B proof97 story. Missing:

- sealed immutable proof97 fixture.
- fixed proof `RUN_ID`, package, owned-file digest bundle, and crash point.
- fresh secret-free `CodexAuthReadinessEvidence=READY` plus adjacent recheck artifact.
- actual Broker WRITE.
- forced expected crash after durable effect.
- same-`RUN_ID` resume.
- duplicate Worker/effect/checkpoint count of zero after resume.
- product-owned frozen node execution.
- independent actual verifier, Post-Quality, and handoff evidence.

## AF_UNIX Decision

The two AF_UNIX gateway skips are not accepted as completed G-4A evidence. They may remain
deferred only while proof97 stays `HOLD`.

Before G-4A `GO`, the project must provide one of:

- authenticated production UDS round trip and one-command smoke in an environment that
  permits AF_UNIX; or
- reviewer-accepted equivalent evidence covering authenticated gateway round trip,
  durable ledger/Intent/Receipt behavior, one-command smoke, and fail-closed production
  boundary.

The current dynamic transport and DEC-007 READ evidence are not equivalent because they do
not exercise AF_UNIX gateway bind, round trip, or smoke.

## Same-Stage Remediation Decision

The `tests/test_production_tool_transport.py` remediation is accepted as a bounded
diagnostic/readiness-probe fix:

- it changed prompt determinism to `exactly once`;
- it raised the hard timeout to `180` seconds;
- it did not weaken assertions or runtime authorization;
- the original timeout is preserved as negative evidence;
- focused and full post-change regressions passed.

However, this is not immutable proof97 evidence. Before proof execution, the final
test/runner digest must be pinned and the immutable story must run without edits.

## Issue Effect

- `ISSUE-025`: unchanged and Critical/Open.
- `ISSUE-059`: unchanged/open.
- `ISSUE-060`: unchanged/open.
- `ISSUE-063`: unchanged/open.
- `ISSUE-064`: unchanged/open.
- `ISSUE-065`: unchanged/open.
- `ISSUE-066`: unchanged/open.
- prior scoped `ISSUE-068` and `ISSUE-095` resolutions remain unchanged.
- `ISSUE-092`: unchanged; retired by append-only disposition only.

## Required Next Order

1. obtain AF_UNIX or exact equivalent production evidence.
2. collect and pin fresh live readiness plus adjacent recheck.
3. materialize and digest-seal proof97 fixture/runner, frozen product nodes, fixed
   `RUN_ID`, package, owned scope, and crash point.
4. rerun full pre-proof regression if any bytes change.
5. execute one immutable actual WRITE to durable Intent/Receipt to expected crash to
   same-`RUN_ID` resume story.
6. collect duplicate counts of zero, frozen product tests, independent verifier,
   Post-Quality, and handoff.
7. request independent G-4A re-review.

## Stage Exit Decision

```text
NO-GO
proof97 = HOLD
```

# OCPv2 R2 implementation ledger

Plan: `OPERATOR_CONTROL_PLANE_V2_R2.1_IMPLEMENTATION_PLAN_ALL_PASS.md`
Branch: `impl/operator-control-plane-v2-r2`
Bound source: `e2ce97a3741c070e538f817113a1b90845cc53c3`
Approved R2 authority SHA-256: `9e4991292ba087b8e0eb53188153556c998a5f06806a8989b38c74c88b573ced`
Approved R2.1 implementation-plan SHA-256: `44ed023860fe9d89e1a4f051e3ec4a685ab292b6db664306c37355d9de48c0ed`
Execution mode: Full Plan HYBRID

Task 0: complete
- Authority binding record: `docs/superpowers/specs/2026-09-21-operator-control-plane-v2-r2-approved.md`
- Hosted CI commit: `c0cc829bda540fba4ef1e0386ebc059bfad3627c`
- Hosted CI run `35564490598`: PASS
- RDC calls required: 0
- Ruling: the public repository contains only the SHA-bound authority projection; the byte-identical approved artifact remains external and authoritative. No live secret, queue, server-path, approval digest, or live migration evidence is made repository authority.

Pre-flight shared interfaces:
- Task 1 envelope -> Tasks 2/4/9/10: immutable validated remote message contract.
- Task 2 receipt ledger -> Tasks 4/8/11: replay/tamper state only; never canonical project state.
- Task 3 outbox -> Tasks 8/9/10/11/14: projection-only retry; never re-execute mutation.
- Task 4 ingress -> Tasks 5/6/7/11: existing `OperatorDirectiveV1`; no new stage authority.
- Task 5 canonical entry -> Tasks 6/7/8: existing Full Plan owner epoch + transaction lock is the only writer boundary.
- Task 7 migration wrapper -> Gate E: exact migration transaction/phase CAS; no migration recreation.
- Task 9 transport -> Tasks 10/11/14: transport API exposes no mutation primitive.

Task 1: complete — Remote operator envelope
- RED run `35564595205`: expected missing-module failure.
- Initial GREEN attempt `35564644696`: implementation passed all behaviors except a test-harness expectation around deliberately forbidden provider/model fields.
- Ruling: `seal_remote_envelope()` correctly delegates to existing `OperatorDirectiveV1` and rejects provider/model fields before validation. The test expectation was moved to the sealing boundary because earlier fail-closed behavior preserves the approved operator contract.
- GREEN run `35564724551`: PASS.
- Envelope implementation commit: `bd58c2ee147f37fa52759e710bad49a4dbaea970`.
- Final Task-1 test commit: `556b1fdcee0d11fbf8786737caff434fb1affc13`.

Task 2: complete — Durable receipt/replay
- RED run `35564814357`.
- First GREEN run `35564854493`: one dangling-symlink case remained.
- Fix commit: `015c9101fec1c16ec17eb2b9b31d28cf4d360c08` checks `is_symlink()` before existence on receipt/channel/previous-generation paths.
- GREEN run `35564912397`: PASS.

Task 3: complete — Durable result outbox
- RED run `35564965586`.
- Implementation commit: `9ac3da534822032601d531cbdae743440ce4cb92`.
- GREEN run `35565007322`: PASS.
- Result delivery remains projection retry only; it does not own canonical completion or re-execute mutation.

Task 4: complete — Non-authoritative ingress
- RED run `35565083823`.
- Implementation commit: `6a50c556a475fcf1f3952b6b08c4521250897770`.
- GREEN run `35565123419`: PASS.
- Ingress reuses existing `OperatorDirectiveV1`, validates source/risk/replay identity, records transport receipt only, and creates no new stage authority.

Task 5: complete — Single writer / canonical CAS entry
- RED run `35565227159`.
- Ruling: the narrow integration helper remains outside the authoritative Full Plan module and exclusively calls existing supervisor owner/epoch/transaction APIs. No OCP lock or lease exists.
- Implementation commit: `8eb5f1c2d51449671f41ada8b1757278d62b00f0`.
- GREEN run `35565299164`: PASS.

Task 6: complete — Production gateway boundary
- RED run `35565449238`.
- Implementation commit: `475d1d4ce2ee8d220beef937cc21990a63af95b3`.
- GREEN run `35565502046`: PASS.
- State-changing `PREPARE -> ACTION` requires canonical gateway authority and exact project/run/gate/task binding. Gateway failure has no direct-execution fallback.

Task 7: complete — Migration-v2 CAS wrapper
- RED run `35565607167`.
- Ruling: `MigrationStore` remains unchanged; OCP performs exact transaction/phase/evidence comparison and delegates mutation to existing `MigrationStore.advance()` only while inside the canonical owner/transaction protection.
- Implementation commit: `9b94738f00372899cdd04cd6d3e5429de1a0472e`.
- GREEN run `35565651714`: PASS.
- No live migration transaction was created, advanced, closed, recreated, or published by this implementation task.

Task 8: complete — Crash-after-mutation reconciliation
- Final implementation commit: `15c47fee236063d7425dd91611f1a3f801052b28` (`fix(ocp): expose canonical completion reconciliation contract`).
- GREEN run `35565901660`: PASS.
- Recovery distinguishes durable canonical completion evidence from downstream delivery/projection state. Retry reconciles canonical state rather than re-executing a completed mutation.

Task 9: complete — Transport-neutral control contract
- Implementation commit: `25acc2da48ac7aa149c554a780b03605c8d6a2a4`.
- GREEN run `35566056687`: PASS.
- `RemoteOperatorTransport` is delivery/projection only: receive, acknowledge delivery, publish projection. It owns no canonical execution or completion authority.

Task 10: complete — Private GitHub control transport
- Implementation commit: `159f35eda2762293e040596d9792a1d98021e1e9`.
- GREEN run `35566342203`: PASS.
- Exact numeric repository/PR/actor checks, non-symlink private token-file checks, and secret scanning are fail-closed.
- Public source repository ID `1254385549` is explicitly rejected as a control repository.
- No live private control repository or token was created during source implementation.

Task 11: complete — Authorization-gated one-shot service
- Implementation commit: `575adf26b3c285b07d2f36dfbd11fb9c1f47b855`.
- GREEN run `35566516009`: PASS.
- `DISABLED`, `OBSERVE_ONLY`, `CONTROL_READ_ONLY`, `CONTROL_MUTATION_CANARY`, and `ACTIVE` are closed control modes. Bootstrap composition installs no mutation executor for the non-mutating modes.
- Service owns no scheduling, provider routing, canonical locks, or direct mutation authority.

Task 12: complete — Operator console projection
- Implementation commit: `33387ea455700939d13900d7ad96fc7b165e45fe`.
- GREEN run `35570221528`: PASS.
- Console projection is a frozen, closed-field, non-authoritative view. Unknown/provider/model fields are not elevated into control authority, and normalization reuses the remote-envelope validator.

Task 13: complete — Static authority audit and whole-repository regression
- Authority negative-space audit verifies that OCP transport/service/console code has no direct shell/execution/broker/provider-selection authority, migration mutation remains bounded, and systemd references remain deployment-only.
- Full-regression runner was made hermetic for two legacy CI fixtures without weakening product validation: one safe external-Python fixture and one fake uid-map fixture bound to the runner's actual UID.
- Interruption/root-cause record: `docs/harness/OCPV2_R2_INTERRUPTION_20260921.md`.
- Exact implementation HEAD before final documentation: `e336e5d7e3ddd7f0028171b250dcbde5e18cd452`.
- Exact-head CI run `35584359324`: focused PASS; full repository regression PASS; regression-delta PASS.
- Full regression evidence: `2066` tests run, `0` failures, `0` errors, `14` skipped.
- The previously observed TemporaryDirectory `.git/objects` cleanup error did not reproduce on this exact-head run and is retained only as historical transient diagnostic evidence, not as a current product blocker.

Task 14: complete — Prepared-only deployment package
- Initial deterministic bootstrap implementation commit: `c1c807a792cfd00335959af65a566d2b0bc6a1be`; GREEN run `35566861208`.
- Final hardening commit: `e336e5d7e3ddd7f0028171b250dcbde5e18cd452`.
- Public example configuration uses the generic `/path/to/global-gpt-harness-engineering` placeholder; no live Jarvis path is committed.
- `deploy/operator-control-plane-v2/README.md` states PREPARED ONLY, separate Gate B authorization, default DISABLED, first live target OBSERVE_ONLY, dedicated private control repository, token-file `0600`, and no provider/model selection authority.
- Non-mutating composition now constructs the durable result outbox and replays only already-sealed strict result projections. This recovery path is transport delivery only and grants no execution/completion/provider-routing/canonical-mutation authority.
- `install-user-service` writes reviewed user-level files only and never invokes `systemctl`.
- Exact-head CI run `35584359324`: PASS across focused deploy/authority tests, whole-repository regression, and baseline/current delta.

Implementation status after Task 14:
- Source implementation: COMPLETE pending final documentation-only exact-head re-verification.
- Live bootstrap/systemd install: NOT PERFORMED.
- Dedicated private control repository/token: NOT CREATED.
- Live migration: UNCHANGED by OCPv2 implementation.
- CONTROL_MUTATION_CANARY: NOT ENABLED.
- Production ACTIVE: NOT ENABLED.
- Merge to `main`: NOT PERFORMED.
- Next live boundary: separate Gate B authorization; it is not implied by source completion.

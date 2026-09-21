# OCPv2 R2 implementation ledger

Plan: `OPERATOR_CONTROL_PLANE_V2_R2.1_IMPLEMENTATION_PLAN_ALL_PASS.md`
Branch: `impl/operator-control-plane-v2-r2`
Bound source: `e2ce97a3741c070e538f817113a1b90845cc53c3`

Task 0: complete
- Authority binding record: `docs/superpowers/specs/2026-09-21-operator-control-plane-v2-r2-approved.md`
- Hosted CI commit: `c0cc829bda540fba4ef1e0386ebc059bfad3627c`
- Hosted CI run `35564490598`: PASS
- RDC calls required: 0

Ruling: the GitHub connector cannot atomically upload the local approved 44KB artifact by local path. The branch therefore binds implementation authority to the approved artifact SHA-256 `9e4991292ba087b8e0eb53188153556c998a5f06806a8989b38c74c88b573ced` and retains the byte-identical approved artifact outside the repository. This does not change any runtime contract; the repository pointer is non-authoritative and the SHA-bound approved artifact remains the source authority.

Pre-flight shared interfaces:
- Task 1 envelope -> Tasks 2/4/9/10: immutable validated remote message contract.
- Task 2 receipt ledger -> Tasks 4/8/11: replay/tamper state only; never canonical project state.
- Task 3 outbox -> Tasks 8/9/10/11: projection-only retry; never re-execute mutation.
- Task 4 ingress -> Tasks 5/6/7/11: existing `OperatorDirectiveV1`; no new stage authority.
- Task 5 canonical entry -> Tasks 6/7/8: existing Full Plan owner epoch + transaction lock is the only writer boundary.
- Task 7 migration wrapper -> Gate E: exact migration transaction/phase CAS; no migration recreation.
- Task 9 transport -> Task 10/11: transport API exposes no mutation primitive.

Task 1: complete
- RED run `35564595205`: expected missing-module failure.
- Initial GREEN attempt `35564644696`: implementation passed all behaviors except a test harness error around deliberately forbidden provider/model fields.
- Ruling: `seal_remote_envelope()` correctly delegates to existing `OperatorDirectiveV1` and rejects provider/model fields before validation. The test expectation was moved to the sealing boundary because earlier fail-closed behavior is stronger and exactly preserves the approved operator contract.
- GREEN run `35564724551`: PASS for remote envelope, operator regression, continuation locking, migration, production gateway, production tool transport, compileall, and diff check.
- Envelope implementation commit: `bd58c2ee147f37fa52759e710bad49a4dbaea970`.
- Final Task-1 test commit: `556b1fdcee0d11fbf8786737caff434fb1affc13`.

Task 2: complete
- RED run `35564814357`: receipt/replay contract failed before implementation as expected.
- First GREEN run `35564854493`: all receipt behaviors passed except dangling symlink rejection.
- Root cause: `Path.exists()` is false for a dangling symlink, so the old guard could treat an unsafe symlink as absent.
- Fix commit: `015c9101fec1c16ec17eb2b9b31d28cf4d360c08` checks `is_symlink()` before existence on receipt/channel/previous-generation paths.
- GREEN run `35564912397`: PASS.

Task 3: complete
- RED run `35564965586`: projection-only durable outbox contract failed before implementation as expected.
- Implementation commit: `9ac3da534822032601d531cbdae743440ce4cb92`.
- GREEN run `35565007322`: PASS.
- Result delivery remains a projection retry only; it does not own canonical completion or re-execute mutation.

Task 4: complete
- RED run `35565083823`: non-authoritative ingress bridge contract failed before implementation as expected.
- Implementation commit: `6a50c556a475fcf1f3952b6b08c4521250897770`.
- GREEN run `35565123419`: PASS.
- Ingress reuses existing `OperatorDirectiveV1`, validates source/risk/replay identity, records transport receipt only, and creates no new stage authority.

Task 5: complete
- RED/integration runs established the canonical single-writer contract, including failed integration run `35565277015` before the final helper implementation.
- Implementation commit: `8eb5f1c2d51449671f41ada8b1757278d62b00f0`.
- GREEN run `35565299164`: PASS for envelope, receipt, outbox, ingress, single-writer, operator, continuation locking, migration, production gateway/tool transport, compileall and diff check.
- The remote mutation path converges on the existing Full Plan continuation-owner epoch and transaction lock; no OCP-owned lock/lease was introduced.

Task 6: complete
- RED run `35565449238`: production gateway boundary contract failed before bridge implementation as expected.
- Implementation commit: `475d1d4ce2ee8d220beef937cc21990a63af95b3`.
- GREEN run `35565502046`: PASS.
- State-changing `PREPARE -> ACTION` requires canonical gateway authority and exact project/run/gate/task binding before one gateway dispatch; read-only transitions do not enter mutation gateway; gateway failure does not fall back to direct execution.

Next task: Task 7 — Migration-v2 CAS integration (TDD RED first).

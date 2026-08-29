# Orchestration Runtime

## Production approval v2 foundation

Production execution uses `orchestration.production-approval.v2` events. Legacy
`orchestration.gate-approval.v1` evidence remains readable for historical and
compatibility inspection, but the production controller boundary does not accept
it as authorization.

Create or correct an event with the official CLI:

```bash
python3 -m runtime.orchestrator.cli production-approval-create \
  --project-root PROJECT --output governance/approval-v2.json \
  --gate-id GATE-1 --plan-sha256 SHA256 --scope-file SCOPE.json \
  --authorization-source USER_OWNER

python3 -m runtime.orchestrator.cli production-approval-correct \
  --project-root PROJECT --output governance/approval-v2.json \
  --gate-id GATE-1 --plan-sha256 SHA256 --scope-file SCOPE.json \
  --authorization-source USER_OWNER --supersedes EVENT_ID
```

Both commands bind the actual UTC clock, attached Git branch, and baseline HEAD.
`--dry-run` and `--read-only` validate without writing. Writes use a temporary
file, fsync, and atomic replacement. The scope file contains exactly
`canonical_lv_scope`, `owned_file_scope`, and
`completion_conditions_sha256`.

Canonical plan mappings can be migrated atomically with
`production-mapping-migrate`. Production Gate execution additionally requires a
canonical v2 Gate state with `READY_FOR_TRANSITION` and `CLOSED`, and rejects
descendants that changed product files after the approval baseline.

This package contains the local runtime orchestration engine used by the Global GPT Harness Engineering repository.

## Stage 1

Stage 1 established the local Python orchestration engine for planning, fan-out, fan-in, approval gating, and stage gating.

## Stage 2

Stage 2 adds a Codex execution adapter on top of the same file-based runtime.

- `manual` mode creates task prompts and waits for human execution.
- `codex-cli` mode best-effort runs task prompts through a local Codex CLI when available.
- `mock` mode keeps the local worker path for smoke tests and deterministic validation.
- `collect` gathers worker outputs into a collection report.
- `fanin` merges collected outputs into a fan-in report and prompt.
- `gate` creates or runs the stage gate review prompt and result.
- `inspect --read-only` validates a project-scoped contract mapping, source hashes, and static approval/gate evidence without constructing the runtime engine or writing state, logs, approvals, fan-out/fan-in outputs, or Gate artifacts.

Project-scoped mappings are opt-in. Projects without a mapping keep the legacy strict contract paths and fail-closed behavior. Mapping paths must stay relative to the selected project root, and mapped source hashes must match before a contract can load.

Read-only output keeps `business_lv_approval_state` and `business_gate_state` separate from `codex_runtime_sandbox_approval_state`. Static business or Gate evidence is never converted into, or reused as, Codex runtime/sandbox authorization.

Current runtime work items are recorded in `docs/harness/orchestration-runtime-work-items.md`.
Jarvis bridge contract is documented in `docs/harness/orchestration-jarvis-bridge.md`.
Jarvis connection readiness is documented in `docs/harness/orchestration-jarvis-bridge-readiness.md`.

The document-based orchestration rules in `docs/harness/` remain the reference contract. This runtime layer expands them into executable file-based workflows without requiring external servers, queues, or databases.

## Manual single-LV worker prompt

`lv-package` derives the manual worker prompt only from the sealed manifest's
Stage purpose, execution mode, dependencies, completion checks, and exact owned
files. Owned `tests/test_*.py` paths determine the focused pytest command; the
project venv pytest command remains the full regression command. Missing or
malformed Stage fields, owned paths, or focused tests fail closed before a
package can be sealed.

The prompt treats every non-owned path as out of scope, forbids guessing API
schemas or implementation details absent from the canonical contract, and
retains the Git, network/API, package-installation, secret, approval, and
baseline boundaries. The worker must emit the bound worker-result schema and
stop. Review is a separate hard stop and cannot automatically start another LV
or advance a Gate.

# Wallet Gate 0 canonical transition

The wallet project mapping uses the Gate 0 states plus opt-in Gate 1 transition
states. `PRE_CHECKPOINT` selects
the approved V20 source. A working-tree-only `CLOSED`/`PASS` declaration is
rejected until a valid Gate 0 checkpoint is found in Git `HEAD`'s first-parent
history. The checkpoint's committed Gate report and approval count, head, full
record hashes, and chain must validate. The current `HEAD` approval log must
preserve and correctly extend that committed chain.
`GATE0_CLOSED_WAITING_GATE1_APPROVAL` reports the verified ancestor commit as
the checkpoint while continuing to select V20. Only a separate, mapped Gate 1
approval committed at the current `HEAD` and bound to the configured
`IMPLEMENTATION_PLAN.md` SHA-256 produces `TRANSITION_READY`. Working-tree-only
approval changes fail closed. `TRANSITION_READY` is authorized but not started
and does not require a Gate State ledger. A mapped project may opt in to
`static_validation.gate_state_ledger`; a committed, validated `GATE1_ACTIVE`
JSON ledger upgrades the report and includes the first-parent activation commit
and committer timestamp. The ledger never stores its own commit SHA. A
checkpoint SHA written inside the Gate report is never used as evidence.

Approval versions are sequential within a lineage keyed by `(target_type,
target_id)`, so the first event for each new target starts at version 1 and
links to no prior approval ID. Later events for that target increment the
lineage version and link to its prior approval ID. Independently, every event's
`previous_record_hash` links the full append order across all target lineages.

## Single-LV review artifacts

`lv-review` requires both a run ID and an explicit canonical positive integer
review attempt:

```text
python3 -m runtime.orchestrator.cli lv-review --run-id <run-id> --attempt 2
```

Values such as a missing attempt, `0`, `-1`, `01`, `+1`, or mixed text fail
closed. Review artifacts are sealed atomically at
`_workspace/orchestration-results/<run-id>/attempt-<NN>/`, where attempts 1 and
2 are `attempt-01` and `attempt-02`. The run directory itself is never a new
review output directory. An existing attempt is never overwritten.

The worker attempt and review attempt are separate identities. A review-only
re-execution records `review_attempt`, `worker_attempt`,
`review_only_reexecution=true`, and `reran_worker=false`; it reuses and verifies
the sealed worker result without running the worker. The reviewer report and
status bind the run, both attempts, package manifest SHA-256, verified preflight
evidence seal SHA-256, worker-result SHA-256, and hard-stop verdict. The status
uses `orchestration.lv_reviewer.status.v1`. Both artifacts are checked against
exact field sets before sealing.

The empty self-reference placeholder inside `preflight.evidence.json` is not
the seal. The reviewer recomputes and verifies the evidence bytes against the
sidecar and preflight status, then records that non-empty computed seal in both
review artifacts.

Legacy files written directly under a run directory are preserved byte-for-byte
and are not renamed or retroactively treated as `attempt-01`. A later recovery
attempt is allowed only when the runtime has a fixed trusted contract for all
five legacy relative paths and hashes. Its `prior_review_lineage` records the
legacy location kind, contract-failure status, five paths and hashes, prior
report hash, and the identical package, preflight, and worker-result hashes.
Missing or drifted legacy evidence blocks the review before a new attempt is
created. The CLI has no arbitrary legacy-path or hash override.

The bounded `attempt-03` recovery additionally requires the failed
`attempt-02` directory as its immediate prior review. All five attempt-02
artifacts must match the runtime's fixed hashes; the report sidecar, status
report hash, run and attempt identities, FAIL/hard-stop result, package,
preflight and worker seals, and `secret_like_value` violation must agree.
`prior_review_lineage` retains the legacy run-root lineage and adds this
immediate attempt-02 relationship. Missing or drifted evidence blocks creation
of attempt-03. Attempts above 3 are not supported by this recovery contract,
and every failed artifact set remains immutable.

The reviewer records bounded, redacted `independent_checks` for the focused and
full tests, configuration import, `git diff --check`, UTF-8/BOM/NUL/trailing
whitespace, conflict markers, secret-like values, owned-file and staged-change
boundaries, Git fingerprints, and immutable package/preflight/worker inputs.
Secret checks are limited to owned files; environment-variable names and empty
placeholders are allowed. Python owned files are parsed with the Python AST so
annotations, docstrings, comments, identifier references, calls and environment
lookups are distinguished from static literals. Narrow, visibly non-credential
test sentinels (`fixture-...-not-a-secret` or `fixture-...-marker`) are allowed;
this exception never applies outside `tests/` or to a credential URL. Non-empty
literals assigned to secret/key/token/password names, statically composed
credential literals, and credential-bearing URL literals fail closed; Python
parse failure also fails closed. Credential-bearing URLs remain forbidden in
tests, so URL fixtures use userinfo-free RFC-reserved domains. Findings record
only a relative path, line, check identifier, candidate kind and redacted
fingerprint—never the literal, source line or complete URL. Non-Python files
retain the existing conservative pattern checks. Interpreter evidence is
recorded before and after tests and must match, including executable, owner,
namespace, mount, venv prefix, base-prefix, version, and venv verification.

## Post-review owned-file remediation

A validation defect discovered after a sealed PASS review uses a separate remediation lineage; it never overwrites or re-labels an `attempt-<NN>` directory. Create the package before changing owned bytes, then preflight, run the manual worker, and review independently:

```text
python3 -m runtime.orchestrator.cli lv-remediation-package --parent-run-id <parent-run> --run-id <remediation-run> --reason-code <UPPER_SNAKE_CODE> --reason <bounded-redacted-reason>
python3 -m runtime.orchestrator.cli lv-remediation-preflight --run-id <remediation-run>
# authorized manual worker writes /tmp/harness-lv-remediation-worker-result-<remediation-run>.json
python3 -m runtime.orchestrator.cli lv-remediation-review --run-id <remediation-run>
```

Artifacts are atomically sealed under `_workspace/orchestration-remediations/<remediation-run>/` in `package`, `preflight`, and `review` directories. Preflight also seals `worker.input.json` and its sidecar with the exact result field set, package and preflight hashes, before snapshot, runtime approval object, output path, and prohibitions. The package requires the latest parent review to be PASS with `hard_stop=true`, binds all parent artifact hashes plus canonical plan, approval, Gate/LV, branch/HEAD/tree/index, exact owned files, and before SHA-256/size. Preflight rejects staged or non-owned drift and stale worker paths. The worker result uses `orchestration.lv_remediation.worker.result.v1`, a distinct path and exact field set, and binds before/after owned content plus package and preflight seals. Review rechecks parent/package/preflight/worker immutability, exact ownership, focused and full tests, text/secret checks, and final snapshot stability. The copied worker result must be byte-identical to the original.

The remediation review always records `hard_stop=true`, `transition_authorized=false`, and `checkpoint_authorized=false`. PASS is evidence only; it is not Gate completion, checkpoint authorization, business approval, or authority to start another LV. Existing attempt-03 legacy recovery remains unchanged and is not a remediation mechanism.

`lv-remediation-review` uses the same exit convention: `0` PASS, `9` FAIL, `10` BLOCKED. Contract-construction errors use bounded JSON and exit `11`.

## Global Gate orchestration

The canonical R01-R25 requirements are recorded without abbreviation in `docs/harness/orchestration-runtime-work-items.md`. The sealed global Gate orchestration requirements SHA-256 is `f734be6f2a81c89428f28605a1ffcd12234a511e69ded4c607041a2e0b367361`; runtime state, action manifests, checkpoints, ledgers, and handoffs must bind this value and fail closed on drift.

`gate-dry-run` is the project-Codex entrypoint for loading a declarative Gate without mutation. `project-onboard --dry-run` reports missing lifecycle contracts and namespace readiness after `dev new` or `dev add`; the non-Git `dev` launcher is not modified by this repository. Project Codex invokes the Harness CLI internally, so users do not need a separate Harness Codex session. Harness engine maintenance remains the only reason to work directly in the Harness project.

The Gate controller binds one authorization to the project, Gate, canonical plan SHA, complete LV order, per-LV owned files and completion criteria, lifecycle permissions, and stop conditions. LV changes use auditable `SYSTEM_TRANSITION` state with `user_approval_renewal=false`; an approval object is never rewritten as the active LV. The lifecycle is `PLAN → PACKAGE → PREFLIGHT → WORKER → REVIEW → CHECKPOINT → EXIT → HANDOFF`, with FAIL routed to same-LV remediation and BLOCKED routed to user handoff.

`GATE_BY_GATE` is the default and stops after Gate Exit. `FULL_PLAN` is rejected unless final project validation and explicit opt-in are both true; no opt-in is activated by implementation or dry-run. `RESUME` verifies a sealed checkpoint SHA plus project, Gate, and run namespace before returning state, so completed LVs are not repeated and artifacts are not overwritten.

The completeness ledger maps every loaded LV plan item to Gate, LV, selected existing asset, owned files, tests, evidence SHA, and status. Missing, duplicate, reordered, unbound, or unevidenced completed items block Exit. Structured handoff uses an exact field set and canonical SHA, includes recovery checkpoint and next-stage boundaries, and revalidates changed files against the LV authorization.

All approval, state, artifact, run, and secret paths live below distinct per-project namespaces. Project IDs and relative paths are validated, cross-project checkpoint/handoff reuse is rejected, and concurrent ownership of one file by different active LVs is blocked. Asset selection is global existing asset, then project existing asset, then composition; capability gaps are reported without authorizing global Skill/Agent creation.

CLI examples:

```text
python3 -m runtime.orchestrator.cli gate-dry-run --project-root <project-root> --gate-id GATE-1 --mode GATE_BY_GATE
python3 -m runtime.orchestrator.cli gate-validate --project-root <project-root> --gate-id GATE-1 --requirements-sha256 <sha256> --approval-evidence <approval.json> --requirement-evidence <requirements.json> --branch <branch> --head <head> --harness-root <harness-root>
python3 -m runtime.orchestrator.cli gate-run --project-root <project-root> --gate-id GATE-1 --run-id <run-id> --requirements-sha256 <sha256> --approval-evidence <approval.json> --requirement-evidence <requirements.json> --branch <branch> --head <head> --harness-root <harness-root>
python3 -m runtime.orchestrator.cli project-onboard --project-root <project-root> --alias <alias> --dry-run
```

`gate-dry-run`, `gate-validate`, and `project-onboard --dry-run` are read-only. `gate-run` is the sole mutating Gate lifecycle surface: it validates every sealed binding before mutation, consumes only immutable lifecycle artifacts, records append-only checkpoints, and returns success only for `SYSTEM_TRANSITION` or Gate Exit. A missing sealed worker result returns the bounded `WORKER_RESULT_REQUIRED` hard stop instead of treating `WORKER_HANDOFF` as success.

`lv-review` exit codes are `0` for PASS, `9` for FAIL, and `10` for BLOCKED.
Argument parsing and existing exception codes retain their prior meanings.
A PASS remains a hard-stop review result only: it is not Gate completion,
business approval, runtime/sandbox authorization, commit authorization, or
permission to start another LV.

# CLI-Anything EDP Qualification

Validated source HEAD: `7946c4b32f2d027e5e6b48c1770f09097432fff8`
Decision: **PASS**
Upstream sealed commit: `810c18b0d1ab9b234bc996c9fd999318523a3ef0`

## R7 Scope-Gap Closure
- CLI-Hub discovery: **QUALIFIED_READ_ONLY** (`list/search/info/can/matrix list/search/preflight` only).
- CLI-Hub mutation/launch: **STRUCTURALLY BLOCKED**.
- CLI-Hub analytics: **DISABLED** in isolated execution.
- Skill generator: **CANDIDATE_ONLY**; generated skills remain unqualified.
- Missing CLI-Hub/generator: **safe UNAVAILABLE degradation / control_authority=NONE**.
- Operational smoke: CLI-Hub 0.4.1 PASS; GIMP representative skill generation PASS as CANDIDATE.

## Coverage
- `TI-01` — **PASS** — CLI_ANYTHING_SOURCE_QUALIFICATION.json, test_candidate_round_trip_is_digest_bound_and_frozen, test_source_and_artifact_hashes_are_mandatory, CLI_HUB_DISCOVERY_GENERATOR_QUALIFICATION.json
- `TI-02` — **PASS** — test_generic_shell_or_command_surfaces_are_rejected, test_command_identity_rejects_traversal_and_relative_path, test_argv_is_explicit_and_allowlisted, test_cli_execution_never_uses_shell_true, test_side_effecting_and_shell_like_surfaces_are_blocked, test_read_only_discovery_allowlist_and_control_authority_none
- `TI-03` — **PASS** — test_read_only_cli_runs_only_through_broker_and_journal, test_state_change_fixture_is_authorized_then_artifact_verified, test_authorization_failure_never_launches_cli
- `TI-04` — **PASS** — test_dry_run_never_launches_artifact, test_preflight_detects_unavailable_and_artifact_mismatch, test_preflight_strips_secret_environment_and_isolates_home, test_unavailable_or_digest_mismatch_degrades_without_execution, test_generator_unavailable_degrades_and_does_not_create_output
- `TI-05` — **PASS** — test_artifact_verification_failure_records_failed_receipt, test_bad_verifier_path_and_unqualified_manifest_fail_closed, test_output_is_bounded
- `TI-06` — **PASS** — test_generated_skill_cannot_self_qualify, test_generated_skill_requires_independent_evidence, test_generator_writes_candidate_only_inside_isolated_workspace, CLI_HUB_DISCOVERY_GENERATOR_QUALIFICATION.json:generated_skill_qualified=false
- `TI-07` — **PASS** — test_relative_path_is_normalized_and_traversal_blocked, test_preflight_strips_secret_environment_and_isolates_home, test_cli_execution_never_uses_shell_true, test_discovery_environment_is_isolated_and_analytics_disabled, test_generator_rejects_output_escape_and_digest_mismatch
- `TI-08` — **PASS** — test_cli_unavailable_does_not_mutate_full_plan_control_state, test_tool_implementation_plane_has_no_control_authority_imports, test_production_code_does_not_directly_invoke_qualified_launcher, CLI_HUB_DISCOVERY_GENERATOR_QUALIFICATION.json:unavailable_degradation

## Invariants
- `TI-INV-01` — **PASS** — test_read_only_cli_runs_only_through_broker_and_journal, test_state_change_fixture_is_authorized_then_artifact_verified
- `TI-INV-02` — **PASS** — test_generated_skill_cannot_self_qualify, test_generated_skill_requires_independent_evidence
- `TI-INV-03` — **PASS** — CLI_HUB_DISCOVERY_GENERATOR_QUALIFICATION.json:control_authority=NONE, test_read_only_discovery_allowlist_and_control_authority_none
- `TI-INV-04` — **PASS** — test_generic_shell_or_command_surfaces_are_rejected, test_cli_execution_never_uses_shell_true
- `TI-INV-05` — **PASS** — test_candidate_round_trip_is_digest_bound_and_frozen, test_bad_digest_fails_closed
- `TI-INV-06` — **PASS** — test_authorization_failure_never_launches_cli, test_bad_verifier_path_and_unqualified_manifest_fail_closed
- `TI-INV-07` — **PASS** — test_cli_unavailable_does_not_mutate_full_plan_control_state, test_unavailable_or_digest_mismatch_degrades_without_execution, test_generator_unavailable_degrades_and_does_not_create_output

## Negative Space
All material forbidden authority/effect bypass counts are `0`.

Qualification SHA-256: `959c5139f32cf124e31ee6f750b41f21b25d61524abe1505936d61d91c274f2c`

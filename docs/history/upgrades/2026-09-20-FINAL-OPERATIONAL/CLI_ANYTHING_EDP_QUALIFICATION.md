# CLI-Anything EDP Qualification

Decision: **PASS**
Upstream HEAD: `810c18b0d1ab9b234bc996c9fd999318523a3ef0`

## Coverage

- `TI-01` — PASS — CLI_ANYTHING_SOURCE_QUALIFICATION.json, test_candidate_round_trip_is_digest_bound_and_frozen, test_source_and_artifact_hashes_are_mandatory
- `TI-02` — PASS — test_generic_shell_or_command_surfaces_are_rejected, test_command_identity_rejects_traversal_and_relative_path, test_argv_is_explicit_and_allowlisted, test_cli_execution_never_uses_shell_true
- `TI-03` — PASS — test_read_only_cli_runs_only_through_broker_and_journal, test_state_change_fixture_is_authorized_then_artifact_verified, test_authorization_failure_never_launches_cli
- `TI-04` — PASS — test_dry_run_never_launches_artifact, test_preflight_detects_unavailable_and_artifact_mismatch, test_preflight_strips_secret_environment_and_isolates_home
- `TI-05` — PASS — test_artifact_verification_failure_records_failed_receipt, test_bad_verifier_path_and_unqualified_manifest_fail_closed, test_output_is_bounded
- `TI-06` — PASS — test_generated_skill_cannot_self_qualify, test_generated_skill_requires_independent_evidence
- `TI-07` — PASS — test_relative_path_is_normalized_and_traversal_blocked, test_preflight_strips_secret_environment_and_isolates_home, test_cli_execution_never_uses_shell_true
- `TI-08` — PASS — test_cli_unavailable_does_not_mutate_full_plan_control_state, test_tool_implementation_plane_has_no_control_authority_imports, test_production_code_does_not_directly_invoke_qualified_launcher

## Invariants

- `TI-INV-01` — PASS — test_read_only_cli_runs_only_through_broker_and_journal, test_state_change_fixture_is_authorized_then_artifact_verified
- `TI-INV-02` — PASS — test_generated_skill_cannot_self_qualify, test_generated_skill_requires_independent_evidence
- `TI-INV-03` — PASS — CLI_ANYTHING_SOURCE_QUALIFICATION.json:control_authority=NONE
- `TI-INV-04` — PASS — test_generic_shell_or_command_surfaces_are_rejected, test_cli_execution_never_uses_shell_true
- `TI-INV-05` — PASS — test_candidate_round_trip_is_digest_bound_and_frozen, test_bad_digest_fails_closed
- `TI-INV-06` — PASS — test_authorization_failure_never_launches_cli, test_bad_verifier_path_and_unqualified_manifest_fail_closed
- `TI-INV-07` — PASS — test_cli_unavailable_does_not_mutate_full_plan_control_state

## Negative Space

All material forbidden authority/effect bypass counts are `0`. CLI-Anything remains a bounded tool-implementation mechanism behind the existing authorization/broker/effect-journal path.

Qualification SHA-256: `bf93a1f7a38539df5a3c6f33e83f43e82a0b93c2bd358f65603ab18db680a84b`

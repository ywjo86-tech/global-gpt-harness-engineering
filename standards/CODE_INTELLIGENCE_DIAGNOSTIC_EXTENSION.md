# Code Intelligence Diagnostic Extension - EDP-1.0

This extension inherits EXHAUSTIVE_DIAGNOSIS_PROTOCOL EDP-1.0 in full and cannot weaken its Universal PASS Gate. It applies only when Diagnostic Intelligence evidence is used. Every applicable domain requires evidence and negative-space review; DOMAIN_EVIDENCE_COVERAGE=100% is mandatory for final PASS.

CI-01 Source Snapshot Binding: exact current HEAD/tree/scope binding; mismatch BLOCKED; audit dirty/untracked/generated paths.
CI-02 Graphify topology coverage: pinned read-only graph evidence; unavailable uses fallback/N/A; audit dynamic/config edges.
CI-03 CodeGraph dependency/impact: pinned graph-only evidence; unavailable uses fallback/N/A; audit runtime/generated/external calls.
CI-04 Graph conflict/raw-source verification: analyzer refs plus raw source; unresolved material conflict BLOCKED.
CI-05 related-test/verifier mapping: material impacts mapped to tests/verifiers; missing material verifier BLOCKED.
CI-06 freshness: before/after binding CURRENT at consumption; STALE cannot be advisory evidence.
CI-07 security/secret check: snapshot exclusion/output scan; secret exposure BLOCKED.
CI-08 fallback/disable equivalence: OFF/degraded canonical authority projection unchanged.
CI-09 post-change impact revalidation: changed source reindexed/revalidated when applicable.

Diagnostic evidence has control_authority=NONE, mutation_authority=NONE, recovery_authority=NONE, completion_authority=NONE, and notification_authority=NONE. Analyzer absence is graceful degradation of advisory evidence only; it is never fail-open authorization.

# OCPv2 Read-only Host Diagnostic Rollout

## Safety boundary

Merging or deploying this implementation leaves the feature **OFF**. No diagnostic request is executed until a separate operational review explicitly enables it. The feature adds observational capability only; it does not create a second execution owner, mutation path, provider selector, or Full Plan completion authority.

Do not delete `ocpv2-r2-e74c1ce`, the current stable runtime, or any rollback/runtime release needed by FA6 while this rollout is being qualified.

## 1. Successor-runtime qualification

Qualify the successor runtime while the stable runtime remains available. Re-run the focused OCP/diagnostic regression, complete repository regression, FA6 authority invariants, and verify that V2 mutation behavior is unchanged. Confirm `GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=false` before deployment.

## 2. Create the local policy

Copy `deploy/operator-control-plane-v2/read-only-host-diagnostic.example.json` outside the repository. Replace only the placeholder roots and service allowlist entries that have been reviewed. The config path must be absolute, the file must be a regular non-symlink file owned by the runtime user, and it must not be group/world writable.

```bash
chmod 0600 /absolute/path/to/read-only-host-diagnostic.json
```

Do not place tokens, passwords, private keys, `.env` contents, or other secret material in the policy.

## 3. Separate feature activation

After qualification, set the reviewed environment values separately from install/bootstrap:

```text
GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=true
GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG=/absolute/path/to/read-only-host-diagnostic.json
```

Activation is permitted only in a reviewed OCP control mode. The approved design allows diagnostic execution in `CONTROL_READ_ONLY` and `ACTIVE`; `OBSERVE_ONLY`, `DISABLED`, and mutation-canary diagnostic execution remain non-executing/fail-closed.

## 4. Smoke request: repository snapshot

Send one typed V3 `repo.snapshot` request against an allowlisted project root. Confirm the result is `OK` or explicitly `STALE`, contains only bounded diagnostic summary data, and is persisted/published through the diagnostic outbox without creating canonical Full Plan completion evidence.

## 5. Smoke request: bounded file range

Send one typed V3 `project.file_range` request for a known non-sensitive UTF-8 file. Confirm the output obeys line/byte limits, secret-like values are redacted, sensitive paths/symlinks/special files remain blocked, and `PARTIAL` is preserved when truncation occurs.

## 6. FA6 invariant recheck

Re-run authority-negative-space checks after both smoke requests. Verify no new execution owner, provider/model binding, mutation bypass, direct service-layer shell/Git/systemd execution, canonical completion claim, or stable-runtime mutation was introduced. Verify ordinary V2 `READ_ONLY_ACCEPTED` and the registered Full Plan mutation path remain unchanged.

## 7. Immediate rollback

Rollback the feature before changing broader OCP state:

```text
GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=false
GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG=
```

Restart/reload only through the separately approved operational procedure. Preserve diagnostic outbox evidence for review; do not delete canonical Harness state or stable runtime releases. If any invariant fails, keep the feature OFF and continue operating from the previously qualified stable runtime.

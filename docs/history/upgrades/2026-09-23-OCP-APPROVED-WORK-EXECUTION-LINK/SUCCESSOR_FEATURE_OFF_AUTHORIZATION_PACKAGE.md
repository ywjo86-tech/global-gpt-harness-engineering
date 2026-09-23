# OCPv2 Successor Feature-OFF Authorization Package

Status: READY FOR EXPLICIT SUCCESSOR RUNTIME SWITCH APPROVAL — NOT YET DEPLOYED

## Bound successor identity

- Successor source HEAD: `304cb27c04a7780675f40f39655e6df42100001a`
- Immutable release path: `/home/ywjo/.local/share/global-gpt-harness/releases/304cb27c04a7780675f40f39655e6df42100001a`
- Runtime release manifest SHA-256: `cecaa7792945d8f11169970b014001f19ba1a2f3c7051d86f769f2ab68ceb9f3`
- Expected live `WorkingDirectory`: `/home/ywjo/.local/share/global-gpt-harness/releases/304cb27c04a7780675f40f39655e6df42100001a`
- Selected-head record: `/home/ywjo/.local/state/global-gpt-harness/awel-successor-review/selected-head.txt`

## Predecessor snapshot

- Current service file: `/home/ywjo/.config/systemd/user/ocpv2.service`
- Current service SHA-256: `65cc82a76640730d2ef4f55229d97cfd11346b68e3d5f2b24ce8430a3b6b3b19`
- Current env file: `/home/ywjo/.config/gch/ocpv2.env`
- Current env SHA-256: `5133bbeb2eec2ff4ae8e0cc912f7a52423230982d735729b45505b77c19c31e1`
- `OCP_HOST_INSPECTION_ENABLED`: `1`
- `OCP_WORK_ACTIVATION_ENABLED`: `0`
- `OCP_WORK_ACTIVATION_POLICY_REF`: `RDC-INDEPENDENT-LIVE-20260923`

No credential path or credential value is copied into this package.

## Reviewed successor files

- Reviewed service file: `/home/ywjo/.local/state/global-gpt-harness/awel-successor-review/304cb27c04a7780675f40f39655e6df42100001a/ocpv2.service`
- Reviewed service SHA-256: `c65889dc56caafe55d3ef7b7b4ae25440dedebc489bd36dff045550955750404`
- Reviewed env file: local review evidence only; not committed
- Reviewed env SHA-256: `6541db30a9a8706fb84f67078854dc494b71b6ae0a7eb12f433fe5abd887fa73`
- `OCP_FULL_PLAN_ACTIVATION_ENABLED`: `0`
- `OCP_FULL_PLAN_ACTIVATION_POLICY_REF`: absent
- Host Inspection setting: preserve predecessor value `1`
- V1 activation setting: preserve predecessor value `0`
- V1 activation policy: preserve predecessor value `RDC-INDEPENDENT-LIVE-20260923`

## Rollback binding

Before any install, the exact predecessor service/env files must be copied to:

- `/home/ywjo/.local/state/global-gpt-harness/awel-deploy-backup/304cb27c04a7780675f40f39655e6df42100001a/ocpv2.service`
- `/home/ywjo/.local/state/global-gpt-harness/awel-deploy-backup/304cb27c04a7780675f40f39655e6df42100001a/ocpv2.env`

Their required source digests are the predecessor SHA-256 values recorded above. On successor qualification failure, restore only those exact backups, reload the user unit, start the one-shot OCP service, and verify the existing timer remains active.

## Approval boundary

This package authorizes nothing by itself. It does **not** authorize installation of the reviewed unit/env, `systemctl --user daemon-reload`, service start/restart, a live control request, or enabling executable activation. The next step requires explicit approval for the exact successor runtime switch bound above. Executable Full Plan activation remains OFF.

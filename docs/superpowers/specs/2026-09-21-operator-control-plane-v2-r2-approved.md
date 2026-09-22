# OPERATOR_CONTROL_PLANE_V2 R2 — Approved Canonical Authority

Status: APPROVED / EDP ALL PASS
Date: 2026-09-21
Authority SHA-256: 9e4991292ba087b8e0eb53188153556c998a5f06806a8989b38c74c88b573ced
Source baseline: main@e2ce97a3741c070e538f817113a1b90845cc53c3

This repository file is the implementation binding record for the user-approved R2 design.
The complete byte-identical approved artifact is retained by the GPT Operator as
OPERATOR_CONTROL_PLANE_V2_R2_EDP_ALL_PASS.md with the SHA-256 above.

Normative invariants for implementation:
- GPT remains Logical Operator / decision authority.
- Harness remains the persistent execution supervisor.
- Transport is non-authoritative and must not become a second orchestrator.
- Provider Router remains the sole provider/model selector.
- State-changing actions continue through the existing Production Execution Gateway / Full MCP boundary.
- Existing Full Plan continuation ownership, epoch fencing and transaction locking remain authoritative.
- Migration-v2 state is advanced only by its canonical store and legal transition rules.
- Existing qualification and successor registration are never recreated during resume.
- RDC is not a runtime dependency of OCPv2.
- Live bootstrap and production activation remain separately authorized gates.

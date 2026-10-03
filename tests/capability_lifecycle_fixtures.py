from runtime.orchestrator.capability_lifecycle import (
    CapabilityContractRefV1,
    CapabilityLifecycleRecordV1,
)


def active_record() -> CapabilityLifecycleRecordV1:
    return CapabilityLifecycleRecordV1.create(
        contract=CapabilityContractRefV1(
            contract_id="cap:ui-design:1",
            contract_version="1.0.0",
            binding_kind="MCP_ENDPOINT",
            endpoint_ref="mcp:ui-design-agent",
            stable_asset_identifier="",
            endpoint_version="rev-001",
            activation_epoch=1,
        ),
        state="ACTIVE",
        health="HEALTHY",
        active_dependency_ids=(),
        evidence_refs=("evidence:use-auth",),
    )

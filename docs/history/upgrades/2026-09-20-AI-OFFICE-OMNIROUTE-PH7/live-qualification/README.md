# PH7 Live Third-Provider Qualification

Status: `GROQ_ACTIVE_QUALIFIED`.

Provider: `groq`. Explicit model: `openai/gpt-oss-120b`. Connection identity is stored in the canonical candidate inventory; credential values remain outside Git. The authorization envelope is `FREE_TIER_ONLY`; paid usage or tier upgrades are not authorized by this record.

Qualification evidence proves: provider connection HTTP 200; explicit-target READ PASS with identical returned provider/model and no fallback; ACTION proposal generation PASS with schema/identity/write binding validation and `CONFIRMED_NO_EFFECT=true`; classified failure reroute PASS with MPRF exclusion and Harness Router-owned reselection; and three-provider neutral-routing qualification PASS.

The pinned OmniRoute 3.8.50 OpenAPI specifies `X-OmniRoute-Fallback-Attempts` is present only when greater than zero. Therefore its absence on the successful explicit-target completion is evidence of zero OmniRoute fallback attempts for this pinned version. Provider/model identity headers must still match exactly.

Canonical runtime activation is projected from `docs/harness/provider-candidate-inventory.json`. Discovery alone cannot create ACTIVE state. The production worker runner registry loads only ACTIVE records and binds the exact provider/model/connection tuple.

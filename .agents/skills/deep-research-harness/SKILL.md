---
name: deep-research-harness
description: Run a bounded, evidence-first research sidecar that gathers and cross-checks multi-source evidence for a defined decision without expanding scope or modifying an approved plan.
status: PROVISIONAL
---

# Deep Research Harness

Use this skill as a conditional research sidecar when a project, design decision, requirement, diagnosis, or business question cannot be handled responsibly without additional external or multi-source evidence.

Do not make this a mandatory lifecycle gate for every project. Trigger it only when the decision benefit justifies the research work.

## Purpose

Answer a bounded research question with traceable evidence, explicit source quality, conflict handling, uncertainty, and a clear stop condition while preventing open-ended research and plan drift.

## Trigger

Use when one or more of the following are true:

- A material decision depends on current external facts, standards, market data, technical evidence, or source comparison.
- Available project context contains conflicting or insufficient evidence.
- A design/requirements question needs independent evidence before the next approved lifecycle step.
- The supervisor explicitly requests a bounded evidence package.

Do not trigger when:

- The answer is already supported by authoritative project artifacts.
- The task is ordinary implementation, code review, documentation authoring, or release review.
- Research would only add interesting background without affecting the decision.
- The requested research scope cannot be bounded to a decision or defined question.

## Research Contract

Before research begins, establish this contract using the strongest available fields:

```yaml
research_contract:
  question: precise question to answer
  objective: why the research is needed
  decision_to_support: downstream decision or artifact that will consume the result
  scope_in:
    - included subjects
  scope_out:
    - excluded subjects
  geography: optional
  time_window: optional
  required_freshness: optional
  source_priority:
    - preferred source classes
  prohibited_sources:
    - optional exclusions
  evidence_threshold: minimum support expected for material claims
  stop_condition:
    - completion criteria
  provenance:
    plan_revision: optional
    plan_sha: optional
    run_id: optional
```

If the research question expands materially during execution, report `SCOPE_EXPANSION_REQUIRED` instead of silently broadening the contract.

## Source Quality Model

Classify evidence by source quality where applicable:

- `TIER_1`: primary/authoritative sources such as laws, regulators, official statistics, standards bodies, original technical documentation, company filings, or first-party source data.
- `TIER_2`: high-quality independent reporting, recognized research institutions, specialist data providers, or peer-reviewed synthesis with clear methodology.
- `TIER_3`: reputable industry publications, professional analysis, or secondary technical material with useful but less authoritative evidence.
- `TIER_4`: community discussions, practitioner anecdotes, blogs, forums, or social signals.

Source tier is not the same as truth. A higher tier can still be outdated, methodologically mismatched, or irrelevant to the exact claim. Record freshness and methodological fit separately when material.

Community/practitioner material must remain clearly labeled as signal or experience, not verified fact, unless independently corroborated.

## Agent Team Pattern

Create only the research lanes needed by the contract.

- Research lead: freezes the research contract, source strategy, scope, and stop condition.
- Primary-source researcher: gathers authoritative first-party, regulatory, standards, statistical, or official technical evidence.
- Independent-source researcher: gathers high-quality external reporting, research, or specialist analysis.
- Academic/standards researcher: checks formal literature when it materially improves the answer.
- Community signal analyst: gathers practitioner/community evidence only when decision-relevant and labels it separately.
- Verification reviewer: checks claim support, source independence, freshness, conflicts, and methodology.
- Synthesis writer: produces the final bounded research package from verified evidence.

## Authority Boundary

This skill MAY:

- Search, gather, compare, and synthesize evidence inside the approved Research Contract.
- Rank source quality and identify evidence gaps.
- Report that research evidence conflicts with a requirement, design assumption, or approved plan.
- Recommend that an amendment or decision review be considered.
- Return `UNRESOLVED` when evidence is insufficient or materially conflicting.

This skill MUST NOT:

- Expand the approved research scope without escalation.
- Modify requirements, architecture, implementation, sealed plans, plan SHA/revision, or orchestration state.
- Treat research findings as automatically approved plan changes.
- Hide unresolved source conflicts by selecting a preferred answer without sufficient basis.
- Present community sentiment as factual proof.
- Continue searching indefinitely after a defined stop condition is met.
- Issue lifecycle `GO`, `CONDITIONAL GO`, or `NO-GO` decisions unless a separate authorized gate explicitly consumes the research package.

When evidence materially undermines the approved plan, return `CHANGE_REQUIRED_CANDIDATE` or the future orchestrator-equivalent signal to the supervisor. The actual plan amendment must follow the approved amendment process.

## Claim-Evidence Contract

Material conclusions should be traceable through a Claim-Evidence Matrix:

```yaml
claim:
  id: R-CLAIM-001
  statement: concise material claim
  evidence:
    - source_id: SRC-001
      source_tier: TIER_1 | TIER_2 | TIER_3 | TIER_4
      support: SUPPORTS | CONTRADICTS | CONTEXT_ONLY
      freshness: current/as-of date when relevant
      independence_group: optional identifier for sources derived from the same origin
  confidence: HIGH | MEDIUM | LOW
  status: SUPPORTED | PARTIALLY_SUPPORTED | CONFLICTED | UNRESOLVED
```

Do not count multiple articles derived from the same original report/data release as fully independent corroboration.

## Conflict Handling

When sources materially disagree, create a conflict record rather than forcing consensus:

```yaml
conflict:
  id: R-CONFLICT-001
  claim_a: first materially different claim
  claim_b: second materially different claim
  source_quality_difference: relevant tier/authority differences
  freshness_difference: relevant timing differences
  methodology_difference: definitions, sample, calculation, or scope differences
  resolution: RESOLVED | PARTIALLY_RESOLVED | UNRESOLVED
  rationale: concise evidence-based explanation
  confidence: HIGH | MEDIUM | LOW
```

Prefer explaining why sources disagree over merely averaging or voting between them.

## Workflow

1. Define and freeze the Research Contract, including `decision_to_support`, scope boundaries, evidence threshold, and stop condition.
2. Build a source plan that prioritizes primary/authoritative evidence where available.
3. Gather independent source lanes in parallel only when their outputs can be compared without shared-edit conflicts.
4. Record sources with tier, date/freshness, methodology notes, and origin/independence when material.
5. Build the Claim-Evidence Matrix for decision-relevant claims.
6. Cross-check important claims across genuinely independent evidence where practical.
7. Create conflict records for material disagreements and resolve only when evidence justifies resolution.
8. Separate verified findings, contextual signals, uncertainty, and recommendations.
9. Check the stop condition. Stop when the contract is satisfied or when additional research is unlikely to change the decision-relevant conclusion.
10. Produce the Research Package and report any `SCOPE_EXPANSION_REQUIRED`, `CHANGE_REQUIRED_CANDIDATE`, or `UNRESOLVED` items to the supervisor.

## Stop Conditions

At least one explicit completion rule must be set before execution. Suitable rules include:

- Each material claim meets the agreed evidence threshold.
- Key claims have authoritative evidence plus at least one genuinely independent corroborating source where practical.
- Additional searches are no longer producing new decision-relevant evidence.
- The remaining evidence gap is clearly documented and cannot be resolved within the approved scope.
- The decision can be supported at the agreed confidence level.

Reaching a stop condition does not mean every uncertainty is eliminated. Unresolved uncertainty must remain visible.

## Outputs

- Research Contract
- Source map with quality/freshness notes
- Claim-Evidence Matrix
- Conflict register
- Evidence summary
- Decision-relevant synthesis
- Confidence and uncertainty statement
- Open evidence gaps
- `SCOPE_EXPANSION_REQUIRED`, `CHANGE_REQUIRED_CANDIDATE`, or `UNRESOLVED` signals when applicable

## Validation

Before handoff, confirm:

- Research stayed inside the approved contract.
- Important claims have traceable source support.
- Apparent corroboration is not merely duplicate reporting from one origin.
- Community/practitioner evidence is labeled separately.
- Material conflicts are explicit and evidence-based.
- Uncertainty and confidence are visible.
- Stop conditions were applied.
- No requirement, plan, architecture, or gate state was changed by the research team.

## Escalation

Escalate to the supervisor when:

- The original research scope is insufficient to answer the decision question.
- Evidence indicates the approved plan may require amendment.
- Authoritative sources conflict materially and remain unresolved.
- A critical source is unavailable or requires access beyond the assigned authority.
- Continuing research would require sensitive data, credentials, paid access, or a materially different method.

## Completion Contract

The skill is complete only when:

- The Research Contract and stop condition are explicit.
- Material claims are represented in the Claim-Evidence Matrix.
- Source quality, freshness, and independence are considered where relevant.
- Conflicts and unresolved gaps are visible.
- The final synthesis answers the original bounded question and identifies the supported decision implication.
- Research has not changed the plan or expanded its own scope.

## Provisional Revalidation

Before promoting this skill to stable/V1.0, re-check it against the completed Full Plan Orchestration implementation for:

- Actual amendment/change-request signal names
- Actual provenance, plan revision/SHA, and run identifiers
- Whether evidence artifacts have a central schema
- How conditional sidecars are invoked and resumed
- Whether the orchestrator centrally enforces scope expansion and stop conditions

If the final orchestration runtime provides these controls centrally, reference them instead of duplicating their implementation inside this skill.

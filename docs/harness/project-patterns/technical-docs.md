# Technical Docs Harness Pattern

## Purpose

Use this pattern to produce accurate technical documentation through endpoint analysis, explanation writing, example generation, and completeness review.

## When to Use

- API, SDK, service, or workflow documentation is needed.
- Existing docs are incomplete or stale.
- Developers need examples and error handling details.
- Documentation must be verified against source behavior.

## Agent Team Composition

- Docs lead: owns audience, structure, and final coherence.
- Endpoint analyst: extracts parameters, responses, errors, and constraints.
- Explanation writer: writes concepts, workflows, and procedures.
- Example builder: creates realistic usage examples.
- Completeness reviewer: checks accuracy, coverage, and usability.

## Workflow

1. Define audience, scope, and documentation goal.
2. Analyze endpoints, commands, schemas, or public interfaces.
3. Draft conceptual and procedural explanations.
4. Create usage examples, including normal and error cases.
5. Verify examples against code, specs, or runnable behavior.
6. Review completeness, consistency, and missing prerequisites.
7. Produce final docs with known gaps.

## Inputs

- API spec, code, or endpoint list
- Target audience
- Existing documentation
- Example requirements
- Verification method

## Outputs

- Documentation outline
- Endpoint or interface inventory
- Draft docs
- Usage examples
- Completeness review notes
- Follow-up gaps

## Validation Criteria

- Public interfaces are accurately described.
- Examples match real inputs and outputs.
- Error cases and prerequisites are documented.
- Docs are understandable for the target audience.

## Cautions

- Do not invent endpoint behavior.
- Keep examples realistic and minimal.
- Mark unverified behavior clearly.

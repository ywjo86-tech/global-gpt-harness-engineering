---
name: full-stack-website-development-harness
description: Use this skill when designing a reusable PMO harness for full-stack website projects that coordinate product scope, UX wireframes, UI review, React/Next.js frontend architecture, backend API architecture, integration, QA testing, deployment readiness, and release handoff from wireframe to deployment.
---

# Full-Stack Website Development Harness

Use this skill to plan and coordinate full-stack website development work as a reusable PMO pattern. This harness does not create a website by default. It defines the team structure, phase order, artifacts, risks, validation criteria, and handoff expectations needed before implementation begins.

## When to Use

Use this harness when a website project needs coordinated planning across:

- product goals, users, page scope, and feature priority
- UX flows, page maps, and wireframes
- UI design consistency, responsive behavior, accessibility, and brand tone
- React or Next.js frontend architecture
- backend API design, authentication, and data handling
- frontend/backend integration contracts
- unit, integration, E2E, and manual QA planning
- deployment readiness and release handoff

Do not use this harness for one-off code fixes, isolated component work, static content edits, or direct app scaffolding without prior planning approval.

## Required Inputs

Collect or infer the narrowest reasonable version of:

- business purpose and target users
- website type, primary user journeys, and success criteria
- page list, route map, and feature priority
- brand, content, accessibility, and responsive requirements
- preferred stack, hosting target, backend dependencies, and API constraints
- authentication, authorization, data sensitivity, and compliance constraints
- testing expectations, release timeline, and deployment owner

If key information is missing, list assumptions and open questions. Do not block low-risk planning work when reasonable assumptions are available.

## Agent Team

Use the smallest active subset needed for the request, while preserving these role contracts for complete website projects:

| Agent | Responsibility | Primary Outputs |
| --- | --- | --- |
| `website-product-orchestrator` | Coordinate goals, users, page scope, feature priority, schedule, and handoffs. | Scope summary, priority map, phase plan, risk register |
| `ux-wireframe-designer` | Design information architecture, screen flow, wireframes, and user journeys. | Page map, user flow, wireframe notes, UX assumptions |
| `ui-design-reviewer` | Review design consistency, layout, responsive behavior, accessibility, and brand tone. | UI specification review, accessibility notes, responsive checklist |
| `frontend-engineer` | Plan React/Next.js components, routing, state management, and UI implementation. | Frontend architecture, component map, route plan, state plan |
| `backend-api-engineer` | Plan API endpoints, request/response shapes, authentication, and data processing. | API contract, data model notes, auth plan, error model |
| `integration-engineer` | Plan frontend/backend connection, environment variables, API client, and error handling. | Integration contract, env map, client plan, failure handling plan |
| `qa-test-engineer` | Plan unit, integration, E2E, and manual QA coverage. | Test matrix, QA checklist, acceptance criteria |
| `deployment-release-reviewer` | Review build, environment, deployment checklist, rollback, and release handoff. | Deployment checklist, rollback notes, release handoff |

## Workflow

1. Project intake
   - Confirm purpose, users, website type, constraints, target stack, release owner, and success criteria.
   - Output: intake summary, assumptions, open questions, initial risk list.
2. Requirements and page map
   - Define pages, routes, user roles, feature priority, content needs, and acceptance criteria.
   - Output: requirements summary, page map, route inventory, priority list.
3. Wireframe and UX flow
   - Define navigation, screen flow, user journeys, form behavior, empty states, and error states.
   - Output: wireframe brief, UX flow, interaction notes.
4. UI design specification
   - Review layout, responsive rules, accessibility expectations, brand tone, visual hierarchy, and reusable UI patterns.
   - Output: UI specification, accessibility checklist, responsive checklist.
5. Frontend architecture
   - Plan React/Next.js routing, components, data fetching, state management, forms, loading states, and client boundaries.
   - Output: frontend architecture plan, component map, route plan, file list proposal.
6. Backend/API architecture
   - Plan endpoints, request/response schemas, auth rules, validation, persistence, errors, and observability.
   - Output: API contract, backend architecture plan, data handling notes.
7. Integration plan
   - Align frontend calls with API contracts, environment variables, API clients, error handling, retries, and mock strategy.
   - Output: integration plan, env variable map, cross-layer risk list.
8. QA test plan
   - Define unit, integration, E2E, accessibility, responsive, and manual QA checks.
   - Output: test matrix, QA checklist, acceptance criteria.
9. Deployment readiness review
   - Check build commands, env setup, hosting target, migrations, secrets handling, rollback, monitoring, and ownership.
   - Output: deployment checklist, rollback plan, release readiness notes.
10. Release handoff
   - Summarize deliverables, unresolved risks, validation evidence, deployment steps, and owner responsibilities.
   - Output: release handoff note, final checklist, follow-up recommendations.

## Operating Rules

- Before editing project files, present the plan, target files, risks, and test criteria.
- If the user says `승인`, `진행해`, `계속 진행`, or `OK 진행`, continue only within the previously proposed scope.
- Do not scaffold a real Next.js app, `package.json`, `src/`, deployment configuration, or API implementation unless the user separately approves implementation work.
- Do not create `.claude/` paths.
- Do not edit `AGENTS.md`, `_workspace/`, `.codex/agents/*.toml`, or existing skills unless explicitly approved under the repository safety protocol.
- Do not store secrets, tokens, passwords, customer data, raw emails, or private production data in harness artifacts.

## Expected Outputs

For a complete planning run, produce:

- project intake summary
- requirements and page map
- UX flow and wireframe brief
- UI design specification
- frontend React/Next.js architecture plan
- backend/API architecture plan
- integration plan
- QA test matrix and manual checklist
- deployment readiness checklist
- release handoff summary

For narrower requests, produce only the applicable subset and state which phases were intentionally skipped.

## Validation Checklist

Before declaring the harness output ready, verify:

- business purpose, target users, and success criteria are explicit
- page map and route plan match the requested website scope
- UX flow includes primary, empty, loading, and error states where relevant
- UI review covers responsive behavior and accessibility
- frontend architecture identifies React/Next.js routing, component boundaries, state, and data fetching
- API plan defines endpoints, schemas, authentication, authorization, validation, and error handling
- integration plan maps API calls, environment variables, and failure behavior
- QA plan includes unit, integration, E2E, accessibility, responsive, and manual checks
- deployment checklist covers build, environment, secrets handling, rollback, monitoring, and handoff ownership
- unresolved risks and assumptions are visible in the final handoff

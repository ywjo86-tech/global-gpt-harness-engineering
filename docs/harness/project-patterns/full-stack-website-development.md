# Full-Stack Website Development Harness

## Purpose

Define a reusable PMO harness pattern for full-stack website development projects. The harness coordinates product scope, UX wireframes, UI design review, React/Next.js frontend planning, backend API planning, integration, QA testing, deployment readiness, and release handoff from wireframe to deployment.

This pattern is for planning and coordination. It does not create a real website, scaffold a Next.js app, add `package.json`, create `src/`, or implement production code by default.

## When to use

Use this pattern when a website project needs coordinated work across design, frontend, backend, QA, and release preparation. It is appropriate for marketing sites with dynamic features, customer portals, dashboards, internal tools, ecommerce flows, authenticated sites, content-driven applications, and web apps that need both UI and API planning.

Use it when the PMO needs a repeatable project pipeline with clear phase gates, agent roles, input contracts, output artifacts, and validation criteria.

## When not to use

Do not use this pattern for:

- isolated bug fixes or small UI changes
- single-component frontend work
- content-only website edits
- backend-only API design with no website surface
- direct code scaffolding without prior planning approval
- projects where an existing domain-specific harness is more precise

## Agent team structure

| Agent | Role |
| --- | --- |
| `website-product-orchestrator` | Owns business goal alignment, target users, page scope, feature priority, schedule, phase gates, and final handoff coordination. |
| `ux-wireframe-designer` | Owns information architecture, screen flow, wireframes, navigation, user journeys, and interaction assumptions. |
| `ui-design-reviewer` | Reviews visual consistency, layout quality, responsive behavior, accessibility, brand tone, and reusable UI patterns. |
| `frontend-engineer` | Plans React/Next.js components, routing, rendering boundaries, state management, forms, data fetching, and UI implementation structure. |
| `backend-api-engineer` | Plans API endpoints, request/response structures, authentication, authorization, validation, persistence, and data processing. |
| `integration-engineer` | Aligns frontend and backend contracts, environment variables, API clients, error handling, retries, mocks, and cross-layer risks. |
| `qa-test-engineer` | Designs unit, integration, E2E, accessibility, responsive, regression, and manual QA coverage. |
| `deployment-release-reviewer` | Reviews build readiness, environment setup, deployment checklist, rollback plan, monitoring, and release ownership. |

The default coordination model is a sequential pipeline. Parallel review is allowed only when the artifacts are independent, such as UI review and API review after the page map is stable.

## End-to-end workflow

1. Project intake
   - Confirm purpose, users, stakeholders, website type, success criteria, constraints, stack assumptions, release timeline, and deployment owner.
   - Output: intake summary, assumptions, open questions, initial risk list.
2. Requirements and page map
   - Define page inventory, route map, user roles, content needs, feature priority, and acceptance criteria.
   - Output: requirements summary, page map, route inventory, priority map.
3. Wireframe and UX flow
   - Define navigation, screen flow, user journeys, forms, empty states, loading states, errors, and key interactions.
   - Output: wireframe brief, UX flow, interaction notes.
4. UI design specification
   - Review layout, visual hierarchy, responsive behavior, accessibility, brand tone, design system assumptions, and reusable patterns.
   - Output: UI specification, responsive checklist, accessibility notes.
5. Frontend architecture
   - Plan React/Next.js routes, components, rendering strategy, state, forms, data fetching, loading behavior, and error boundaries.
   - Output: frontend architecture plan, component map, route plan, proposed file list.
6. Backend/API architecture
   - Plan endpoints, schemas, authentication, authorization, validation, persistence, error model, logging, and rate limits.
   - Output: API contract, backend architecture plan, data handling notes.
7. Integration plan
   - Align API client behavior, environment variables, mock strategy, contract checks, retries, error handling, and cross-layer dependencies.
   - Output: integration contract, env variable map, failure handling plan.
8. QA test plan
   - Define unit, integration, E2E, accessibility, responsive, security-adjacent, and manual QA coverage.
   - Output: test matrix, QA checklist, acceptance criteria.
9. Deployment readiness review
   - Review build commands, environment setup, secrets handling, hosting target, database migrations, monitoring, rollback, and owners.
   - Output: deployment checklist, rollback plan, release readiness notes.
10. Release handoff
   - Summarize completed artifacts, validation evidence, unresolved risks, deployment steps, rollback path, and owner responsibilities.
   - Output: release handoff summary, final checklist, follow-up recommendations.

## Inputs required

- business purpose and success criteria
- target users and user roles
- website type and project scope
- required pages, routes, and user journeys
- content, brand, responsive, and accessibility requirements
- preferred frontend stack, especially React or Next.js expectations
- backend dependencies, data sources, and API constraints
- authentication, authorization, and data sensitivity requirements
- target hosting platform and deployment ownership
- testing expectations, timeline, and acceptance criteria

## Outputs produced

- project intake summary
- requirements summary and page map
- wireframe brief and UX flow
- UI design specification
- React/Next.js frontend architecture plan
- backend/API architecture plan
- integration plan
- QA test matrix and manual checklist
- deployment readiness checklist
- release handoff summary

## Frontend React/Next.js considerations

Frontend planning should address:

- route structure and page ownership
- component boundaries and reusable UI patterns
- server/client rendering boundaries for Next.js
- data fetching strategy and cache assumptions
- state management scope and form handling
- loading, empty, and error states
- responsive behavior across mobile, tablet, and desktop
- accessibility expectations, including keyboard flow and semantic structure
- asset handling, metadata, SEO, and performance-sensitive pages
- proposed file list before implementation begins

## Backend/API considerations

Backend planning should address:

- API endpoint inventory and ownership
- request and response schemas
- authentication and authorization rules
- validation, normalization, and error responses
- persistence model and external data dependencies
- pagination, filtering, sorting, and search behavior where relevant
- rate limits, logging, auditability, and observability
- sensitive data handling and secret boundaries
- migration or seed data needs
- compatibility with frontend integration and QA mocks

## QA testing criteria

QA planning should include:

- unit tests for critical frontend utilities, backend validation, and business rules
- component or interaction tests for important UI states
- integration tests for API contracts and frontend API clients
- E2E tests for primary user journeys and role-specific flows
- accessibility checks for keyboard navigation, labels, focus, contrast, and semantic structure
- responsive checks for defined viewport classes
- manual QA checklist for content, navigation, forms, errors, and release-critical flows
- regression checks for existing behavior when modifying an existing website
- explicit acceptance criteria mapped back to requirements

## Deployment checklist

Before release handoff, verify:

- build command and expected output are known
- required environment variables are documented without secret values
- hosting target and deployment owner are identified
- API base URLs and environment-specific configuration are clear
- database migration or data setup steps are defined if needed
- monitoring, logs, and alert ownership are identified
- rollback path is documented
- release notes and known risks are captured
- post-deployment smoke checks are listed
- handoff owner and follow-up actions are assigned

## Risks and guardrails

- Do not start implementation before the plan, target files, risks, and test criteria are shown and approved.
- Do not create `.claude/` paths.
- Do not store API keys, tokens, passwords, or secrets in planning artifacts.
- Do not scaffold a real app, `package.json`, or `src/` unless implementation is separately approved.
- Keep frontend, backend, integration, QA, and deployment responsibilities separate enough for review.
- Keep assumptions visible when requirements are incomplete.
- Require explicit approval before scope expansion, sensitive data handling, repository standard changes, deployment changes, or Git operations.
- Keep `_workspace/` as temporary handoff space only when a specific run needs it; do not touch it for adding this reusable pattern.

## Example Codex prompt for using this harness in a real project

```text
Use the full-stack-website-development-harness to plan a full-stack website project.

Project goal:
Build a customer portal where users can sign in, view account details, update contact information, and submit support requests.

Target stack:
Next.js frontend, REST API backend, hosted on Vercel or equivalent.

Please start with project intake, requirements and page map, UX flow, frontend architecture, backend/API architecture, integration plan, QA test plan, deployment readiness checklist, and release handoff. Do not create implementation files until I approve the plan.
```

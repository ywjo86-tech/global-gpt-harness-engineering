# Data Pipeline Design Harness Pattern

## Purpose

Use this pattern to design a data pipeline with clear schema, ETL logic, validation rules, monitoring, and operational ownership.

## When to Use

- A new ingestion, transformation, reporting, or analytics pipeline is needed.
- Data quality and lineage matter.
- Multiple systems or owners are involved.
- Monitoring and failure recovery need explicit design.

## Agent Team Composition

- Pipeline architect: owns the full design and handoffs.
- Schema designer: defines source, staging, and target schemas.
- ETL designer: defines extraction, transformation, loading, and dependencies.
- Data quality reviewer: defines validation and reconciliation rules.
- Monitoring designer: defines alerts, dashboards, and failure handling.

## Workflow

1. Clarify business purpose, consumers, and freshness requirements.
2. Map source systems, target systems, and ownership.
3. Design schemas, keys, partitions, and data contracts.
4. Define ETL logic, dependencies, idempotency, and backfill behavior.
5. Define validation rules for completeness, correctness, and freshness.
6. Define monitoring, alerting, logging, and escalation.
7. Review security, privacy, scalability, and maintainability risks.

## Inputs

- Business goal
- Source and target systems
- Data entities and volume
- Refresh cadence
- Compliance constraints
- Consumer requirements

## Outputs

- Pipeline architecture
- Schema design
- ETL logic plan
- Data validation rules
- Monitoring and alerting plan
- Operational handoff notes

## Validation Criteria

- Data contracts are explicit.
- Validation rules are testable.
- Failure handling and replay behavior are defined.
- Monitoring covers freshness, volume, quality, and failures.
- Ownership is clear across systems.

## Cautions

- Do not hide data quality issues in transformation logic.
- Do not design monitoring as an afterthought.
- Confirm sensitive data handling before implementation.

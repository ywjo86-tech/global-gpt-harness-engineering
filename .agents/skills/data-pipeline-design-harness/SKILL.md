---
name: data-pipeline-design-harness
description: Run a reusable data pipeline design agent team pattern for schema, ETL logic, validation rules, and monitoring.
---

# Data Pipeline Design Harness

Use this skill when designing a data ingestion, transformation, validation, or reporting pipeline.

## Inputs

- Business purpose
- Source systems
- Target consumers
- Data volume and cadence
- Quality and compliance constraints

## Agent Team Pattern

- Pipeline architect: owns end-to-end design.
- Schema designer: defines source, staging, and target models.
- ETL designer: defines extraction, transformation, and load logic.
- Data quality reviewer: defines validation and reconciliation rules.
- Monitoring designer: defines observability, alerts, and failure handling.

## Workflow

1. Clarify pipeline goal, consumers, and freshness needs.
2. Map source systems, target stores, and ownership boundaries.
3. Design schemas and data contracts.
4. Define ETL logic, dependencies, and failure behavior.
5. Define validation, reconciliation, and data quality rules.
6. Define monitoring, alerting, and operational handoff.
7. Review the design against scale, security, and maintainability risks.

## Outputs

- Pipeline architecture
- Schema and data contract notes
- ETL logic plan
- Data validation rules
- Monitoring and alert plan
- Risks and open questions

## Validation

- Source and target ownership are clear.
- Data quality rules are testable.
- Failure and retry behavior is defined.
- Monitoring covers freshness, completeness, and correctness.

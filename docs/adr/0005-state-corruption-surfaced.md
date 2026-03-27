# ADR-0005 — State corruption must be surfaced explicitly

## Status
Accepted

## Context
The JSON state store previously ignored parsing failures silently and fell back to default state.

## Decision
State parsing issues must be surfaced explicitly in logs and through a warning field in the loaded state.

## Consequences
- Operators and future services can detect degraded persistence situations.
- Silent resets become less likely to remain unnoticed.

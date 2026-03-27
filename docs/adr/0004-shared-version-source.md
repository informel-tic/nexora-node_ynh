# ADR-0004 — Shared Python version constant

## Status
Accepted

## Context
The same application version was repeated across several Python entrypoints.

## Decision
Python applications import a shared version constant from `nexora_core.version`.

## Consequences
- Control plane, node agent and core service share the same Python-level version source.
- Packaging/release automation remains a follow-up checkpoint.

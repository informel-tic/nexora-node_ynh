# ADR-0003 — MCP is an interface adapter, not the domain core

## Status
Accepted

## Context
Nexora exposes a broad MCP surface for AI-assisted operations.
That surface must remain consistent with REST and operator workflows.

## Decision
MCP is treated as an adapter interface over stable Nexora capabilities.
Business logic should live in the shared core and service layer, not diverge inside MCP handlers.

## Consequences
- MCP tooling remains valuable without becoming a second product architecture.
- Domain capabilities can be reused by API, console and AI interfaces.

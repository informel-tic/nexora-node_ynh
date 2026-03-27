# ADR-0001 — Nexora is a control-plane platform

## Status
Accepted

## Context
The repository contains a local node runtime, a control-plane API, a console UI, an MCP layer, blueprints and a YunoHost package.
The previous narrative could be misread as “a large YunoHost package”.

## Decision
Nexora is defined as a control-plane platform for YunoHost infrastructures.
The official product decomposition is Node + Control Plane + Console + MCP + Value Modules.

## Consequences
- Architecture and docs must be expressed from the platform viewpoint.
- The package is not the full product boundary.
- Control-plane responsibilities become the canonical orchestration model.

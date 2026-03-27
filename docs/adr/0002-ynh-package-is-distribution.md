# ADR-0002 — The YunoHost package is a distribution artifact

## Status
Accepted

## Context
The repository ships a YunoHost package today, but the platform scope is broader than packaging.

## Decision
The YunoHost package is treated as a supported distribution artifact for the local Nexora runtime.
It is not the canonical expression of Nexora architecture.

## Consequences
- Package scripts stay focused on install/upgrade/restore and exposure concerns.
- Domain logic remains in Python services and shared core modules.
- Support boundaries can evolve independently from SaaS/control-plane features.

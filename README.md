# Nexora Node YunoHost

`nexora-node_ynh` is the Layer B repository for Nexora: the local node agent runtime, the YunoHost packaging, the enrollment and trust lifecycle, and the local execution adapters.

## Scope

- `apps/node_agent/` - local FastAPI runtime bound to the node
- `src/nexora_core/` - shared core plus node-specific adapters such as `yh_adapter.py`, `docker.py`, `storage.py`, and `migration.py`
- `ynh-package/` - native YunoHost packaging assets
- `deploy/bootstrap-node.sh` and related scripts - node bootstrap, adopt, and augment flows

This repository intentionally excludes the SaaS control plane, the console, MCP, and SaaS-only orchestration modules.

## Architecture

```text
Layer A - YunoHost runtime (untouched)
Layer B - Node agent runtime, identity, trust, local execution
Layer C - Control plane and MCP (lives in nexora-saas)
```

## Run locally

```bash
PYTHONPATH=src python -m pytest tests/ -q
python -m uvicorn apps.node_agent.api:app --host 127.0.0.1 --port 38121
```

## Packaging

- `nexora-node-agent` starts the local node runtime
- `ynh-package/` remains the authoritative YunoHost package source
- bootstrap entrypoints stay focused on `fresh`, `adopt`, and `augment` node flows

## Key invariants

- the agent stays locally bound and reverse-proxy protected
- enrollment, attestation, and trust state remain auditable
- token comparison stays timing-safe via `secrets.compare_digest()`
- token files remain mode `0o600`

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/RUNBOOKS.md`
- `docs/SECURITY.md`
- `docs/SUBSCRIBER_GUIDE.md`
- `docs/CI_QUALITY_GATES.md`

## License

AGPL-3.0-or-later

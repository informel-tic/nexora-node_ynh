# Nexora administration notes

## Runtime model

Nexora keeps YunoHost as the node-level core and adds a control plane on top. The MCP server exposes 168 tools across 25 modules, accessible via the MCP protocol or the REST API.

## Profiles

Nexora operates in 4 modes, configured in `config.toml`:

- **observer** (default) — read-only, audit, monitoring, documentation, scoring
- **operator** — safe actions: restart services, create backups, apply branding
- **architect** — generate configurations, blueprints, topologies, PRA plans
- **admin** — destructive operations: install/remove apps, upgrade, restore

## API authentication

All API endpoints require a Bearer token. The token is auto-generated at install and stored in the app data directory. Use it with:

```
Authorization: Bearer <token>
```

Or via the `X-Nexora-Token` header.

## Recommended deployment on existing nodes

1. Install in observer mode first
2. Review the adoption report (`/api/adoption/report`)
3. Keep existing domains, apps and permissions untouched
4. Enable operator/architect modes progressively
5. Keep destructive features disabled unless explicitly needed

## Blueprints

8 business blueprints are included: PME, MSP, Agency, Training, Collective, E-commerce, Studio, SI interne. Use `ynh_blueprint_validate_prereqs` before deploying.

## Automation

Use `nexora-job --list` to see available automation templates. Generate a crontab with `ynh_auto_generate_crontab`.

## Docker

Docker containers can run alongside YunoHost apps. Use `ynh_docker_list_templates` to see available pre-built services (Redis, PostgreSQL, Grafana, etc.). Docker is optional and requires Docker Engine to be installed separately.

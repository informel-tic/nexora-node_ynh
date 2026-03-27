# Nexora YunoHost package

This folder contains the YunoHost package for the Nexora control plane.

## Scope

- The YunoHost package exposes the **control-plane** behind a YunoHost domain/path.
- The monorepo bootstrap can additionally deploy the **node-agent** service on the same host or on agent-only nodes.

## Supported monorepo deployment flows

- fresh install on a blank Debian 12 / YunoHost-compatible node
- adopt an existing populated YunoHost (dry-run first)
- augment an already adopted node
- agent-only bootstrap for remote fleet members

## Examples

```bash
MODE=fresh PROFILE=control-plane+node-agent DOMAIN=example.org PATH_URL=/nexora ./deploy/bootstrap-full-platform.sh
MODE=adopt PROFILE=control-plane+node-agent DOMAIN=example.org PATH_URL=/nexora ./deploy/bootstrap-full-platform.sh
MODE=adopt PROFILE=control-plane+node-agent DOMAIN=example.org PATH_URL=/nexora CONFIRM_ADOPT=yes ./deploy/bootstrap-full-platform.sh
MODE=augment PROFILE=control-plane+node-agent DOMAIN=example.org PATH_URL=/nexora CONFIRM_AUGMENT=yes ./deploy/bootstrap-full-platform.sh
MODE=augment PROFILE=node-agent-only TARGET_HOST=node-01.internal ./deploy/bootstrap-full-platform.sh
```

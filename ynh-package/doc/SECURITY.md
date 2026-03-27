Nexora follows a defense-in-depth approach:

- **Observer mode by default**: no destructive operations unless explicitly enabled
- **API authentication**: all endpoints require a Bearer token (auto-generated at install)
- **Operator-only lock by default**: `/etc/nexora/api-token-roles.json` is initialized empty, and operator-only routes require explicit trusted role binding (`operator`/`admin`/`architect`)
- **CSRF protection**: mutating requests require Origin verification and a custom header
- **Input validation**: all user-supplied parameters are validated (IP, hostnames, paths, integers)
- **Path traversal protection**: file exports are restricted to allowed directories
- **Systemd hardening**: NoNewPrivileges, ProtectSystem=strict, ProtectHome=true
- **Audit logging**: all tool invocations are logged to `/var/log/yunohost-mcp-server/audit.log`
- **Policy engine**: 4 profiles (observer/operator/architect/admin) control tool access
- **Deployment scope guardrail**: `NEXORA_DEPLOYMENT_SCOPE=subscriber` blocks control-plane surfaces except minimal enrollment/health endpoints (for subscriber-facing runtime separation)

Keep destructive tools disabled on production instances unless explicitly required.

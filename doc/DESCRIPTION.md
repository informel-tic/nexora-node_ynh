Nexora Node Agent enrolls your YunoHost server into the Nexora SaaS platform.

**Features:**
- Secure enrollment with your Nexora SaaS operator
- Docker overlay services deployed remotely by your operator (Redis, PostgreSQL, Grafana, etc.)
- Monitoring, security scoring, and drift detection
- Full rollback on uninstall - restores pure YunoHost state
- Anti-tampering protection: features require SaaS authorization

**Security model:** The node agent is a passive receiver. It cannot install
features by itself - all deployments are signed and authorized by the SaaS
control plane. Uninstalling this app automatically removes ALL Nexora additions.

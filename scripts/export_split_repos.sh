#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist/repo-split}"
OPERATOR_DIR="$OUT_DIR/operator-private"
SUBSCRIBER_DIR="$OUT_DIR/subscriber-public"

rm -rf "$OPERATOR_DIR" "$SUBSCRIBER_DIR"
mkdir -p "$OPERATOR_DIR" "$SUBSCRIBER_DIR"

echo "==> Export operator-private repository snapshot"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.build' \
  --exclude 'dist/repo-split' \
  "$ROOT/" "$OPERATOR_DIR/"

cat > "$OPERATOR_DIR/.nexora-repo-profile" <<'EOF'
profile=operator-private
intended_use=internal-saas-control-plane
EOF

echo "==> Export subscriber-public repository snapshot"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.build' \
  --exclude 'dist/repo-split' \
  "$ROOT/" "$SUBSCRIBER_DIR/"

rm -rf "$SUBSCRIBER_DIR/apps/control_plane"
rm -rf "$SUBSCRIBER_DIR/apps/console"
rm -rf "$SUBSCRIBER_DIR/ynh-package"
rm -f "$SUBSCRIBER_DIR/deploy/templates/nexora-control-plane.service"

cat > "$SUBSCRIBER_DIR/.nexora-repo-profile" <<'EOF'
profile=subscriber-public
intended_use=node-agent-only-enrollment
EOF

cat > "$SUBSCRIBER_DIR/README_SUBSCRIBER_SCOPE.md" <<'EOF'
# Nexora Subscriber Public Scope

This export intentionally strips control-plane and console artifacts.
Use only:

- `NEXORA_DEPLOYMENT_SCOPE=subscriber`
- `PROFILE=node-agent-only`

Do not use this scope to host a full Nexora SaaS control-plane.
EOF

echo "Split repositories exported:"
echo "- operator:   $OPERATOR_DIR"
echo "- subscriber: $SUBSCRIBER_DIR"

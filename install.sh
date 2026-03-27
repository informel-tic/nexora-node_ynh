#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "This repository deploys the Nexora node agent and YunoHost package."
echo "Example: PROFILE=node-agent-only ENROLLMENT_MODE=pull $ROOT_DIR/deploy/bootstrap-node.sh"

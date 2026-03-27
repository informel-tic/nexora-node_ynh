#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Run package_check manually against: $ROOT_DIR/ynh-package"
echo "This helper is informational; package_check is not bundled in this archive."

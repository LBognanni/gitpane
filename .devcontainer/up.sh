#!/usr/bin/env bash
# Start the devcontainer with the main repository root as the workspace folder.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
common="$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)"
exec npx -y @devcontainers/cli up \
  --workspace-folder "${common%/.git}" \
  --config "$here/devcontainer.json" "$@"

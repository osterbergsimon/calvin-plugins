#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$repo_root/scripts/build-plugin.sh" "$@"

if ! git -C "$repo_root" diff --quiet -- '*/frontend/dist.js'; then
  echo "Plugin frontend artifacts are out of sync. Run scripts/build-plugin.sh and commit frontend/dist.js." >&2
  git -C "$repo_root" diff -- '*/frontend/dist.js' >&2
  exit 1
fi

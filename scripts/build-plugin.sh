#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin="${1:-}"

build_plugin() {
  local plugin_dir="$1"
  local entry="$plugin_dir/frontend/src/index.js"
  local out_dir="$plugin_dir/frontend"

  if [[ ! -f "$entry" ]]; then
    if [[ -n "$plugin" ]]; then
      echo "No frontend source entry found: $entry" >&2
      exit 1
    fi
    return
  fi

  echo "Building $(basename "$plugin_dir") frontend"
  CALVIN_PLUGIN_ENTRY="$entry" \
    CALVIN_PLUGIN_OUTDIR="$out_dir" \
    CALVIN_PLUGIN_DIST_NAME="dist.js" \
    npx vite build --config "$repo_root/scripts/vite.config.js"
}

if [[ -n "$plugin" ]]; then
  build_plugin "$repo_root/$plugin"
else
  for plugin_dir in "$repo_root"/*; do
    [[ -d "$plugin_dir" ]] || continue
    build_plugin "$plugin_dir"
  done
fi

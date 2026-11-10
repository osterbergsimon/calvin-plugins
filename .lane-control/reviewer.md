---
lane_control_template: 1
max_lines: 30
read_by: reviewer
---
Additions to your persona for this project. They never relax a rule there, and they never lower a finding's level.

## Look at first
- Credentials in `imap/plugin.py`, `immich/plugin.py`, `mealie/plugin.py`, `lychee/plugin.py`, `unsplash/plugin.py`: logged, echoed in errors, or left in fixtures.
- `scripts/validate_plugins.py`: a weakened rule lets bad manifests into the catalog.
- `plugin.json` against the validator rules: `api_version: 1`, no retired keys, label and description copy.
- `plugins.json`: must match what `scripts/rebuild-manifest.py` makes; `catalog: false` only on the two test plugins.
- `.github/workflows/rebuild-manifest.yml`: it pushes to main with a token.
- `sl_departures/plugin.py`, `yr_weather/plugin.py`: external API parsing and filter edge cases.

## How to exercise a change
- Plugin code: run the plugin's `test_*.py` with the Calvin backend venv, plus the validator on that plugin. Network is stubbed in tests; do not hit real services.
- Manifest or `plugins.json`: run `python3 scripts/validate_plugins.py`; compare `plugins.json` with a rebuild.
- `dist.js` files: read only, prebuilt bundles, source lives in this repo.
- Workflows and docs: read only, they run only on the host.

## Also blockers here
- A test fixture or doc holding a real token, host, IP or mailbox.
- A plugin edit that renames a config field key without a migration.

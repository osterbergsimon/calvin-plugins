---
lane_control_template: 1
max_lines: 30
read_by: coordinator
---
Additions to your persona for this project. They never relax a rule there.

## First turn
- `bd ready` for open CPL issues.
- `.github/workflows/ci.yml` for the pinned `CALVIN_REF`.
- `CREATING_PLUGINS.md` for the plugin contract.
- `scripts/validate_plugins.py` for what the validator enforces.
- `docs/superpowers/specs/` for an existing design on the plugin in question.

## Every lane brief adds
- Run the validator for the touched plugin, and its tests against a Calvin checkout; report which ran.
- Do not hand-edit `plugins.json` unless a manifest changed; use `scripts/rebuild-manifest.py`.
- `plugin.json` must keep `api_version: 1` and copy rules (sentence-case labels, one-line descriptions ending in a full stop).
- Do not edit `chromecast/frontend/dist.js` or `test-plugin-frontend/frontend/dist.js` by hand without a stated reason.

## Opening lanes here
Base branch `main`. No `orca.yaml`. No setup step in this repo; tests need a Calvin checkout with its backend venv (`uv sync --extra dev`), which is at `../calvin` (owner's answer).

## Owner first
- Bumping `CALVIN_REF` (`develop` is being removed).
- Changes to the `.github/workflows/` files (rebuild-manifest pushes to main).
- Changing a plugin's id, config field keys or stored-config shape (breaks installed users).
- Edits to spec or audit documents.

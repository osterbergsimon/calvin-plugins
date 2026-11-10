---
lane_control_template: 1
max_rows: 40
read_by: coordinator, design lead, reviewer
---
How lanes are routed in this project. Tier by the paths a task touches: the highest tier wins, in doubt one tier up.
The budget decides how many lanes run, never the tier. Deep whatever the paths: a diagnosis (cause unknown), a
cross-cutting refactor, a feature with subtle text or locale handling, an open design question, a follow-up of a
silent-loss or false-gate-claim finding. Swift only for prose docs, scripts without private data and CI; it may port
tests but never adds expectations, and never takes a task that needs private data. A PR touching a path above its
lane's tier fails review.

Review tiers, by what a PR touches, not by who wrote it. A: the coordinator's own checks only. B: plus an independent
review by a different model. C: plus a deep-tier review, and spec statements approved by the owner before merge. Keep C for paths where a
mistake really hurts (secrets, auth, data loss, the check that keeps bad input out, sandbox and host settings) and
name that harm in the row's why; ordinary code in a sensitive package is B. The "in doubt one tier up" rule is for the
model tier, not for the review letter.

## Path map
path glob | tier | review | why
--- | --- | --- | ---
`scripts/validate_plugins.py` | deep | C | the check that keeps bad manifests out of the public catalog
`test_validate_plugins.py` | deep | B | tests of that check
`.github/workflows/rebuild-manifest.yml` | deep | C | pushes to main with a repo token
`.github/workflows/ci.yml` | standard | B | pins the Calvin ref the gates run against
`imap/plugin.py` | deep | C | holds mailbox credentials; a leak exposes a user's mailbox
`immich/plugin.py`, `mealie/plugin.py`, `lychee/plugin.py`, `unsplash/plugin.py`, `nasa-apod/plugin.py` | deep | C | hold service tokens; a leak exposes a user's accounts
`sl_departures/plugin.py`, `yr_weather/plugin.py`, `picsum/plugin.py` | deep | B | parse untrusted external API responses
`chromecast/plugin.py`, `system-monitor/plugin.py` | deep | B | act on local network and host
`*/plugin.json`, `midnight-theme/theme.json` | standard | B | install contract with Calvin
`plugins.json` | standard | B | generated catalog
`scripts/rebuild-manifest.py` | standard | B | writes the catalog
`scripts/create_plugin.py`, `test_create_plugin.py` | standard | B | scaffold others copy
`*/frontend/dist.js` | deep | B | prebuilt bundle, source in this repo, runs in browser
`*/plugin.py` | standard | B | plugin logic
`*/test_*.py`, `conftest.py`, `pytest.ini` | standard | B | tests
`docs/**`, `**/README.md`, `CREATING_PLUGINS.md`, `README.md` | swift | A | prose docs
`.claude/**` | deep | C | hooks run commands in every agent session
`.beads/hooks/**`, `AGENTS.md`, `CLAUDE.md`, `.lane-control/**` | deep | B | host git hooks and prompts that steer agents
`.beads/**`, `.gitignore` | standard | B | tracker settings
`**` | standard | B | default

## Deep whatever the paths, here
Any change to a plugin's id, config field keys or stored-config shape. Any change that handles credentials. Any task that depends on Calvin host behavior not visible in this repo.

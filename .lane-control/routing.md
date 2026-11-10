---
lane_control_template: 1
max_rows: 40
read_by: coordinator, design lead, reviewer
---
How lanes are routed in this project. Route by the intelligence the work needs, cheapest first. Tiers: swift =
OpenCode with DeepSeek (hosted, sandboxed), the default; standard = Claude Sonnet; deep = Claude Opus. Claude is
only for the most qualified work, Sonnet before Opus. Tier by the paths a task touches: the highest tier wins, in
doubt one tier up. The budget decides how many lanes run, never the tier.

Swift: ordinary plugin code (plugins that hold no credentials), tests, docs, scaffold scripts and CI. Swift may write a
failing test first. Swift never takes a task that needs private data or real credentials; a hosted model seeing this
public code is fine. Standard whatever the paths: a diagnosis (cause unknown), a cross-cutting refactor, an open
design question, a change that needs Calvin host behavior not visible in this repo. Deep: the review-C paths and the
files that steer agents. A PR touching a path above its lane's tier fails review.

Reviews always run on Claude, whoever wrote the PR (a swift lane gets a standard reviewer). Review tiers, by what a
PR touches, not by who wrote it. A: the coordinator's own checks only. B: plus an independent review by a different
model. C: plus a deep-tier review, and spec statements approved by the owner before merge. Keep C for paths where a
mistake really hurts (secrets, auth, data loss, the check that keeps bad input out, sandbox and host settings) and
name that harm in the row's why; ordinary code in a sensitive package is B. The "in doubt one tier up" rule is for the
model tier, not for the review letter.

## Path map
path glob | tier | review | why
--- | --- | --- | ---
`scripts/validate_plugins.py` | deep | C | the check that keeps bad manifests out of the public catalog
`test_validate_plugins.py` | swift | B | tests of that check
`.github/workflows/rebuild-manifest.yml` | deep | C | pushes to main with a repo token
`.github/workflows/ci.yml` | swift | B | pins the Calvin ref the gates run against
`imap/plugin.py` | deep | C | holds mailbox credentials; a leak exposes a user's mailbox
`immich/plugin.py`, `mealie/plugin.py`, `lychee/plugin.py`, `unsplash/plugin.py`, `nasa-apod/plugin.py` | deep | C | hold service tokens; a leak exposes a user's accounts
`sl_departures/plugin.py`, `yr_weather/plugin.py`, `picsum/plugin.py` | swift | B | parse untrusted external API responses
`chromecast/plugin.py`, `system-monitor/plugin.py` | swift | B | act on local network and host
`*/plugin.json`, `midnight-theme/theme.json` | swift | B | install contract with Calvin
`plugins.json` | swift | B | generated catalog
`scripts/rebuild-manifest.py` | deep | C | its output is pushed to main by the workflow without review
`scripts/create_plugin.py`, `test_create_plugin.py` | swift | B | scaffold others copy
`*/frontend/dist.js` | swift | B | prebuilt bundle, source in this repo, runs in browser
`*/plugin.py` | swift | B | plugin logic
`*/test_*.py`, `conftest.py`, `pytest.ini` | swift | B | tests
`docs/**`, `**/README.md`, `CREATING_PLUGINS.md`, `README.md` | swift | A | prose docs
`.claude/**` | deep | C | hooks run commands in every agent session
`.beads/hooks/**`, `AGENTS.md`, `CLAUDE.md`, `.lane-control/**` | deep | B | host git hooks and prompts that steer agents
`.beads/**`, `.gitignore` | deep | C | ignore rules keep the credential key and Dolt DB out of a public repo
`**` | standard | B | default

## Deep whatever the paths, here
Any change to a plugin's id, config field keys or stored-config shape. Any change that handles credentials.

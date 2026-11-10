---
lane_control_template: 1
max_lines: 30
read_by: design lead
---
Additions to your persona for this project. They never relax a rule or lower the quality floor there.

## Subject
Calvin dashboard users see these plugin widgets on a home display. The only real frontend is the Chromecast now-playing widget: its one job is to show what is playing on a cast device at a glance. `test-plugin-frontend` is a test fixture, not a product screen.

## Where it lives
- `chromecast/frontend/dist.js`: web component `calvin-chromecast-now-playing`, prebuilt, source lives in this repo (owner's answer).
- `test-plugin-frontend/frontend/dist.js`: web component `calvin-test-frontend`, test fixture.
- Both are declared in each plugin's `plugin.json`. The host app (Calvin, separate repo) loads them.

## Existing design language
none found (looked in: chromecast/frontend, test-plugin-frontend/frontend, docs/). Theme tokens live in `midnight-theme/theme.json`; copy rules are in Calvin's plugin-copy doc, outside this repo.

## Seeing it run
Not runnable from this repo: it needs a Calvin checkout that loads the plugin. The Chromecast plugin talks to real cast devices on the local network; stub them, never hit real devices. Without a Calvin checkout, say so and review the bundle by reading only.

## Quality floor, added
none. Because `dist.js` has no source here, the source lives in this repo (owner's answer); change the source, not the bundle by hand, and state the reason.

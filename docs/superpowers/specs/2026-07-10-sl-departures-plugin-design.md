# SL Departures Plugin — Design

**Date:** 2026-07-10
**Status:** Approved design, pending implementation
**Plugin id:** `sl_departures`
**Type:** `service` (Calvin plugin contract 1.0)

## Summary

A Calvin `service` plugin that shows a live public-transport departure board
for a single Stockholm (SL) stop, filterable by line, transport mode, and
direction. Backed by the **SL Transport API**, which requires **no API key**.
Each instance renders a panel (built-in `status` list renderer) and a compact
clock-bar strip showing the next (and optionally the following) departure.

Scope is deliberately Stockholm/SL only — no provider-abstraction layer. A
future non-SL provider would be a separate plugin.

## Data source

**SL Transport API** — `https://transport.integration.sl.se`, no API key.

- **Departures:** `GET /v1/sites/{site_id}/departures?forecast={minutes}`
  Optional API-side filters exist (transport mode, line, direction); we apply
  filtering in Python for full control and to keep behaviour uniform.
  Each departure object includes: `line.designation`, `line.transport_mode`,
  `destination`, `direction_code`, `display` (human string e.g. `"Nu"` /
  `"4 min"`), `scheduled`, `expected`, `state`, and `deviations`.
- **Sites:** `GET /v1/sites?expand=true` — full list of stops with `id` and
  `name`. Used to resolve a typed stop name → numeric `site_id`. Response is
  large; cache it in-process (class-level, short TTL) so repeated Test clicks
  don't refetch.

Be a good API citizen: no key means shared infrastructure — use a sane
`poll_interval_ms` (30 s) and cache the Sites list.

## Configuration (`instance_config_schema`)

| field | type | required | notes |
|---|---|---|---|
| `stop_name` | string | yes | e.g. `"Tappström"`. Resolved to a site id on Test. |
| `site_id` | integer | no | Auto-filled/cached after resolution; if set, wins over `stop_name`. |
| `lines` | string | no | Comma list, e.g. `"176, 177"`. Empty = all lines. Matched against `designation`. Placeholder demonstrates the multi-line form. |
| `modes` | string | no | Comma list of `bus` / `metro` / `train` / `tram` / `ship`, e.g. `"bus, train"`. Empty = all modes. (Comma string, not a multi-select — no such UI component exists in this repo.) |
| `direction` | select | no | `Any` / `1` / `2` (SL's arbitrary direction code). Default `Any`; most users filter by line instead. |
| `max_departures` | integer | no | Rows on the panel. Default `8`. |
| `forecast_minutes` | integer | no | API time window. Default `60`. |
| `clockbar_show_following` | boolean | no | Clock-bar shows the departure after next as well. Default `true`. |

### Stop resolution (`test_connection` classmethod)

Powers a "Test Connection" `ui_action` (`type: "test"`).

1. Fetch/cached Sites list, fuzzy-match `stop_name` (case-insensitive
   contains, prefer exact).
2. **Single match** → return `{success: true, message: "Tappström (site
   9184) — next: 176 to Brommaplan in 4 min", site_id: 9184}` and shows a
   sample of the filtered departures.
3. **Multiple matches** → `{success: false, message: "Several stops match
   'Centralen': 1002 Stockholm City, 9001 T-Centralen, … — set the site id"}`
   listing candidate ids so the user disambiguates.
4. **No match / network error** → direction-y `{success: false, message:
   "No SL stop matches 'Xyz' — check spelling"}`.

`validate_config` (async classmethod): start from `normalize_config`, require
`stop_name` non-empty (or a `site_id`), and validate `direction ∈ {Any,1,2}`.

## Data flow & display shaping

`fetch(start_date=None, end_date=None)`:

1. Resolve site id (prefer `site_id`, else resolve `stop_name`, else return an
   `{"error": …}` payload).
2. `GET /v1/sites/{id}/departures?forecast={forecast_minutes}`.
3. Filter departures by `lines`, `modes`, `direction`.
4. Sort by `expected` (fallback `scheduled`), take `max_departures`.
5. `_shape_for_display()` → payload:

```json
{
  "stop": "Tappström",
  "departures": [
    {"label": "176 · Brommaplan", "display": "4 min", "status": "ok"},
    {"label": "177 · Brommaplan", "display": "9 min", "status": "warn"}
  ],
  "clockbar": {"label": "Tappström", "value": "176·4′ · 177·9′", "status": "ok"},
  "next_count": 2
}
```

Per-departure shaping:

- `label`: `"{designation} · {destination}"`. The line number is the identity
  (as on SL's own signage), carried as text in the theme's `var(--ink)` /
  `var(--font-ui)`.
- `display`: SL's `display` string, else computed minutes from `expected`.
- `status`: `ok` normally; `warn` if a deviation/delay is present; `error` if
  cancelled (`state` indicates cancelled).

### Visual theme

Match the main app exactly by using the built-in `StatusRenderer` and adding
nothing that fights it:

- **No decorative icons/emoji.** The renderer draws the `icon` slot as plain
  text, and its design rule is "color appears only when something needs
  attention — `ok` stays monochrome." A colorful mode emoji (🚌) would put
  non-semantic color on the wall and break that discipline. Transport mode is
  already implied by the filtered lines; the line designation leads each row.
- **Color reserved for disruptions.** Only `warn`/`error` tint (via
  `var(--warn)` / `var(--err)`) and light the attention lamp. Normal
  departures are monochrome.
- Typography, ink colors, hairline rows and the active theme (e.g. midnight)
  come for free from `StatusRenderer` — no plugin-side styling, no
  web-component. This is the whole reason we chose a built-in renderer over a
  custom board.

### Panel — `display_schema`

Built-in `status` renderer, list layout:

```python
display_schema={
    "kind": "status",
    "layout": "list",
    "data_path": "$.departures",
    "item": {
        "label_path": "$.label",
        "value_path": "$.display",
        "status_path": "$.status",
    },
    "poll_interval_ms": 30000,
}
```

Empty board (no filtered departures in window) shapes a single quiet item
("No departures in the next 60 min"), not an error.

### Clock bar — `statusbar_schema`

`status` kind (the clock-bar namespace is status-only — a strip, not a panel):

```python
statusbar_schema={
    "kind": "status",
    "item": {
        "label_path": "$.clockbar.label",
        "value_path": "$.clockbar.value",
        "status_path": "$.clockbar.status",
    },
    "poll_interval_ms": 30000,
}
```

- `clockbar.label` is the stop name — renders as the theme's uppercase
  micro-label (`var(--ink-3)`), so the strip self-identifies without an icon.
- `clockbar.value` shows the **next** filtered departure as `"{line}·{min}′"`.
- When `clockbar_show_following` is true and a second filtered departure
  exists, append it: `"176·4′ · 177·9′"`. Each entry carries its own line, so
  a mixed-line pair reads correctly.
- `clockbar.status` reflects the next departure (warn/error if delayed or
  cancelled), so a disruption lights the strip.
- No upcoming filtered departure → quiet `—`.

One instance → one panel + one clock-bar strip. A second stop — or a second
*view* of the same stop with different filters (e.g. a bus board and a metro
board at one hub) — is a second instance. `supports_multiple_instances = True`
with **no `instance_identity`**: instances are independent and user-created, so
two boards for the same `site_id` with different `lines`/`modes` don't collide.

## Error handling

- Network/HTTP failure → payload `{"error": "Couldn't reach SL — retrying"}`.
  Copy is direction, never a stack trace (error strings surface on the wall).
- Empty board → friendly "no departures" item (see above), not an error.
- Unresolvable stop at fetch time → `{"error": "Stop not set — open settings
  and pick a stop"}`.

## Testing (`test_sl_departures.py`, mealie-style)

Run from the Calvin backend (`cd ../calvin/backend && uv run pytest
../../calvin-plugins/sl_departures`).

- **Contract:** loader discovers the class; no module-level hooks; metadata
  fields (`type_id == "sl_departures"`, family, display + statusbar schema
  kinds and bound paths).
- **Config:** normalization (types), `validate_config` (stop/site presence,
  direction domain).
- **Filtering:** `lines` (single + multiple, e.g. `176, 177`), `modes`,
  `direction`; sort + `max_departures` truncation.
- **Shaping:** `_shape_for_display` against the `status` schema paths — label
  format (`{designation} · {destination}`), `display` fallback from
  `expected`, deviation → `warn`, cancellation → `error`, and that no icon/
  color is emitted for on-time departures (theme discipline).
- **Clock bar:** stop-name label, next-only vs next+following
  (`clockbar_show_following`), mixed-line pair formatting, empty → `—`.
- **`test_connection`:** single match, multi-match (candidate list), no match,
  network error — all against a mocked Sites response.

Use `httpx` mocking (respx or monkeypatched transport) for the API; no live
network in tests.

## Decisions & non-goals

- **Built-in `status` renderer**, not a custom web-component board. Ships
  faster, no build step, follows the repo's "use built-in renderers" ethos. A
  richer web-component departure board is a clean future enhancement.
- **SL-only**, no provider abstraction (per scoping decision). ResRobot or
  other providers would be separate plugins.
- **Python-side filtering** rather than relying on API filter params — uniform
  behaviour and easier testing.
- `dependencies.packages`: `httpx` (already used by other plugins; confirm it
  needs declaring or is host-provided during implementation).

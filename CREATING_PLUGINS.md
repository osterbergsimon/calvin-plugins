# Creating Plugins for Calvin

A Calvin plugin is **one Python class plus a `plugin.json`**. The class
declares everything about itself in a single `metadata` attribute; the host
discovers the class, generates the settings form, normalizes config, and (for
service plugins) draws the panel with a built-in renderer. You write no
registration hooks, no frontend code, and no config plumbing.

This guide describes **plugin contract 1.0** (`api_version: 1`).

## Quick start

```bash
# Scaffold a new plugin
python scripts/create_plugin.py service my-widget --name "My Widget" --label Server

# Validate it (no imports needed — AST-based)
python scripts/validate_plugins.py my-widget

# Run its tests against the Calvin backend
cd ../calvin/backend
uv run pytest ../../calvin-plugins/my-widget
```

The smallest legal plugin, in full:

```python
"""plugin.py"""
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class HelloPlugin(ServicePlugin):
    metadata = PluginMetadata(
        type_id="hello",
        name="Hello",
        description="Says hello",
        instance_label="Greeting",
        instance_config_schema={
            "who": {"type": "string", "default": "world",
                    "ui": {"component": "input", "validation": {"required": True}}},
        },
        display_schema={
            "kind": "status",
            "item": {"label": "Hello", "value_path": "$.message"},
        },
    )

    async def fetch(self, start_date=None, end_date=None):
        return {"message": f"hello, {self.config['who']}"}
```

```json
{
  "api_version": 1,
  "id": "hello",
  "name": "Hello",
  "version": "1.0.0",
  "type": "service",
  "description": "Says hello"
}
```

That's the entire plugin. Reference implementation: [`mealie/`](mealie/) —
a real service plugin with connection testing, per-instance config, and a
card-grid display.

## How it works

1. **Discovery.** At load (and at install — no restart needed), the host
   imports `plugin.py` and registers every `BasePlugin`-family subclass that
   declares its own `metadata = PluginMetadata(...)` attribute. A subclass
   *without* its own `metadata` is just an implementation detail; a subclass
   *with* one is a second plugin type (see `ical`/`proton` in the Calvin
   built-ins for that pattern).
2. **Instantiation.** Instances are constructed as
   `YourPlugin(plugin_id, name, enabled)` — never override `__init__` with
   config parameters. Then the host calls `await instance.configure(config)`.
3. **Config.** `configure()` normalizes the raw config against your
   `instance_config_schema` (type-driven conversion: `string`/`password` →
   str, `integer` → int, `number` → float, `boolean` → bool) and stores it in
   `self.config`. Read `self.config["key"]`; add small `@property` accessors
   for trimming (see mealie).
4. **Validation.** Before creating or updating an instance the host awaits
   `YourPlugin.validate_config(config)` (an async **classmethod**). The
   default checks that every field with `ui.validation.required` is non-empty.
   Override only for extra rules, and start with
   `normalized = cls.normalize_config(config)`.
5. **Identity.** `instance_identity=["url"]` makes instance ids a stable hash
   of those config values (same server → same instance). Single-instance
   plugins set `supports_multiple_instances=False` (+ optional
   `fixed_instance_id`).
6. **Display.** `display_schema` (and optionally `statusbar_schema`) tell the
   host how to draw your data with a built-in renderer — see below.

## The plugin families

| type | base class | MUST implement | data verb |
|---|---|---|---|
| `service` | `ServicePlugin` | — | `fetch(start_date, end_date)` → payload for the display schema |
| `calendar` | `CalendarPlugin` | `fetch_events(start, end)` | returns `list[CalendarEvent]` |
| `image` | `ImagePlugin` | `get_images`, `get_image`, `get_image_data`, `scan_images` | (+ optional `upload_image`, `delete_image`, `get_thumbnail_path`) |
| `backend` | `BackendPlugin` | — | optional `fetch()` ("check now"), `get_schedule_config`/`run_scheduled_task`, `handle_event`/`get_subscribed_events`, `provide_service` |

Lifecycle (all optional overrides): `initialize()` (connect/validate; runs
after `configure`), `cleanup()` (release resources), `configure()` (react to
config changes — call `await super().configure(config)` first).

Class-level operations (optional classmethods):

- `test_connection(config) -> dict | None` — powers a "Test Connection"
  button; declare a `ui_action` with `type: "test"`. Return
  `{"success": bool, "message": str}`.
- `scan_options(field_key) -> dict | None` — discover options for a config
  field (e.g. enumerate devices). Return `{"options": [{"value", "label"}]}`.

## Display schemas: panels without frontend code

A service plugin returns a JSON payload from `fetch()` and declares how to
draw it. Values bind via `*_path` JSON paths (`$.a.b`) resolved against the
payload; literal keys (`label`) work too, and `value_format` applies
formatting.

Panel kinds (`display_schema.kind`):

| kind | what it draws | key schema fields |
|---|---|---|
| `status` | readouts (label over value) | `layout` (tile/row/list), `data_path`, `item: {icon,label,value,unit,status}` |
| `metric-dashboard` | grid of big metric tiles | `data_path`, `layout.columns`, `tile: {...}` |
| `card-grid` | cards with titled item lists | `data_path`, `layout.columns`, `card: {title_path, items_path, item}` |
| `item-list` | timestamped feed/log | `data_path`, `item: {timestamp,label,value}` |
| `weather-forecast` | current conditions + daily forecast | `current_path`, `forecast_path`, `current: {...}`, `forecast: {...}`, `units` |
| `image-with-caption` | full-bleed image + caption | `image_url_path`, `title`, `caption`, `metadata` |
| `iframe` | embedded web page | `url_path` |
| `web-component` | your own custom element (escape hatch) | `element`, `module`, `stylesheet?` |

- `status` items take `status: "ok" | "warn" | "error"` — `ok` renders
  monochrome; `warn`/`error` light an indicator lamp and tint the value.
  Color on the wall means "needs attention"; don't mark everything.
- `poll_interval_ms` on the schema makes the frontend re-fetch periodically.
- `statusbar_schema` puts a compact item in the clock bar. Its namespace is
  intentionally small: **`status` only** — a statusbar item is a strip, not a
  panel.
- Kind lists are enforced: the backend rejects unknown kinds at load, and a
  kind-sync test keeps backend and frontend lists identical.

### The web-component escape hatch

If no built-in renderer fits, ship a **prebuilt** ES module defining a custom
element (no build step on the host, no `.vue` sources):

```python
display_schema={"kind": "web-component", "element": "calvin-my-widget", "module": "dist.js"}
```

Put `frontend/dist.js` in your plugin (list it in `files.include`); it's
served at `/api/plugins/{id}/static/dist.js`. The host sets the element's
`.data` property with each `fetch()` payload — implement `set data(value)`
and re-render. Style with the shell's CSS custom properties (`--ink`,
`--ink-2`, `--ink-3`, `--bg-1`, `--bg-2`, `--line`, `--font-ui`,
`--font-data`, `--ok`/`--warn`/`--err`) so your component follows Calvin's
themes; custom properties inherit into shadow DOM. See
[`chromecast/`](chromecast/).

## plugin.json

```json
{
  "api_version": 1,
  "id": "my_widget",
  "name": "My Widget",
  "version": "1.0.0",
  "type": "service",
  "description": "One-line description",
  "author": "You",
  "license": "MIT",
  "dependencies": {"packages": ["some-lib>=2.0"]},
  "files": {"include": ["plugin.py", "plugin.json"], "exclude": ["*.md", "tests/**", "__pycache__/**"]},
  "requirements": {"config_required": true}
}
```

- `api_version` (int, **required**) — the one contract version signal. The
  installer rejects manifests that omit it or declare a version the host
  doesn't support. Current: `1`.
- `dependencies.packages` — pip requirement strings, installed into the
  host's venv at plugin install (a failed install rolls the plugin back).
  This is the only dependency mechanism.
- `id` must equal `metadata.type_id`; `type` must match the family base
  class. `scripts/validate_plugins.py` checks both.
- Retired keys (rejected): `format_version`, `protocol_version`,
  `python_dependencies`, `dependencies.python`, `dependencies.calvin`.

## Rules of the road

- **Self-contained.** Import only from `app.*` and third-party libraries —
  never from another plugin.
- **No module-level hooks.** `register_plugin_types`,
  `create_plugin_instance`, `handle_plugin_config_update`, `@hookimpl` are
  all retired.
- **Config is declared once** — in `instance_config_schema`. Don't unpack it
  in `__init__`, don't keep parallel field lists.
- **`fetch()` returns data, not markup.** Shape your payload for the display
  schema (see `mealie._shape_for_display` for the pattern) and let the
  renderer draw it.
- **Copy is interface.** Error strings in payloads (`{"error": "..."}`)
  surface on the wall — write direction ("Authentication failed — check the
  API token"), not stack traces.

## Testing

Every plugin ships a `test_<id>.py`, run from the Calvin backend so `app.*`
resolves:

```bash
cd ../calvin/backend
uv run pytest ../../calvin-plugins/my-widget
```

Follow [`mealie/test_mealie.py`](mealie/test_mealie.py): assert the contract
shape (loader discovery, no module hooks, metadata fields), config
normalization/validation, and your payload shaping against the display
schema's paths. `pytest.ini` at the repo root enables `asyncio_mode=auto`, so
plain `async def` tests work.

## Publishing to this repository

1. `python scripts/validate_plugins.py <your-plugin>` passes.
2. Tests pass against the backend.
3. `python scripts/rebuild-manifest.py` updates `plugins.json`.
4. Open a PR. The repo's contract tests
   (`calvin/backend/tests/integration/test_calvin_plugins_contracts.py`)
   validate every listed plugin against the host on CI.

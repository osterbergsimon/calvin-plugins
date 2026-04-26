# Creating Plugins for Calvin

This guide provides everything you need to create plugins for the Calvin dashboard system.

## Quick Start

Use the scaffold script to generate a new plugin in seconds:

```bash
python scripts/create_plugin.py <type> <id> [options]
```

**Types:** `service`, `image`, `calendar`, `backend`

**Examples:**
```bash
python scripts/create_plugin.py service yr-pro --name "Yr.no Pro" --label Location
python scripts/create_plugin.py image flickr --name Flickr --description "Photos from Flickr"
python scripts/create_plugin.py calendar my-cal --name "My Calendar"
python scripts/create_plugin.py backend resize-worker --single
```

**Options:**
- `--name NAME` — Human-readable name (default: title-cased id)
- `--description DESC` — Short description
- `--single` — Single-instance plugin (default: multi-instance)
- `--label LABEL` — Instance label shown in UI (e.g. `Location`, `Device`, `Gallery`)
- `--author AUTHOR` — Author name
- `--no-tests` — Skip generating test file

The script creates `<id>/plugin.json`, `<id>/plugin.py`, and `<id>/test_<id>.py`, then automatically rebuilds `plugins.json`.

After scaffolding, edit `plugin.py` to fill in `instance_config_schema` and your business logic.

---

1. **Read the format specification**: [PLUGIN_PACKAGE_FORMAT.md](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md)
2. **Review the development guide**: [PLUGIN_DEVELOPMENT.md](../calvin/docs/PLUGIN_DEVELOPMENT.md)
3. **Look at examples**: Check existing plugins in this repository
4. **Create your plugin**: Use the scaffold script above or follow the structure below

## Plugin Structure

Every plugin must follow this structure:

```
my-plugin/
├── plugin.json       # REQUIRED: Plugin manifest
├── plugin.py        # REQUIRED: Plugin implementation
├── frontend/        # OPTIONAL: Frontend components
│   └── Component.vue
└── assets/          # OPTIONAL: Static assets
    └── icon.png
```

## Step-by-Step Guide

### Step 1: Create Plugin Directory

Create a directory for your plugin:

```bash
mkdir my-plugin
cd my-plugin
```

### Step 2: Create Plugin Manifest (`plugin.json`)

Create `plugin.json` with required fields:

```json
{
  "format_version": "1.0.0",
  "protocol_version": 1,
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "service",
  "description": "A description of what this plugin does",
  "author": "Your Name",
  "license": "MIT"
}
```

**Required Fields:**
- `id`: Unique plugin identifier (lowercase, underscores, hyphens)
- `name`: Human-readable plugin name
- `version`: Plugin version (semantic versioning)
- `type`: Plugin type (`calendar`, `image`, or `service`)

**Optional Fields:**
- `format_version`: Plugin manifest format version (defaults to `1.0.0`)
- `protocol_version`: Calvin plugin protocol version (defaults to `1`)
- `description`: Plugin description
- `author`: Plugin author
- `license`: License type
- `homepage`, `repository`, `bugs`: URLs
- `keywords`: Array of tags
- `dependencies`: Python packages, system requirements
- `files`: File inclusion/exclusion rules
- `requirements`: Installation requirements

See the [complete manifest schema](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#plugin-manifest-schema-pluginjson) for all available fields.

### Step 3: Create Plugin Implementation (`plugin.py`)

Create `plugin.py` with your plugin implementation. Prefer the shared SDK helpers in `app.plugins.sdk.*` and use the generic instance manager for lifecycle handling. The scaffold script now generates SDK-first templates for all supported plugin families.

SDK modules by plugin type:

- `service` -> `app.plugins.sdk.service`
- `image` -> `app.plugins.sdk.image`
- `calendar` -> `app.plugins.sdk.calendar`
- `backend` -> `app.plugins.sdk.backend`

Service plugin example:

```python
"""My custom plugin."""

from typing import Any

from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.sdk.service import (
    ServiceConfigField,
    build_service_manager_config,
    build_service_plugin_metadata,
    create_service_plugin_instance,
)
from app.plugins.utils.instance_manager import handle_plugin_config_update_generic


SERVICE_FIELDS = (
    ServiceConfigField("api_key", default="", converter=str),
)


class MyServicePlugin(ServicePlugin):
    """My custom service plugin."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return build_service_plugin_metadata(
            type_id="my_plugin",
            name="My Plugin",
            description="A custom plugin",
            plugin_class=cls,
            supports_multiple_instances=True,
            common_config_schema={},
            instance_config_schema={
                # Instance-specific settings
                "api_key": {
                    "type": "password",
                    "description": "API key",
                    "ui": {
                        "component": "password",
                        "validation": {"required": True},
                    },
                },
            },
            display_schema={
                "type": "api",
                "api_endpoint": "/api/plugins/{service_id}/data",
                "method": "GET",
            },
        )

    def __init__(self, plugin_id: str, name: str, api_key: str = "", enabled: bool = True):
        """Initialize plugin."""
        super().__init__(plugin_id, name, enabled)
        self.api_key = api_key

    async def initialize(self) -> None:
        """Initialize the plugin."""
        pass

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        pass

    async def get_content(self) -> dict[str, Any]:
        """Get service content for display."""
        return {
            "type": "api",
            "url": f"/api/plugins/{self.plugin_id}/data",
        }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key", "")).strip())

    async def configure(self, config: dict[str, Any]) -> None:
        if "api_key" in config:
            self.api_key = str(config["api_key"]).strip()


# Register plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register plugin type."""
    return [MyServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> MyServicePlugin | None:
    return create_service_plugin_instance(
        MyServicePlugin,
        expected_type_id="my_plugin",
        plugin_id=plugin_id,
        type_id=type_id,
        name=name,
        config=config,
        fields=SERVICE_FIELDS,
    )


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle plugin configuration updates using generic instance manager."""
    if type_id != "my_plugin":
        return None

    def generate_instance_id(c: dict[str, Any], _: str) -> str:
        """Generate unique instance ID based on config."""
        unique_str = f"my_plugin_{c.get('api_key', '')}"
        return f"my-plugin-{abs(hash(unique_str)) % 100000}"

    manager_config = build_service_manager_config(
        type_id="my_plugin",
        fields=SERVICE_FIELDS,
        validate_config=lambda c: bool(str(c.get("api_key", "")).strip()),
        generate_instance_id=generate_instance_id,
    )

    return await handle_plugin_config_update_generic(
        type_id=type_id,
        config=config,
        enabled=enabled,
        db_type=db_type,
        session=session,
        manager_config=manager_config,
    )
```

**Key points:**

1. **Use the family SDK** for your plugin type:
   - `service`: `ServiceConfigField`, `build_service_plugin_metadata`, `create_service_plugin_instance`, `build_service_manager_config`
   - `image`: `ImageConfigField`, `build_image_plugin_metadata`, `create_image_plugin_instance`, `build_image_manager_config`
   - `calendar`: `CalendarConfigField`, `build_calendar_plugin_metadata`, `create_calendar_plugin_instance`, `build_calendar_manager_config`
   - `backend`: `BackendConfigField`, `build_backend_plugin_metadata`, `create_backend_plugin_instance`, `build_backend_manager_config`
2. **Declare `supports_multiple_instances`** in metadata (`True` for multi-instance, `False` for single-instance)
3. **Use `instance_config_schema`** for instance-specific settings and `common_config_schema` for plugin-type-level settings (rare)
4. **Use `handle_plugin_config_update_generic`** instead of manually managing instance creation or updates
5. **Provide `generate_instance_id`** for multi-instance plugins when the default hash-based ID is not stable enough for your domain

The generated scaffold already wires the correct helper family for each plugin type. In most cases you only need to:

1. Fill in the config field tuple (`SERVICE_FIELDS`, `IMAGE_FIELDS`, `CALENDAR_FIELDS`, or `BACKEND_FIELDS`)
2. Define `instance_config_schema`
3. Add your plugin's runtime methods
4. Tighten `validate_config()` where your plugin needs stronger checks

### Step 4: Add Frontend Components (Optional)

Prefer schema-driven host renderers when they fit. If your plugin needs a custom web component, keep the source in `frontend/src/index.js` and commit the generated `frontend/dist.js` too:

```
my-plugin/
└── frontend/
    ├── src/
    │   └── index.js
    └── dist.js
```

Build a plugin frontend from the repo root:

```bash
scripts/build-plugin.sh my-plugin
```

CI runs the same build and fails if `frontend/dist.js` is not in sync with the source. Plugin packages should include `frontend/dist.js` so Calvin users do not need Node installed.

### Step 5: Add Dependencies (If Needed)

If your plugin requires Python packages, add them to `plugin.json`:

```json
{
  "dependencies": {
    "python": ">=3.10",
    "packages": {
      "requests": ">=2.28.0",
      "pydantic": "^2.0.0"
    }
  }
}
```

### Step 6: Test Your Plugin

#### Writing Tests

Create a test file (e.g., `test_my_plugin.py`) in your plugin directory:

```python
"""Tests for My Plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/my-plugin/test_my_plugin.py
"""

import pytest

# Import your plugin class
from pathlib import Path
import importlib.util

plugin_path = Path(__file__).parent / "plugin.py"
spec = importlib.util.spec_from_file_location("my_plugin", plugin_path)
my_plugin_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(my_plugin_module)
MyPlugin = my_plugin_module.MyPlugin


@pytest.fixture
def my_plugin():
    """Create a plugin instance for testing."""
    return MyPlugin(
        plugin_id="test-instance",
        name="Test Plugin",
        api_key="test-key",
        enabled=True,
    )


class TestMyPlugin:
    """Tests for MyPlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = MyPlugin.get_plugin_metadata()
        assert metadata["type_id"] == "my_plugin"
        assert metadata["name"] == "My Plugin"

    def test_init(self, my_plugin):
        """Test plugin initialization."""
        assert my_plugin.plugin_id == "test-instance"
        assert my_plugin.api_key == "test-key"
        assert my_plugin.enabled is True

    @pytest.mark.asyncio
    async def test_validate_config(self, my_plugin):
        """Test config validation."""
        assert await my_plugin.validate_config({"api_key": "valid"}) is True
        assert await my_plugin.validate_config({"api_key": ""}) is False

    @pytest.mark.asyncio
    async def test_configure(self, my_plugin):
        """Test plugin configuration."""
        await my_plugin.configure({"api_key": "new-key"})
        assert my_plugin.api_key == "new-key"


@pytest.mark.asyncio
class TestMyPluginHooks:
    """Tests for plugin hooks."""

    async def test_create_plugin_instance(self):
        """Test create_plugin_instance hook."""
        # Test the hook implementation
        pass

    async def test_handle_plugin_config_update(self):
        """Test handle_plugin_config_update hook.
        
        Note: This test is skipped when run from the plugin directory because it requires
        the `test_db` fixture which is only available in the backend test suite.
        
        To test handle_plugin_config_update hooks, run the backend test suite from the
        backend directory:
            cd backend
            pytest tests/unit/test_plugin_hooks.py
        """
        pytest.skip("Requires backend test fixtures (test_db). "
                   "Run from backend directory: "
                   "cd backend && pytest tests/unit/test_plugin_hooks.py")
```

#### Testing Plugin Class Methods

You can test most plugin functionality (metadata, initialization, validation, configuration) by running tests from the plugin directory:

```bash
cd calvin-plugins/my-plugin
pytest test_my_plugin.py -v
```

Or from the backend directory:

```bash
cd backend
pytest ../calvin-plugins/my-plugin/test_my_plugin.py -v
```

#### Testing `handle_plugin_config_update` Hook

The `handle_plugin_config_update` hook requires database access and backend fixtures, so it cannot be tested directly from the plugin directory. Instead:

1. **Write tests in your plugin test file** that skip when backend fixtures aren't available (as shown above).

2. **Run hook tests from the backend directory**:
   ```bash
   cd backend
   pytest tests/unit/test_plugin_hooks.py -v
   ```

   This test suite:
   - Loads plugin hooks directly from plugin files
   - Tests that hooks correctly call `handle_plugin_config_update_generic`
   - Verifies database entries are created correctly
   - Uses the `test_db` fixture for proper database isolation

3. **Or run the comprehensive generic handler tests**:
   ```bash
   cd backend
   pytest tests/unit/test_plugin_instance_manager.py -v
   ```

   These tests verify that `handle_plugin_config_update_generic` (which all plugin hooks now use) works correctly for both single-instance and multi-instance plugins.

#### What to Test

- **Plugin metadata**: Verify `get_plugin_metadata()` returns correct values
- **Initialization**: Test `__init__` and `initialize()` methods
- **Configuration validation**: Test `validate_config()` with valid and invalid inputs
- **Configuration updates**: Test `configure()` method updates plugin state correctly
- **Plugin-specific methods**: Test all methods required by your plugin type
- **Hook integration**: Test that `handle_plugin_config_update` correctly uses the generic instance manager (from backend test suite)

#### Running Tests

**From plugin directory** (tests plugin class methods):
```bash
cd calvin-plugins/my-plugin
pytest test_my_plugin.py -v
```

**From backend directory** (tests hooks and integration):
```bash
cd backend
# Test all plugin hooks
pytest tests/unit/test_plugin_hooks.py -v

# Test specific plugin hook
pytest tests/unit/test_plugin_hooks.py::TestPluginHooks::test_my_plugin_handle_plugin_config_update -v

# Test plugin class methods from plugin directory
pytest ../calvin-plugins/my-plugin/test_my_plugin.py -v
```

#### Manual Testing

1. Package your plugin as a zip file
2. Install it via the Calvin UI or API
3. Test all functionality through the UI
4. Verify configuration works correctly
5. Test instance creation/updates/deletion

### Step 7: Add to Repository

If adding to this repository:

1. Create your plugin directory
2. Add `plugin.json` and `plugin.py`
3. Update `plugins.json` to include your plugin:

```json
{
  "version": "1.0.0",
  "plugins": [
    {
      "id": "my_plugin",
      "name": "My Plugin",
      "path": "my-plugin",
      "version": "1.0.0",
      "type": "service",
      "description": "A description of what this plugin does"
    }
  ]
}
```

4. Submit a pull request

## Plugin Types

### Calendar Plugins

Provide calendar events from external sources.

**Preferred SDK:** `app.plugins.sdk.calendar`

**Required Methods:**
- `fetch_events(start_date, end_date)` - Fetch events for a date range
- `validate_config(config)` - Validate configuration

**Example Use Cases:**
- Google Calendar integration
- iCal/ICS feed parsing
- CalDAV servers

### Image Plugins

Provide images from various sources.

**Preferred SDK:** `app.plugins.sdk.image`

**Required Methods:**
- `get_images()` - Get all available images
- `get_image(image_id)` - Get image metadata by ID
- `get_image_data(image_id)` - Get image file data
- `scan_images()` - Scan for new/updated images

**Example Use Cases:**
- Local filesystem image directory
- Unsplash API
- Cloud storage (S3, etc.)

### Service Plugins

Display web services, APIs, or custom content.

**Preferred SDK:** `app.plugins.sdk.service`

**Required Methods:**
- `get_content()` - Get service content for display
- `validate_config(config)` - Validate configuration

**Example Use Cases:**
- Iframe embeds
- API-driven displays
- Webhook receivers

### Backend Plugins

Handle background work, events, or non-visual integrations.

**Preferred SDK:** `app.plugins.sdk.backend`

**Required Methods:**
- `validate_config(config)` - Validate configuration

**Common Patterns:**
- task runners
- mailbox or webhook processors
- media processing jobs

## Best Practices

1. **Use semantic versioning** for plugin versions
2. **Use config utilities** (`extract_config_value`, `to_str`, `to_int`, etc.) for type-safe configuration extraction
3. **Use generic instance manager** (`handle_plugin_config_update_generic`) instead of manually managing instances
4. **Declare `supports_multiple_instances`** in metadata (`True` for multi-instance, `False` for single-instance)
5. **Use `instance_config_schema`** for instance-specific settings and `common_config_schema` only for plugin-type-level settings (rare)
6. **Validate configuration** in `validate_config()` method using config utilities
7. **Handle errors gracefully** with proper error messages
8. **Document dependencies** in `plugin.json`
9. **Test plugins** before distribution
10. **Follow naming conventions**: lowercase with underscores for IDs
11. **Include format_version and protocol_version** in `plugin.json` for future compatibility
12. **Specify dependencies** explicitly to avoid runtime errors
13. **Exclude unnecessary files** to reduce plugin size
14. **Document permissions** required by your plugin

## Resources

- **[Plugin Package Format](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md)** - Complete format specification
- **[Plugin Development Guide](../calvin/docs/PLUGIN_DEVELOPMENT.md)** - Detailed development guide
- **[Plugin Installation Guide](../calvin/docs/PLUGIN_INSTALLATION.md)** - Installation instructions
- **[Example Plugins](../calvin/backend/app/plugins/)** - Built-in plugin examples

## Format Versioning

The plugin package format is versioned to allow for future changes while maintaining backward compatibility.

**Current Format Version: `1.0.0`**

Always specify `format_version` and `protocol_version` in your `plugin.json`:

```json
{
  "format_version": "1.0.0",
  "protocol_version": 1,
  ...
}
```

If not specified, `format_version` defaults to `1.0.0` and `protocol_version` defaults to `1`. Future versions will be documented in the [format specification](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#format-versioning).

## Getting Help

- Check existing plugins in this repository for examples
- Review the [development guide](../calvin/docs/PLUGIN_DEVELOPMENT.md)
- Look at built-in plugins in `calvin/backend/app/plugins/`
- Open an issue if you need help


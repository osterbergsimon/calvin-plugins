# Creating Plugins for Calvin

This guide provides everything you need to create plugins for the Calvin dashboard system.

## Quick Start

1. **Read the format specification**: [PLUGIN_PACKAGE_FORMAT.md](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md)
2. **Review the development guide**: [PLUGIN_DEVELOPMENT.md](../calvin/docs/PLUGIN_DEVELOPMENT.md)
3. **Look at examples**: Check existing plugins in this repository
4. **Create your plugin**: Follow the structure below

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

Create `plugin.py` with your plugin implementation. **Use the generic instance manager and config utilities** to simplify your code:

```python
"""My custom plugin."""

import hashlib
from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_str
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)


class MyServicePlugin(ServicePlugin):
    """My custom service plugin."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "my_plugin",
            "plugin_type": PluginType.SERVICE,
            "name": "My Plugin",
            "description": "A custom plugin",
            "version": "1.0.0",
            "supports_multiple_instances": True,  # Set to False for single-instance plugins
            "common_config_schema": {},  # Plugin-type-level settings (rarely used)
            "instance_config_schema": {
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
            "display_schema": {
                "type": "api",
                "api_endpoint": "/api/web-services/{service_id}/data",
                "method": "GET",
            },
            "plugin_class": cls,
        }

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
            "url": f"/api/web-services/{self.plugin_id}/data",
        }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate plugin configuration using config utilities."""
        api_key = extract_config_value(config, "api_key", to_str, "")
        return bool(api_key)

    async def configure(self, config: dict[str, Any]) -> None:
        """Update plugin configuration using config utilities."""
        self.api_key = extract_config_value(config, "api_key", to_str, self.api_key)


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
    """Create plugin instance using config utilities."""
    if type_id != "my_plugin":
        return None

    enabled = config.get("enabled", False)
    # Use extract_config_value for type-safe config extraction
    api_key = extract_config_value(config, "api_key", to_str, "")

    return MyServicePlugin(
        plugin_id=plugin_id,
        name=name,
        api_key=api_key,
        enabled=enabled,
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

    # Define how to generate instance IDs (optional for multi-instance plugins)
    def generate_instance_id(c: dict[str, Any]) -> str:
        """Generate unique instance ID based on config."""
        # For multi-instance plugins, create a hash from unique config values
        # For single-instance plugins, return a fixed ID like "my-plugin-instance"
        unique_str = f"my_plugin_{c.get('api_key', '')}"
        return f"my-plugin-{hashlib.md5(unique_str.encode()).hexdigest()[:8]}"

    # Configure the generic instance manager
    manager_config = InstanceManagerConfig(
        type_id="my_plugin",
        plugin_class=MyServicePlugin,
        validate_config=MyServicePlugin(None, "").validate_config,
        normalize_config=lambda c: c,  # Add normalization if needed
        generate_instance_id=generate_instance_id,  # Optional for multi-instance
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

1. **Use config utilities** (`extract_config_value`, `to_str`, `to_int`, `to_bool`, `to_float`) for type-safe configuration extraction
2. **Declare `supports_multiple_instances`** in metadata (`True` for multi-instance, `False` for single-instance)
3. **Use `instance_config_schema`** for instance-specific settings and `common_config_schema` for plugin-type-level settings (rare)
4. **Use `handle_plugin_config_update_generic`** instead of manually managing instance creation/updates
5. **Provide `generate_instance_id`** function for multi-instance plugins (optional - defaults to hash-based ID)

### Step 4: Add Frontend Components (Optional)

If your plugin needs custom frontend components, create a `frontend/` directory:

```
my-plugin/
└── frontend/
    └── MyComponent.vue
```

The component will be available at `{plugin_id}/MyComponent.vue` in the frontend.

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

**Required Methods:**
- `fetch_events(start_date, end_date)` - Fetch events for a date range
- `validate_config(config)` - Validate configuration

**Example Use Cases:**
- Google Calendar integration
- iCal/ICS feed parsing
- CalDAV servers

### Image Plugins

Provide images from various sources.

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

**Required Methods:**
- `get_content()` - Get service content for display
- `validate_config(config)` - Validate configuration

**Example Use Cases:**
- Iframe embeds
- API-driven displays
- Webhook receivers

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
11. **Include format_version** in `plugin.json` for future compatibility
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

Always specify `format_version` in your `plugin.json`:

```json
{
  "format_version": "1.0.0",
  ...
}
```

If not specified, it defaults to `1.0.0`. Future format versions will be documented in the [format specification](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#format-versioning).

## Getting Help

- Check existing plugins in this repository for examples
- Review the [development guide](../calvin/docs/PLUGIN_DEVELOPMENT.md)
- Look at built-in plugins in `calvin/backend/app/plugins/`
- Open an issue if you need help


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

Create `plugin.py` with your plugin implementation:

```python
"""My custom plugin."""

from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin


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
            "common_config_schema": {
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

    def __init__(self, plugin_id: str, name: str, api_key: str, enabled: bool = True):
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
        """Validate plugin configuration."""
        return "api_key" in config and bool(config["api_key"])


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
    """Create plugin instance."""
    if type_id != "my_plugin":
        return None

    enabled = config.get("enabled", False)
    api_key = config.get("api_key", "")

    return MyServicePlugin(
        plugin_id=plugin_id,
        name=name,
        api_key=api_key,
        enabled=enabled,
    )
```

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

1. Package your plugin as a zip file
2. Install it via the Calvin UI or API
3. Test all functionality
4. Verify configuration works correctly

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
2. **Validate configuration** in `validate_config()` method
3. **Handle errors gracefully** with proper error messages
4. **Document dependencies** in `plugin.json`
5. **Test plugins** before distribution
6. **Follow naming conventions**: lowercase with underscores for IDs
7. **Include format_version** in `plugin.json` for future compatibility
8. **Specify dependencies** explicitly to avoid runtime errors
9. **Exclude unnecessary files** to reduce plugin size
10. **Document permissions** required by your plugin

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


# Calvin Plugins Repository

This repository contains plugins for the Calvin dashboard system.

## 📚 Documentation

**All plugins in this repository must follow the official Calvin Plugin Package Format.**

### Essential Reading

1. **[Creating Plugins Guide](./CREATING_PLUGINS.md)** - Complete guide to creating plugins ⭐ **Start here!**
2. **[Plugin Package Format](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md)** - Official format specification
3. **[Plugin Development Guide](../calvin/docs/PLUGIN_DEVELOPMENT.md)** - Detailed development guide
4. **[Plugin Installation Guide](../calvin/docs/PLUGIN_INSTALLATION.md)** - How to install plugins

### Quick Links

- **Format Version**: Currently `1.0.0` (see [format versioning](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#format-versioning))
- **Example Plugins**: See `test-plugin/` in this repository
- **Built-in Examples**: See `calvin/backend/app/plugins/`

## Quick Reference

### Repository Structure

```
calvin-plugins/
├── plugins.json          # Repository manifest (lists all plugins)
├── plugin1/              # Plugin directory
│   ├── plugin.json       # Plugin manifest (required)
│   ├── plugin.py         # Plugin implementation (required)
│   ├── frontend/         # Frontend components (optional)
│   └── assets/           # Static assets (optional)
└── plugin2/
    ├── plugin.json
    └── plugin.py
```

### Required Files

Each plugin **must** have:
- `plugin.json` - Plugin manifest with metadata, dependencies, and requirements
- `plugin.py` - Plugin implementation

### Plugin Manifest (`plugin.json`)

Minimal required fields:

```json
{
  "format_version": "1.0.0",
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "service"
}
```

**Note**: While `format_version` is optional (defaults to `1.0.0`), it's recommended to include it explicitly for future compatibility.

See the [complete manifest schema](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#plugin-manifest-schema-pluginjson) for all available fields including:
- Dependencies (Python packages, system requirements)
- File inclusion/exclusion rules
- Installation requirements
- Additional metadata

### Repository Manifest (`plugins.json`)

If this repository contains multiple plugins, include a `plugins.json` at the root:

```json
{
  "version": "1.0.0",
  "plugins": [
    {
      "id": "plugin1",
      "name": "Plugin 1",
      "path": "plugin1",
      "version": "1.0.0",
      "type": "service",
      "description": "Plugin description"
    }
  ]
}
```

## Creating a New Plugin

**See [CREATING_PLUGINS.md](./CREATING_PLUGINS.md) for the complete step-by-step guide.**

Quick checklist:
1. ✅ Read [CREATING_PLUGINS.md](./CREATING_PLUGINS.md)
2. ✅ Create plugin directory (e.g., `my-plugin/`)
3. ✅ Add `plugin.json` with required fields (include `format_version: "1.0.0"`)
4. ✅ Add `plugin.py` with plugin implementation
5. ✅ Optionally add `frontend/` and `assets/` directories
6. ✅ Test your plugin locally
7. ✅ Update `plugins.json` to include your plugin
8. ✅ Submit a pull request

## Plugin Format Version

**Current Format Version: `1.0.0`**

All plugins should specify `format_version: "1.0.0"` in their `plugin.json` manifest. This ensures compatibility as the format evolves.

See [Format Versioning](../calvin/docs/PLUGIN_PACKAGE_FORMAT.md#format-versioning) for details.

## Testing

Plugins in this repository are used for testing the Calvin plugin installation system. See:
- `backend/tests/unit/test_plugin_installer_github.py`
- `backend/tests/integration/test_api_plugins_github.py`

## License

See [LICENSE](./LICENSE) file for license information.


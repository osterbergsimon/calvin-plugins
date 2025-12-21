#!/usr/bin/env python3
"""
Rebuild plugins.json manifest file.

Scans the repository for plugins and themes, validates them,
and generates/updates the plugins.json manifest file.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import validation functions
REPO_ROOT = Path(__file__).parent.parent


def validate_plugin_directory(plugin_dir: Path) -> dict:
    """Validate a plugin directory and return its manifest."""
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        raise ValueError(f"plugin.json not found in {plugin_dir}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Required fields
    required_fields = ["id", "name", "version", "type"]
    for field in required_fields:
        if field not in manifest:
            raise ValueError(f"Missing required field in plugin.json: {field}")

    # Check for plugin.py
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.exists():
        raise ValueError("plugin.py not found in plugin package")

    return manifest


def validate_theme_directory(theme_dir: Path) -> dict:
    """Validate a theme directory and return its manifest."""
    manifest_path = theme_dir / "theme.json"
    if not manifest_path.exists():
        raise ValueError(f"theme.json not found in {theme_dir}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Required fields
    required_fields = ["id", "name", "version", "variables"]
    for field in required_fields:
        if field not in manifest:
            raise ValueError(f"Missing required field in theme.json: {field}")

    return manifest


def rebuild_manifest():
    """Rebuild the plugins.json manifest file."""
    plugins = []
    themes = []
    errors = []

    # Scan repository for plugins and themes
    for item in REPO_ROOT.iterdir():
        if not item.is_dir():
            continue

        # Skip common non-plugin/theme directories
        if item.name in [
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "scripts",
            ".github",
        ]:
            continue

        # Check for plugin
        plugin_json = item / "plugin.json"
        plugin_py = item / "plugin.py"
        if plugin_json.exists() and plugin_py.exists():
            try:
                manifest = validate_plugin_directory(item)
                plugins.append(
                    {
                        "id": manifest["id"],
                        "name": manifest.get("name", manifest["id"]),
                        "path": item.name,
                        "description": manifest.get("description", ""),
                        "version": manifest.get("version", "1.0.0"),
                        "type": manifest.get("type", "service"),
                    }
                )
            except Exception as e:
                errors.append(f"Plugin {item.name}: {e}")

        # Check for theme
        theme_json = item / "theme.json"
        if theme_json.exists():
            try:
                manifest = validate_theme_directory(item)
                themes.append(
                    {
                        "id": manifest["id"],
                        "name": manifest.get("name", manifest["id"]),
                        "path": item.name,
                        "description": manifest.get("description", ""),
                        "version": manifest.get("version", "1.0.0"),
                    }
                )
            except Exception as e:
                errors.append(f"Theme {item.name}: {e}")

    # Sort by name for consistency
    plugins.sort(key=lambda x: x["name"].lower())
    themes.sort(key=lambda x: x["name"].lower())

    # Build manifest
    manifest = {
        "version": "1.0.0",
        "plugins": plugins,
    }

    # Only include themes array if there are themes
    if themes:
        manifest["themes"] = themes

    # Write manifest
    manifest_path = REPO_ROOT / "plugins.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    # Print results
    print("Rebuilt plugins.json")
    print(f"  - Found {len(plugins)} plugin(s)")
    if themes:
        print(f"  - Found {len(themes)} theme(s)")

    if errors:
        print("\nWarnings/Errors encountered:")
        for error in errors:
            print(f"  - {error}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(rebuild_manifest())


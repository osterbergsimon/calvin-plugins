# Test Plugin

A basic test plugin for plugin installation testing in the Calvin dashboard.

## Purpose

This plugin is designed to be used in automated tests to verify that the plugin installation system works correctly. It provides a minimal but complete plugin implementation that can be installed and validated.

## Structure

```
test-plugin/
├── plugin.json      # Plugin manifest
├── plugin.py        # Plugin implementation
└── README.md        # This file
```

## Plugin Details

- **ID**: `test_plugin`
- **Name**: Test Plugin
- **Type**: Service
- **Version**: 1.0.0

## Features

- Minimal service plugin implementation
- Configurable message field
- Valid plugin structure for testing installation flows
- Compatible with plugin installation tests

## Usage in Tests

This plugin is used in:
- `backend/tests/unit/test_plugin_installer_github.py` - Unit tests for plugin installation
- `backend/tests/integration/test_api_plugins_github.py` - Integration tests for GitHub plugin installation

## Installation

This plugin can be installed via:
1. Direct repository installation (from calvin-plugins repo)
2. GitHub repository installation
3. Zip file installation

See the main Calvin documentation for plugin installation instructions.


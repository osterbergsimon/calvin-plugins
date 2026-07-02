"""Tests for the Chromecast plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/chromecast/test_chromecast.py

pychromecast is deliberately NOT required: the plugin module guards its
import, and these tests mock pychromecast at the module boundary.
"""

import importlib.util
import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("chromecast_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chromecast_module = _load_plugin_module()
ChromecastServicePlugin = chromecast_module.ChromecastServicePlugin


def _fake_cast(name="Living Room", app="Spotify", player_state="PLAYING"):
    cast = MagicMock()
    cast.cast_info.friendly_name = name
    cast.app_display_name = app
    cast.app_id = "APP_ID"
    media = MagicMock()
    media.player_state = player_state
    media.title = "Song"
    media.artist = "Artist"
    media.album_name = "Album"
    media.images = [MagicMock(url="http://art.example/cover.jpg")]
    media.duration = 200
    media.current_time = 60
    cast.media_controller.status = media
    return cast


@pytest.fixture
async def plugin():
    """A configured plugin instance."""
    instance = ChromecastServicePlugin(plugin_id="chromecast-test", name="Chromecast", enabled=True)
    await instance.configure({"device_name": " Living Room ", "discovery_timeout": "10"})
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_chromecast")
        module.ChromecastServicePlugin = ChromecastServicePlugin
        assert loader.register_module(module) == ["chromecast"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(chromecast_module, hook), hook

    def test_metadata(self):
        md = ChromecastServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "chromecast"
        assert md.supports_multiple_instances is True
        assert md.display_schema["kind"] == "web-component"
        assert md.display_schema["element"] == "calvin-chromecast-now-playing"
        assert md.display_schema["module"] == "dist.js"
        assert md.display_schema["panel_variant"] == "media"

    def test_is_service_plugin(self):
        assert issubclass(ChromecastServicePlugin, ServicePlugin)

    def test_ships_web_component_artifact(self):
        """dist.js is the shipped frontend artifact and the manifest includes it."""
        plugin_dir = Path(__file__).parent
        assert (plugin_dir / "frontend" / "dist.js").exists()
        manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["api_version"] == 1
        assert "frontend/dist.js" in manifest["files"]["include"]
        assert manifest["dependencies"]["packages"] == ["pychromecast>=14.0"]


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.device_name == "Living Room"  # whitespace trimmed
        assert plugin.discovery_timeout == 10  # "10" converted by schema type

    async def test_defaults_apply(self):
        instance = ChromecastServicePlugin("cc-x", "Chromecast")
        await instance.configure({})
        assert instance.device_name == ""
        assert instance.discovery_timeout == 5

    async def test_validate_config_requires_dependency(self):
        with patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", False):
            assert await ChromecastServicePlugin.validate_config({}) is False
        with patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", True):
            assert await ChromecastServicePlugin.validate_config({}) is True
            assert (
                await ChromecastServicePlugin.validate_config({"discovery_timeout": 99}) is False
            )

    def test_instance_identity_stable_per_device(self):
        living = {"device_name": "Living Room"}
        kitchen = {"device_name": "Kitchen"}
        assert ChromecastServicePlugin.instance_id_for(living) == (
            ChromecastServicePlugin.instance_id_for({**living, "discovery_timeout": 20})
        )
        assert ChromecastServicePlugin.instance_id_for(living) != (
            ChromecastServicePlugin.instance_id_for(kitchen)
        )
        # Empty device name -> generic fallback id.
        assert ChromecastServicePlugin.instance_id_for({"device_name": ""}) is None


class TestScanOptions:
    async def test_ignores_other_fields(self):
        assert await ChromecastServicePlugin.scan_options("other_field") is None

    async def test_without_dependency(self):
        with patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", False):
            result = await ChromecastServicePlugin.scan_options("device_name")
        assert result == {"options": [], "error": "pychromecast is not installed"}

    async def test_discovers_devices(self):
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = ([_fake_cast("Living Room")], object())

        with (
            patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", True),
            patch.object(chromecast_module, "pychromecast", fake_pychromecast, create=True),
        ):
            result = await ChromecastServicePlugin.scan_options("device_name")

        assert result == {"options": [{"value": "Living Room", "label": "Living Room"}]}
        fake_pychromecast.discovery.stop_discovery.assert_called_once()


class TestFetchShaping:
    """fetch() output is the payload the custom element's `.data` binds to."""

    async def test_fetch_without_dependency(self, plugin):
        with patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", False):
            result = await plugin.fetch()
        assert result == {"state": "error", "error": "pychromecast is not installed"}

    def _status_with(self, plugin, fake_pychromecast):
        with (
            patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", True),
            patch.object(chromecast_module, "pychromecast", fake_pychromecast, create=True),
            patch.object(chromecast_module.time, "sleep"),
        ):
            return plugin._get_cast_status()

    async def test_playing_payload(self, plugin):
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = ([_fake_cast()], object())
        result = self._status_with(plugin, fake_pychromecast)

        assert result["state"] == "playing"
        assert result["device_name"] == "Living Room"
        assert result["app_name"] == "Spotify"
        assert result["title"] == "Song"
        assert result["artist"] == "Artist"
        assert result["album"] == "Album"
        assert result["album_art_url"] == "http://art.example/cover.jpg"
        assert result["duration"] == 200
        assert result["current_time"] == 60

    async def test_idle_payload_has_no_media_fields(self, plugin):
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = (
            [_fake_cast(player_state="IDLE")],
            object(),
        )
        result = self._status_with(plugin, fake_pychromecast)
        assert result["state"] == "idle"
        assert "title" not in result

    async def test_no_devices(self, plugin):
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = ([], object())
        result = self._status_with(plugin, fake_pychromecast)
        assert result == {"state": "no_devices"}

    async def test_device_not_found_lists_alternatives(self, plugin):
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = (
            [_fake_cast("Kitchen"), _fake_cast("Bedroom")],
            object(),
        )
        result = self._status_with(plugin, fake_pychromecast)
        assert result["state"] == "device_not_found"
        assert result["available_devices"] == ["Kitchen", "Bedroom"]

    async def test_pick_device(self, plugin):
        casts = [_fake_cast("Kitchen"), _fake_cast("Living Room")]
        # Case-insensitive exact match on the configured name.
        assert plugin._pick_device(casts).cast_info.friendly_name == "Living Room"
        # No configured name -> first device.
        unconfigured = ChromecastServicePlugin("cc-x", "Chromecast")
        await unconfigured.configure({})
        assert unconfigured._pick_device(casts).cast_info.friendly_name == "Kitchen"

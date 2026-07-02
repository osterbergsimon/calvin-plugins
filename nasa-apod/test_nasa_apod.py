"""Tests for the NASA APOD plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/nasa-apod/test_nasa_apod.py
"""

import importlib.util
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ImagePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("nasa_apod_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nasa_module = _load_plugin_module()
NasaApodImagePlugin = nasa_module.NasaApodImagePlugin


@pytest.fixture
async def plugin(monkeypatch):
    """A configured plugin instance (scan cache disabled)."""
    monkeypatch.setattr(nasa_module, "save_scan_cache", lambda *a, **k: None)
    instance = NasaApodImagePlugin(plugin_id="nasa-apod-instance", name="NASA APOD", enabled=True)
    await instance.configure({"api_key": "", "count": "20"})
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_nasa_apod")
        module.NasaApodImagePlugin = NasaApodImagePlugin
        assert loader.register_module(module) == ["nasa_apod"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(nasa_module, hook), hook

    def test_metadata(self):
        md = NasaApodImagePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "nasa_apod"
        assert md.supports_multiple_instances is False
        assert md.fixed_instance_id == "nasa-apod-instance"  # preserved pre-2.0 instance id
        assert set(md.instance_config_schema) == {"api_key", "count"}

    def test_single_instance_has_no_config_derived_id(self):
        assert NasaApodImagePlugin.instance_id_for({"api_key": "x", "count": 5}) is None

    def test_is_image_plugin(self):
        assert issubclass(NasaApodImagePlugin, ImagePlugin)


class TestConfig:
    async def test_blank_api_key_falls_back_to_demo_key(self, plugin):
        assert plugin.api_key == "DEMO_KEY"
        assert plugin.count == 20  # "20" converted by schema type

    async def test_api_key_trimmed(self, plugin):
        await plugin.configure({"api_key": " real-key ", "count": 10})
        assert plugin.api_key == "real-key"

    async def test_count_capped_at_api_limit(self, plugin):
        await plugin.configure({"api_key": "", "count": 500})
        assert plugin.count == 100

    async def test_validate_config(self):
        assert await NasaApodImagePlugin.validate_config({"count": 20}) is True
        assert await NasaApodImagePlugin.validate_config({}) is True  # defaults are valid
        assert await NasaApodImagePlugin.validate_config({"count": 0}) is False
        assert await NasaApodImagePlugin.validate_config({"count": 101}) is False

    async def test_configure_forces_rescan(self, plugin):
        plugin._last_scan = datetime.now()
        await plugin.configure({"api_key": "", "count": 10})
        assert plugin._last_scan is None


class TestScan:
    async def test_scan_parses_entries_and_handles_videos(self, plugin):
        entries = [
            {
                "date": "2026-01-01",
                "media_type": "image",
                "url": "https://apod.nasa.gov/image/one.jpg",
                "hdurl": "https://apod.nasa.gov/image/one_hd.jpg",
                "title": "Galaxy",
                "explanation": "A galaxy.",
                "copyright": "Jane Doe",
            },
            {
                "date": "2026-01-02",
                "media_type": "video",
                "url": "https://youtube.com/watch?v=x",
                "thumbnail_url": "https://apod.nasa.gov/image/thumb.jpg",
                "title": "Video day",
            },
            {
                "date": "2026-01-03",
                "media_type": "video",
                "url": "https://youtube.com/watch?v=y",
                # no thumbnail -> skipped
            },
        ]
        response = MagicMock()
        response.json.return_value = entries
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert [img["id"] for img in images] == ["apod-2026-01-01", "apod-2026-01-02"]
        image = images[0]
        assert image["url"] == "https://apod.nasa.gov/image/one.jpg"
        assert image["raw_url"] == "https://apod.nasa.gov/image/one_hd.jpg"
        assert image["photographer"] == "Jane Doe"
        video = images[1]
        assert video["url"] == "https://apod.nasa.gov/image/thumb.jpg"
        assert video["media_type"] == "video"

        # The demo key and thumbs flag go out with the request
        _, kwargs = client.get.await_args
        assert kwargs["params"]["api_key"] == "DEMO_KEY"
        assert kwargs["params"]["thumbs"] == "true"

    async def test_scan_uses_cache_within_interval(self, plugin):
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            await plugin.scan_images()
            await plugin.scan_images()

        assert client.get.await_count == 1

    async def test_scan_keeps_cached_images_on_http_error(self, plugin):
        plugin._images = [{"id": "apod-2026-01-01"}]
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert images == [{"id": "apod-2026-01-01"}]


class TestGetImageData:
    async def test_uses_shared_fetch_helper(self, plugin):
        plugin._images = [{"id": "apod-2026-01-01", "url": "https://example.com/apod.jpg"}]
        plugin._last_scan = datetime.now()

        with patch.object(nasa_module, "fetch_image_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = b"image-data"
            data = await plugin.get_image_data("apod-2026-01-01")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with(
            "https://example.com/apod.jpg",
            plugin_name="NASA APOD",
            follow_redirects=True,
        )


class TestConnectionTest:
    async def test_success(self):
        response = MagicMock()
        response.status_code = 200
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await NasaApodImagePlugin.test_connection({"api_key": "my-key"})

        assert result["success"] is True
        _, kwargs = client.get.await_args
        assert kwargs["params"] == {"api_key": "my-key", "count": 1}

    async def test_connect_error_reported(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await NasaApodImagePlugin.test_connection({})

        assert result["success"] is False

"""Tests for the Picsum Photos plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/picsum/test_picsum.py
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
    spec = importlib.util.spec_from_file_location("picsum_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


picsum_module = _load_plugin_module()
PicsumImagePlugin = picsum_module.PicsumImagePlugin


@pytest.fixture
async def plugin(monkeypatch):
    """A configured plugin instance (scan cache disabled)."""
    monkeypatch.setattr(picsum_module, "save_scan_cache", lambda *a, **k: None)
    instance = PicsumImagePlugin(plugin_id="picsum-instance", name="Picsum Photos", enabled=True)
    await instance.configure({"count": "30"})
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_picsum")
        module.PicsumImagePlugin = PicsumImagePlugin
        assert loader.register_module(module) == ["picsum"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(picsum_module, hook), hook

    def test_metadata(self):
        md = PicsumImagePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "picsum"
        assert md.supports_multiple_instances is False
        assert md.fixed_instance_id == "picsum-instance"  # preserved pre-2.0 instance id
        assert set(md.instance_config_schema) == {"count"}

    def test_single_instance_has_no_config_derived_id(self):
        assert PicsumImagePlugin.instance_id_for({"count": 5}) is None

    def test_is_image_plugin(self):
        assert issubclass(PicsumImagePlugin, ImagePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.count == 30  # "30" converted by schema type
        assert plugin.base_url == "https://picsum.photos"

    async def test_count_capped_at_api_limit(self, plugin):
        await plugin.configure({"count": 200})
        assert plugin.count == 100

    async def test_validate_config(self):
        assert await PicsumImagePlugin.validate_config({"count": 30}) is True
        assert await PicsumImagePlugin.validate_config({"count": 1}) is True
        assert await PicsumImagePlugin.validate_config({"count": 100}) is True
        assert await PicsumImagePlugin.validate_config({}) is True  # defaults are valid
        assert await PicsumImagePlugin.validate_config({"count": 0}) is False
        assert await PicsumImagePlugin.validate_config({"count": 101}) is False

    async def test_configure_forces_rescan(self, plugin):
        plugin._last_scan = datetime.now()
        await plugin.configure({"count": 10})
        assert plugin._last_scan is None


class TestScan:
    async def test_scan_parses_photos(self, plugin):
        mock_photos = [
            {
                "id": "1",
                "author": "John Doe",
                "width": 1920,
                "height": 1080,
                "url": "https://picsum.photos/id/1",
                "download_url": "https://picsum.photos/id/1/download",
                "author_url": "https://example.com",
            },
            {
                "id": "2",
                "author": "Jane Smith",
                "width": 1920,
                "height": 1080,
                "url": "https://picsum.photos/id/2",
                "download_url": "https://picsum.photos/id/2/download",
                "author_url": "https://example.com",
            },
        ]
        response = MagicMock()
        response.json.return_value = mock_photos
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert {img["id"] for img in images} == {"picsum-1", "picsum-2"}
        assert {img["photographer"] for img in images} == {"John Doe", "Jane Smith"}
        assert all(img["source"] == "picsum-instance" for img in images)
        by_id = {img["id"]: img for img in images}
        assert by_id["picsum-1"]["url"] == "https://picsum.photos/id/1/800/600"
        assert by_id["picsum-1"]["raw_url"] == "https://picsum.photos/id/1/1920/1080"

    async def test_scan_limits_to_configured_count(self, plugin):
        await plugin.configure({"count": 3})
        mock_photos = [
            {"id": str(i), "author": f"Author {i}", "width": 1920, "height": 1080}
            for i in range(50)
        ]
        response = MagicMock()
        response.json.return_value = mock_photos
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert len(images) == 3

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
        plugin._images = [{"id": "picsum-1"}]
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert images == [{"id": "picsum-1"}]


class TestImageAccess:
    async def test_get_image_and_missing_image(self, plugin):
        images = [
            {"id": "picsum-1", "url": "https://example.com/1.jpg"},
            {"id": "picsum-2", "url": "https://example.com/2.jpg"},
        ]
        plugin._images = images
        plugin._last_scan = datetime.now()

        image = await plugin.get_image("picsum-1")
        assert image["id"] == "picsum-1"
        assert await plugin.get_image("picsum-nope") is None

    async def test_get_image_data_uses_shared_fetch_helper(self, plugin):
        plugin._images = [{"id": "picsum-1", "url": "https://example.com/1.jpg"}]
        plugin._last_scan = datetime.now()

        with patch.object(picsum_module, "fetch_image_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = b"image-data"
            data = await plugin.get_image_data("picsum-1")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with(
            "https://example.com/1.jpg",
            plugin_name="Picsum",
        )

    async def test_get_image_data_not_found(self, plugin):
        plugin._images = []
        plugin._last_scan = datetime.now()
        assert await plugin.get_image_data("picsum-nope") is None

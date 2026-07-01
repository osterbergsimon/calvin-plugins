"""Tests for the Unsplash plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/unsplash/test_unsplash.py
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
    spec = importlib.util.spec_from_file_location("unsplash_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


unsplash_module = _load_plugin_module()
UnsplashImagePlugin = unsplash_module.UnsplashImagePlugin


@pytest.fixture
async def plugin(monkeypatch):
    """A configured plugin instance (scan cache disabled)."""
    monkeypatch.setattr(unsplash_module, "save_scan_cache", lambda *a, **k: None)
    instance = UnsplashImagePlugin(plugin_id="unsplash-instance", name="Unsplash", enabled=True)
    await instance.configure(
        {"api_key": " test-api-key ", "category": "popular", "count": "30"}
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_unsplash")
        module.UnsplashImagePlugin = UnsplashImagePlugin
        assert loader.register_module(module) == ["unsplash"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(unsplash_module, hook), hook

    def test_metadata(self):
        md = UnsplashImagePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "unsplash"
        assert md.supports_multiple_instances is False
        assert md.fixed_instance_id == "unsplash-instance"  # preserved pre-2.0 instance id
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"api_key"}

    def test_single_instance_has_no_config_derived_id(self):
        assert UnsplashImagePlugin.instance_id_for({"api_key": "x"}) is None

    def test_is_image_plugin(self):
        assert issubclass(UnsplashImagePlugin, ImagePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.api_key == "test-api-key"  # whitespace trimmed
        assert plugin.category == "popular"
        assert plugin.count == 30  # "30" converted by schema type

    async def test_blank_api_key_becomes_none(self, plugin):
        await plugin.configure({"api_key": "   ", "category": "popular", "count": 30})
        assert plugin.api_key is None

    async def test_count_capped_at_api_limit(self, plugin):
        await plugin.configure({"api_key": "k", "count": 500})
        assert plugin.count == 100

    async def test_validate_config(self):
        good = {"api_key": "k", "category": "popular", "count": 30}
        assert await UnsplashImagePlugin.validate_config(good) is True
        assert await UnsplashImagePlugin.validate_config({**good, "api_key": ""}) is False
        assert await UnsplashImagePlugin.validate_config({**good, "category": "weird"}) is False
        assert await UnsplashImagePlugin.validate_config({**good, "count": 0}) is False
        assert await UnsplashImagePlugin.validate_config({**good, "count": 101}) is False

    async def test_configure_forces_rescan(self, plugin):
        plugin._last_scan = datetime.now()
        await plugin.configure({"api_key": "k", "count": 10})
        assert plugin._last_scan is None


class TestScan:
    async def test_scan_parses_photos_and_sends_auth(self, plugin):
        mock_photos = [
            {
                "id": "abc123",
                "width": 4000,
                "height": 3000,
                "description": "A sunset",
                "alt_description": "Sunset over hills",
                "created_at": "2026-01-01T00:00:00Z",
                "urls": {
                    "regular": "https://images.unsplash.com/abc123?w=1080",
                    "raw": "https://images.unsplash.com/abc123",
                },
                "user": {
                    "name": "Jane Doe",
                    "links": {"html": "https://unsplash.com/@jane"},
                },
            }
        ]
        response = MagicMock()
        response.json.return_value = mock_photos
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert [img["id"] for img in images] == ["unsplash-abc123"]
        image = images[0]
        assert image["url"] == "https://images.unsplash.com/abc123?w=1080"
        assert image["raw_url"] == "https://images.unsplash.com/abc123"
        assert image["title"] == "A sunset"
        assert image["photographer"] == "Jane Doe"
        assert image["photographer_url"] == "https://unsplash.com/@jane"
        assert image["source"] == "unsplash-instance"

        _, kwargs = client.get.await_args
        assert kwargs["headers"]["Authorization"] == "Client-ID test-api-key"
        assert kwargs["params"] == {"per_page": 30, "order_by": "popular"}

    async def test_scan_without_api_key_sends_no_auth_header(self, plugin):
        await plugin.configure({"api_key": "", "category": "latest", "count": 5})
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            await plugin.scan_images()

        _, kwargs = client.get.await_args
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["params"] == {"per_page": 5, "order_by": "latest"}

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
        plugin._images = [{"id": "unsplash-old"}]
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert images == [{"id": "unsplash-old"}]


class TestImageAccess:
    async def test_get_image_and_missing_image(self, plugin):
        plugin._images = [
            {"id": "unsplash-1", "url": "https://example.com/1.jpg"},
            {"id": "unsplash-2", "url": "https://example.com/2.jpg"},
        ]
        plugin._last_scan = datetime.now()

        image = await plugin.get_image("unsplash-2")
        assert image["id"] == "unsplash-2"
        assert await plugin.get_image("unsplash-nope") is None

    async def test_get_image_data_prefers_raw_url(self, plugin):
        plugin._images = [
            {
                "id": "unsplash-1",
                "url": "https://example.com/regular.jpg",
                "raw_url": "https://example.com/raw.jpg",
            }
        ]
        plugin._last_scan = datetime.now()

        with patch.object(
            unsplash_module, "fetch_image_data", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = b"image-data"
            data = await plugin.get_image_data("unsplash-1")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with(
            "https://example.com/raw.jpg",
            plugin_name="Unsplash",
        )

    async def test_get_image_data_not_found(self, plugin):
        plugin._images = []
        plugin._last_scan = datetime.now()
        assert await plugin.get_image_data("unsplash-nope") is None

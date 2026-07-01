"""Tests for the Lychee plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/lychee/test_lychee.py
"""

import importlib.util
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.sdk.image import SelfHostedGalleryImagePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("lychee_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lychee_module = _load_plugin_module()
LycheeImagePlugin = lychee_module.LycheeImagePlugin


@pytest.fixture
async def plugin(monkeypatch):
    """A configured plugin instance (scan cache disabled)."""
    monkeypatch.setattr(lychee_module, "save_scan_cache", lambda *a, **k: None)
    instance = LycheeImagePlugin(plugin_id="lychee-test", name="Lychee", enabled=True)
    await instance.configure(
        {
            "url": "https://photos.example.com/",
            "api_key": "token",
            "album_id": "",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_lychee")
        module.LycheeImagePlugin = LycheeImagePlugin
        assert loader.register_module(module) == ["lychee"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(lychee_module, hook), hook

    def test_metadata(self):
        md = LycheeImagePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "lychee"
        assert md.supports_multiple_instances is True
        assert md.instance_identity == ["url"]
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"url", "api_key"}

    def test_is_gallery_image_plugin(self):
        assert issubclass(LycheeImagePlugin, SelfHostedGalleryImagePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.base_url == "https://photos.example.com"  # trailing slash trimmed
        assert plugin.api_key == "token"
        assert plugin.album_id == ""

    async def test_validate_config(self):
        good = {"url": "https://photos.example.com", "api_key": "token"}
        assert await LycheeImagePlugin.validate_config(good) is True
        assert await LycheeImagePlugin.validate_config({**good, "api_key": ""}) is False
        assert await LycheeImagePlugin.validate_config({**good, "url": ""}) is False
        assert await LycheeImagePlugin.validate_config({**good, "url": "ftp://x"}) is False

    def test_instance_identity_stable_per_server(self):
        config = {"url": "https://photos.example.com", "api_key": "a"}
        other = {"url": "https://other.example.com", "api_key": "a"}
        assert LycheeImagePlugin.instance_id_for(config) == LycheeImagePlugin.instance_id_for(
            {**config, "api_key": "b"}
        )
        assert LycheeImagePlugin.instance_id_for(config) != LycheeImagePlugin.instance_id_for(
            other
        )

    async def test_configure_forces_rescan(self, plugin):
        plugin._last_scan = MagicMock()
        await plugin.configure({"url": "https://photos.example.com", "api_key": "new"})
        assert plugin._last_scan is None


class TestGalleryHelpers:
    async def test_auth_headers_and_api_url(self, plugin):
        assert plugin.auth_headers() == {
            "Authorization": "Bearer token",
            "Accept": "application/json",
        }
        assert plugin.api_url("Albums") == "https://photos.example.com/api/v2/Albums"

    async def test_get_image_data_uses_gallery_base_fetch(self, plugin):
        images = [{"id": "lychee-1", "url": "https://photos.example.com/uploads/1.jpg"}]
        plugin._images = images

        with (
            patch.object(plugin, "scan_images", new=AsyncMock(return_value=images)),
            patch.object(
                LycheeImagePlugin, "fetch_protected_image_data", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_fetch.return_value = b"image-data"
            data = await plugin.get_image_data("lychee-1")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with("https://photos.example.com/uploads/1.jpg")


class TestScan:
    async def test_scan_skipped_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(lychee_module, "save_scan_cache", lambda *a, **k: None)
        instance = LycheeImagePlugin("lychee-x", "Lychee")
        await instance.configure({"url": "", "api_key": ""})
        assert await instance.scan_images() == []

    async def test_metadata_resolves_relative_urls(self, plugin):
        image = plugin._to_image_metadata(
            {
                "id": "p1",
                "title": "Sunset",
                "type": "image/jpeg",
                "created_at": "2026-01-01",
                "size_variants": {
                    "original": {
                        "url": "/uploads/original/p1.jpg",
                        "width": 4000,
                        "height": 3000,
                        "filesize": 999,
                    },
                    "medium": {"url": "uploads/medium/p1.jpg"},
                },
            }
        )
        assert image["id"] == "lychee-p1"
        assert image["url"] == "https://photos.example.com/uploads/medium/p1.jpg"
        assert image["raw_url"] == "https://photos.example.com/uploads/original/p1.jpg"
        assert image["format"] == "jpeg"
        assert image["width"] == 4000
        assert image["source"] == "lychee-test"

    async def test_scan_fetches_configured_album(self, plugin):
        await plugin.configure(
            {"url": "https://photos.example.com", "api_key": "token", "album_id": "alb1"}
        )
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "photos": [
                {"id": "p1", "title": "One", "size_variants": {"original": {"url": "/u/1.jpg"}}}
            ]
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert [img["id"] for img in images] == ["lychee-p1"]
        client.post.assert_awaited_once_with(
            "https://photos.example.com/api/v2/Album",
            json={"albumID": "alb1"},
            headers={"Authorization": "Bearer token", "Accept": "application/json"},
        )


class TestConnectionTest:
    async def test_missing_config_fails_fast(self):
        result = await LycheeImagePlugin.test_connection({})
        assert result["success"] is False

    async def test_albums_success(self):
        response = MagicMock()
        response.status_code = 200
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await LycheeImagePlugin.test_connection(
                {"url": "https://photos.example.com", "api_key": "token"}
            )

        assert result["success"] is True
        client.post.assert_awaited_once_with(
            "https://photos.example.com/api/v2/Albums",
            headers={"Authorization": "Bearer token", "Accept": "application/json"},
        )

    async def test_connect_error_reported(self):
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("no route"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await LycheeImagePlugin.test_connection(
                {"url": "https://photos.example.com", "api_key": "token"}
            )

        assert result["success"] is False
        assert "connect" in result["message"].lower()

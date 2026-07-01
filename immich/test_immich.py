"""Tests for the Immich plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/immich/test_immich.py
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
    spec = importlib.util.spec_from_file_location("immich_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


immich_module = _load_plugin_module()
ImmichImagePlugin = immich_module.ImmichImagePlugin


@pytest.fixture
async def plugin(monkeypatch):
    """A configured plugin instance (scan cache disabled)."""
    monkeypatch.setattr(immich_module, "save_scan_cache", lambda *a, **k: None)
    instance = ImmichImagePlugin(plugin_id="immich-test", name="Immich", enabled=True)
    await instance.configure(
        {
            "url": "https://photos.example.com/",
            "api_key": "secret",
            "album_id": "",
            "count": "30",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_immich")
        module.ImmichImagePlugin = ImmichImagePlugin
        assert loader.register_module(module) == ["immich"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(immich_module, hook), hook

    def test_metadata(self):
        md = ImmichImagePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "immich"
        assert md.supports_multiple_instances is True
        assert md.instance_identity == ["url"]
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"url", "api_key"}

    def test_is_gallery_image_plugin(self):
        assert issubclass(ImmichImagePlugin, SelfHostedGalleryImagePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.base_url == "https://photos.example.com"  # trailing slash trimmed
        assert plugin.api_key == "secret"
        assert plugin.album_id == ""
        assert plugin.count == 30  # "30" converted by schema type

    async def test_validate_config(self):
        good = {"url": "https://photos.example.com", "api_key": "secret"}
        assert await ImmichImagePlugin.validate_config(good) is True
        assert await ImmichImagePlugin.validate_config({**good, "api_key": ""}) is False
        assert await ImmichImagePlugin.validate_config({**good, "url": ""}) is False
        assert await ImmichImagePlugin.validate_config({**good, "url": "ftp://x"}) is False

    def test_instance_identity_stable_per_server(self):
        config = {"url": "https://photos.example.com", "api_key": "a"}
        other = {"url": "https://other.example.com", "api_key": "a"}
        assert ImmichImagePlugin.instance_id_for(config) == ImmichImagePlugin.instance_id_for(
            {**config, "api_key": "b"}
        )
        assert ImmichImagePlugin.instance_id_for(config) != ImmichImagePlugin.instance_id_for(
            other
        )

    async def test_configure_forces_rescan(self, plugin):
        plugin._last_scan = MagicMock()
        await plugin.configure({"url": "https://photos.example.com", "api_key": "new"})
        assert plugin._last_scan is None


class TestGalleryHelpers:
    async def test_auth_headers_and_api_url(self, plugin):
        assert plugin.auth_headers() == {
            "x-api-key": "secret",
            "Accept": "application/json",
        }
        assert plugin.api_url("assets/asset123/original") == (
            "https://photos.example.com/api/assets/asset123/original"
        )

    async def test_get_image_data_uses_gallery_base_fetch(self, plugin):
        with patch.object(
            ImmichImagePlugin,
            "fetch_protected_image_data",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = b"image-data"

            data = await plugin.get_image_data("immich-asset123")

            assert data == b"image-data"
            mock_fetch.assert_awaited_once_with(
                "https://photos.example.com/api/assets/asset123/original",
            )


class TestScan:
    async def test_scan_skipped_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(immich_module, "save_scan_cache", lambda *a, **k: None)
        instance = ImmichImagePlugin("immich-x", "Immich")
        await instance.configure({"url": "", "api_key": ""})
        assert await instance.scan_images() == []

    async def test_scan_parses_assets_and_filters_non_images(self, plugin):
        assets = [
            {
                "id": "asset1",
                "type": "IMAGE",
                "originalFileName": "sunset.jpg",
                "originalMimeType": "image/jpeg",
                "fileSize": 1234,
                "fileCreatedAt": "2026-01-01T00:00:00Z",
                "localDateTime": "2026-01-01T00:00:00",
                "exifInfo": {"exifImageWidth": 4000, "exifImageHeight": 3000, "make": "Canon"},
            },
            {"id": "clip1", "type": "VIDEO", "originalFileName": "clip.mp4"},
        ]
        response = MagicMock()
        response.json.return_value = assets
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            images = await plugin.scan_images()

        assert [img["id"] for img in images] == ["immich-asset1"]
        image = images[0]
        assert image["filename"] == "sunset.jpg"
        assert image["url"] == (
            "https://photos.example.com/api/assets/asset1/thumbnail?size=preview"
        )
        assert image["raw_url"] == "https://photos.example.com/api/assets/asset1/original"
        assert image["width"] == 4000
        assert image["photographer"] == "Canon"
        assert image["source"] == "immich-test"

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


class TestConnectionTest:
    async def test_missing_config_fails_fast(self):
        result = await ImmichImagePlugin.test_connection({})
        assert result["success"] is False

    async def test_ping_success(self):
        response = MagicMock()
        response.status_code = 200
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await ImmichImagePlugin.test_connection(
                {"url": "https://photos.example.com", "api_key": "secret"}
            )

        assert result["success"] is True
        client.get.assert_awaited_once_with(
            "https://photos.example.com/api/server/ping",
            headers={"x-api-key": "secret", "Accept": "application/json"},
        )

    async def test_connect_error_reported(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value = client
            result = await ImmichImagePlugin.test_connection(
                {"url": "https://photos.example.com", "api_key": "secret"}
            )

        assert result["success"] is False
        assert "connect" in result["message"].lower()

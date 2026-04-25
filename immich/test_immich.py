"""Tests for Immich plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    import importlib.util

    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("immich_plugin", plugin_path)
    if spec and spec.loader:
        immich_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(immich_module)
        ImmichImagePlugin = immich_module.ImmichImagePlugin
    else:
        pytest.skip("Could not load immich plugin module", allow_module_level=True)
except ImportError as exc:
    pytest.skip(f"Backend dependencies not available: {exc}", allow_module_level=True)


@pytest.mark.asyncio
async def test_get_image_data_uses_gallery_base_fetch():
    plugin = ImmichImagePlugin(
        plugin_id="immich-instance",
        name="Immich",
        url="https://photos.example.com",
        api_key="secret",
        album_id="",
        count=30,
        enabled=True,
    )

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


def test_immich_uses_gallery_base_helpers():
    plugin = ImmichImagePlugin(
        plugin_id="immich-instance",
        name="Immich",
        url="https://photos.example.com/",
        api_key="secret",
        album_id="",
        count=30,
        enabled=True,
    )

    assert plugin.auth_headers() == {
        "x-api-key": "secret",
        "Accept": "application/json",
    }
    assert plugin.api_url("assets/asset123/original") == (
        "https://photos.example.com/api/assets/asset123/original"
    )

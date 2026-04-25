"""Tests for Lychee plugin."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    import importlib.util

    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("lychee_plugin", plugin_path)
    if spec and spec.loader:
        lychee_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lychee_module)
        LycheeImagePlugin = lychee_module.LycheeImagePlugin
    else:
        pytest.skip("Could not load lychee plugin module")
except ImportError as exc:
    pytest.skip(f"Backend dependencies not available: {exc}")


@pytest.mark.asyncio
async def test_get_image_data_uses_gallery_base_fetch():
    plugin = LycheeImagePlugin(
        plugin_id="lychee-instance",
        name="Lychee",
        url="https://photos.example.com",
        api_key="secret",
        album_id="",
        enabled=True,
    )
    plugin._images = [
        {
            "id": "lychee-photo123",
            "url": "https://photos.example.com/uploads/photo123.jpg",
        }
    ]
    plugin._last_scan = datetime.now()

    with patch.object(
        LycheeImagePlugin,
        "fetch_protected_image_data",
        new_callable=AsyncMock,
    ) as mock_fetch:
        mock_fetch.return_value = b"image-data"

        data = await plugin.get_image_data("lychee-photo123")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with(
            "https://photos.example.com/uploads/photo123.jpg",
        )


def test_lychee_uses_gallery_base_helpers():
    plugin = LycheeImagePlugin(
        plugin_id="lychee-instance",
        name="Lychee",
        url="https://photos.example.com/",
        api_key="secret",
        album_id="",
        enabled=True,
    )

    assert plugin.auth_headers() == {
        "Authorization": "Bearer secret",
        "Accept": "application/json",
    }
    assert plugin.api_url("Album") == "https://photos.example.com/api/v2/Album"

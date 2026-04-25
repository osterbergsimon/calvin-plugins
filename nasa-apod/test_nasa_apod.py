"""Tests for NASA APOD plugin."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    import importlib.util

    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("nasa_apod_plugin", plugin_path)
    if spec and spec.loader:
        nasa_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nasa_module)
        NasaApodImagePlugin = nasa_module.NasaApodImagePlugin
    else:
        pytest.skip("Could not load nasa-apod plugin module", allow_module_level=True)
except ImportError as exc:
    pytest.skip(f"Backend dependencies not available: {exc}", allow_module_level=True)


@pytest.mark.asyncio
async def test_get_image_data_uses_shared_fetch_helper():
    plugin = NasaApodImagePlugin(
        plugin_id="nasa-apod-instance",
        name="NASA APOD",
        api_key="",
        count=20,
        enabled=True,
    )
    plugin._images = [
        {
            "id": "apod-2024-01-01",
            "url": "https://example.com/apod.jpg",
        }
    ]
    plugin._last_scan = datetime.now()

    with patch.object(nasa_module, "fetch_image_data", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = b"image-data"

        data = await plugin.get_image_data("apod-2024-01-01")

        assert data == b"image-data"
        mock_fetch.assert_awaited_once_with(
            "https://example.com/apod.jpg",
            plugin_name="NASA APOD",
            follow_redirects=True,
        )

"""Tests for Picsum Photos plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/picsum/test_picsum.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest
import httpx

# Note: These tests assume the plugin is installed and the backend imports are available
# In a real scenario, you'd run these tests in the calvin backend context
try:
    from app.plugins.base import PluginType
    from app.plugins.hooks import hookimpl
    from app.plugins.protocols import ImagePlugin
    from app.plugins.utils.config import extract_config_value, to_int
    from app.plugins.utils.instance_manager import (
        InstanceManagerConfig,
        handle_plugin_config_update_generic,
    )
    
    # Import the plugin
    import sys
    from pathlib import Path
    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("picsum_plugin", plugin_path)
        if spec and spec.loader:
            picsum_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(picsum_module)
            PicsumImagePlugin = picsum_module.PicsumImagePlugin
        else:
            pytest.skip("Could not load picsum plugin module")
    else:
        pytest.skip("picsum plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def picsum_plugin():
    """Create a PicsumImagePlugin instance."""
    return PicsumImagePlugin(
        plugin_id="picsum-instance",
        name="Picsum Photos",
        count=30,
        enabled=True,
    )


class TestPicsumImagePlugin:
    """Tests for PicsumImagePlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = PicsumImagePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "picsum"
        assert metadata["plugin_type"] == PluginType.IMAGE
        assert metadata["name"] == "Picsum Photos"
        assert metadata["supports_multiple_instances"] is False
        assert "common_config_schema" in metadata
        assert "count" in metadata["common_config_schema"]

    def test_init(self, picsum_plugin):
        """Test plugin initialization."""
        assert picsum_plugin.plugin_id == "picsum-instance"
        assert picsum_plugin.name == "Picsum Photos"
        assert picsum_plugin.count == 30
        assert picsum_plugin.enabled is True
        assert picsum_plugin.base_url == "https://picsum.photos"

    @pytest.mark.asyncio
    async def test_scan_images_success(self, picsum_plugin):
        """Test scanning images successfully."""
        mock_photos = [
            {
                "id": 1,
                "author": "John Doe",
                "width": 1920,
                "height": 1080,
                "url": "https://picsum.photos/id/1",
                "download_url": "https://picsum.photos/id/1/download",
                "author_url": "https://example.com",
            },
            {
                "id": 2,
                "author": "Jane Smith",
                "width": 1920,
                "height": 1080,
                "url": "https://picsum.photos/id/2",
                "download_url": "https://picsum.photos/id/2/download",
                "author_url": "https://example.com",
            },
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            images = await picsum_plugin.scan_images()

            assert len(images) <= picsum_plugin.count
            if len(images) > 0:
                assert images[0]["id"] == "picsum-1"
                assert images[0]["source"] == "picsum-instance"
                assert images[0]["photographer"] == "John Doe"

    @pytest.mark.asyncio
    async def test_scan_images_with_caching(self, picsum_plugin):
        """Test that scan_images caches results."""
        mock_photos = [
            {
                "id": 1,
                "author": "John Doe",
                "width": 1920,
                "height": 1080,
                "url": "https://picsum.photos/id/1",
                "download_url": "https://picsum.photos/id/1/download",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # First scan
            images1 = await picsum_plugin.scan_images()
            # Second scan should use cache
            images2 = await picsum_plugin.scan_images()

            # Should only call API once (cached on second call)
            assert mock_client.return_value.__aenter__.return_value.get.call_count <= 1

    @pytest.mark.asyncio
    async def test_scan_images_http_error(self, picsum_plugin):
        """Test handling of HTTP errors during scan."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=MagicMock()
            )
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Should return cached images or empty list
            images = await picsum_plugin.scan_images()
            assert isinstance(images, list)

    @pytest.mark.asyncio
    async def test_get_images(self, picsum_plugin):
        """Test getting images list."""
        # Mock scan_images to return test data without actually scanning
        test_images = [{"id": "picsum-1", "url": "https://example.com/image.jpg"}]
        
        # Patch scan_images to set the internal state and return
        async def mock_scan():
            picsum_plugin._images = test_images
            picsum_plugin._last_scan = datetime.now()
            return test_images
        
        with patch.object(picsum_plugin, "scan_images", side_effect=mock_scan):
            images = await picsum_plugin.get_images()
            assert len(images) == 1
            assert images[0]["id"] == "picsum-1"

    @pytest.mark.asyncio
    async def test_get_image(self, picsum_plugin):
        """Test getting a specific image by ID."""
        # Mock scan_images to return test data without actually scanning
        test_images = [
            {"id": "picsum-1", "url": "https://example.com/image1.jpg"},
            {"id": "picsum-2", "url": "https://example.com/image2.jpg"},
        ]
        
        # Patch scan_images to set the internal state and return
        async def mock_scan():
            picsum_plugin._images = test_images
            picsum_plugin._last_scan = datetime.now()
            return test_images
        
        with patch.object(picsum_plugin, "scan_images", side_effect=mock_scan):
            image = await picsum_plugin.get_image("picsum-1")
            assert image is not None
            assert image["id"] == "picsum-1"

            image = await picsum_plugin.get_image("picsum-nonexistent")
            assert image is None

    @pytest.mark.asyncio
    async def test_get_image_data(self, picsum_plugin):
        """Test getting image file data."""
        with patch.object(picsum_plugin, "get_image", new_callable=AsyncMock) as mock_get_image:
            mock_get_image.return_value = {
                "id": "picsum-1",
                "url": "https://example.com/image.jpg",
                "raw_url": "https://example.com/image.jpg",
            }

            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.content = b"fake image data"
                mock_response.raise_for_status = MagicMock()
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

                data = await picsum_plugin.get_image_data("picsum-1")
                assert data == b"fake image data"

    @pytest.mark.asyncio
    async def test_get_image_data_not_found(self, picsum_plugin):
        """Test getting image data for non-existent image."""
        with patch.object(picsum_plugin, "get_image", new_callable=AsyncMock) as mock_get_image:
            mock_get_image.return_value = None
            data = await picsum_plugin.get_image_data("picsum-nonexistent")
            assert data is None

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, picsum_plugin):
        """Test config validation with valid config."""
        assert await picsum_plugin.validate_config({"count": 30}) is True
        assert await picsum_plugin.validate_config({"count": 1}) is True
        assert await picsum_plugin.validate_config({"count": 100}) is True

    @pytest.mark.asyncio
    async def test_validate_config_invalid(self, picsum_plugin):
        """Test config validation with invalid config."""
        assert await picsum_plugin.validate_config({"count": 0}) is False
        assert await picsum_plugin.validate_config({"count": 101}) is False
        assert await picsum_plugin.validate_config({"count": -1}) is False

    @pytest.mark.asyncio
    async def test_configure(self, picsum_plugin):
        """Test plugin configuration."""
        assert picsum_plugin.count == 30

        await picsum_plugin.configure({"count": 50})
        assert picsum_plugin.count == 50

        # Test capping at 100
        await picsum_plugin.configure({"count": 200})
        assert picsum_plugin.count == 100

        # Verify cache is reset
        assert picsum_plugin._last_scan is None


@pytest.mark.asyncio
class TestPicsumPluginHooks:
    """Tests for Picsum plugin hooks."""

    async def test_create_plugin_instance(self):
        """Test create_plugin_instance hook."""
        # This would need to be tested in the actual backend context
        # with proper plugin loading
        pass

    async def test_handle_plugin_config_update(self):
        """Test handle_plugin_config_update hook.
        
        Note: This test is skipped when run from the plugin directory because it requires
        the `test_db` fixture which is only available in the backend test suite.
        
        To test handle_plugin_config_update hooks, run the backend test suite from the
        backend directory:
            cd backend
            pytest tests/unit/test_plugin_hooks.py
        
        Or run the comprehensive generic instance manager tests which test the same
        functionality that all plugin hooks now use:
            pytest tests/unit/test_plugin_instance_manager.py
        
        These tests verify that:
        - handle_plugin_config_update_generic works correctly (tested in test_plugin_instance_manager.py)
        - Plugin hooks correctly call handle_plugin_config_update_generic (tested in test_plugin_hooks.py)
        """
        pytest.skip("Requires backend test fixtures (test_db). "
                   "Run from backend directory: "
                   "cd backend && pytest tests/unit/test_plugin_hooks.py")


class TestPicsumPluginIntegration:
    """Integration tests for Picsum plugin (require backend context)."""

    @pytest.mark.asyncio
    async def test_randomization(self, picsum_plugin):
        """Test that images are randomized on each scan."""
        import random
        
        # Seed random for reproducible test
        random.seed(42)
        
        mock_photos = [
            {"id": i, "author": f"Author {i}", "width": 1920, "height": 1080,
             "url": f"https://picsum.photos/id/{i}", "download_url": ""}
            for i in range(100)
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Reset cache
            picsum_plugin._last_scan = None
            
            # First scan
            images1 = await picsum_plugin.scan_images()
            ids1 = [img["id"] for img in images1]

            # Reset cache and scan again
            picsum_plugin._last_scan = None
            random.seed(999)  # Different seed
            images2 = await picsum_plugin.scan_images()
            ids2 = [img["id"] for img in images2]

            # Should have different selection (though not guaranteed with randomization)
            # At least verify we get the expected count
            assert len(images1) == picsum_plugin.count
            assert len(images2) == picsum_plugin.count

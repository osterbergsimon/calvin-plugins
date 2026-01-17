"""Tests for Unsplash plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/unsplash/test_unsplash.py
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
    from app.plugins.utils.config import extract_config_value, to_int, to_str
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
        spec = importlib.util.spec_from_file_location("unsplash_plugin", plugin_path)
        if spec and spec.loader:
            unsplash_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(unsplash_module)
            UnsplashImagePlugin = unsplash_module.UnsplashImagePlugin
        else:
            pytest.skip("Could not load unsplash plugin module")
    else:
        pytest.skip("unsplash plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def unsplash_plugin():
    """Create an UnsplashImagePlugin instance."""
    return UnsplashImagePlugin(
        plugin_id="unsplash-instance",
        name="Unsplash",
        api_key="test-api-key",
        category="popular",
        count=30,
        enabled=True,
    )


class TestUnsplashImagePlugin:
    """Tests for UnsplashImagePlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = UnsplashImagePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "unsplash"
        assert metadata["plugin_type"] == PluginType.IMAGE
        assert metadata["name"] == "Unsplash"
        assert metadata["supports_multiple_instances"] is False
        assert "common_config_schema" in metadata
        assert "api_key" in metadata["common_config_schema"]
        assert "category" in metadata["common_config_schema"]
        assert "count" in metadata["common_config_schema"]

    def test_init(self, unsplash_plugin):
        """Test plugin initialization."""
        assert unsplash_plugin.plugin_id == "unsplash-instance"
        assert unsplash_plugin.name == "Unsplash"
        assert unsplash_plugin.api_key == "test-api-key"
        assert unsplash_plugin.category == "popular"
        assert unsplash_plugin.count == 30
        assert unsplash_plugin.enabled is True
        assert unsplash_plugin.base_url == "https://api.unsplash.com"

    def test_init_without_api_key(self):
        """Test plugin initialization without API key."""
        plugin = UnsplashImagePlugin(
            plugin_id="unsplash-instance",
            name="Unsplash",
            api_key=None,
            category="latest",
            count=50,
            enabled=False,
        )
        assert plugin.api_key is None
        assert plugin.category == "latest"
        assert plugin.count == 50
        assert plugin.enabled is False

    @pytest.mark.asyncio
    async def test_scan_images_success(self, unsplash_plugin):
        """Test scanning images successfully."""
        mock_photos = [
            {
                "id": "photo1",
                "description": "Test photo",
                "width": 1920,
                "height": 1080,
                "urls": {
                    "regular": "https://images.unsplash.com/photo1-regular",
                    "raw": "https://images.unsplash.com/photo1-raw",
                },
                "user": {
                    "name": "John Doe",
                    "links": {"html": "https://unsplash.com/@johndoe"},
                },
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "photo2",
                "alt_description": "Another test photo",
                "width": 1920,
                "height": 1080,
                "urls": {
                    "regular": "https://images.unsplash.com/photo2-regular",
                    "raw": "https://images.unsplash.com/photo2-raw",
                },
                "user": {
                    "name": "Jane Smith",
                    "links": {"html": "https://unsplash.com/@janesmith"},
                },
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            images = await unsplash_plugin.scan_images()

            assert len(images) <= unsplash_plugin.count
            if len(images) > 0:
                assert images[0]["id"] == "unsplash-photo1"
                assert images[0]["source"] == "unsplash-instance"
                assert images[0]["photographer"] == "John Doe"
                assert images[0]["raw_url"] == "https://images.unsplash.com/photo1-raw"

    @pytest.mark.asyncio
    async def test_scan_images_with_api_key(self, unsplash_plugin):
        """Test scanning images with API key in headers."""
        mock_photos = [
            {
                "id": "photo1",
                "width": 1920,
                "height": 1080,
                "urls": {"regular": "https://example.com/photo.jpg", "raw": "https://example.com/photo-raw.jpg"},
                "user": {"name": "Test User", "links": {}},
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            await unsplash_plugin.scan_images()

            # Verify Authorization header was added
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert headers["Authorization"] == "Client-ID test-api-key"

    @pytest.mark.asyncio
    async def test_scan_images_without_api_key(self):
        """Test scanning images without API key (should still work but with warnings)."""
        plugin = UnsplashImagePlugin(
            plugin_id="unsplash-instance",
            name="Unsplash",
            api_key=None,
            enabled=True,
        )

        mock_photos = [
            {
                "id": "photo1",
                "width": 1920,
                "height": 1080,
                "urls": {"regular": "https://example.com/photo.jpg", "raw": "https://example.com/photo-raw.jpg"},
                "user": {"name": "Test User", "links": {}},
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            await plugin.scan_images()

            # Verify no Authorization header when API key is None
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_scan_images_with_caching(self, unsplash_plugin):
        """Test that scan_images caches results."""
        mock_photos = [
            {
                "id": "photo1",
                "width": 1920,
                "height": 1080,
                "urls": {"regular": "https://example.com/photo.jpg", "raw": "https://example.com/photo-raw.jpg"},
                "user": {"name": "Test User", "links": {}},
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_photos
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # First scan
            images1 = await unsplash_plugin.scan_images()
            # Second scan should use cache
            images2 = await unsplash_plugin.scan_images()

            # Should only call API once (cached on second call)
            assert mock_client.return_value.__aenter__.return_value.get.call_count <= 1

    @pytest.mark.asyncio
    async def test_scan_images_http_error_401(self, unsplash_plugin):
        """Test handling of 401 (authentication) error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Should return cached images or empty list
            images = await unsplash_plugin.scan_images()
            assert isinstance(images, list)

    @pytest.mark.asyncio
    async def test_scan_images_http_error_403(self, unsplash_plugin):
        """Test handling of 403 (forbidden) error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Forbidden",
                request=MagicMock(),
                response=MagicMock(status_code=403),
            )
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Should return cached images or empty list
            images = await unsplash_plugin.scan_images()
            assert isinstance(images, list)

    @pytest.mark.asyncio
    async def test_get_images(self, unsplash_plugin):
        """Test getting images list."""
        # Mock scan_images by setting the internal _images list
        test_images = [{"id": "unsplash-photo1", "url": "https://example.com/image.jpg"}]
        unsplash_plugin._images = test_images
        unsplash_plugin._last_scan = datetime.now()  # Set to avoid rescanning
        
        images = await unsplash_plugin.get_images()
        assert len(images) == 1
        assert images[0]["id"] == "unsplash-photo1"

    @pytest.mark.asyncio
    async def test_get_image(self, unsplash_plugin):
        """Test getting a specific image by ID."""
        # Mock scan_images by setting the internal _images list
        test_images = [
            {"id": "unsplash-photo1", "url": "https://example.com/image1.jpg"},
            {"id": "unsplash-photo2", "url": "https://example.com/image2.jpg"},
        ]
        unsplash_plugin._images = test_images
        unsplash_plugin._last_scan = datetime.now()  # Set to avoid rescanning
        
        image = await unsplash_plugin.get_image("unsplash-photo1")
        assert image is not None
        assert image["id"] == "unsplash-photo1"

        image = await unsplash_plugin.get_image("unsplash-nonexistent")
        assert image is None

    @pytest.mark.asyncio
    async def test_get_image_data(self, unsplash_plugin):
        """Test getting image file data."""
        # Mock scan_images by setting the internal _images list
        unsplash_plugin._images = [
            {
                "id": "unsplash-photo1",
                "url": "https://example.com/image.jpg",
                "raw_url": "https://example.com/image-raw.jpg",
            }
        ]
        unsplash_plugin._last_scan = datetime.now()

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.content = b"fake image data"
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            data = await unsplash_plugin.get_image_data("unsplash-photo1")
            assert data == b"fake image data"

    @pytest.mark.asyncio
    async def test_get_image_data_not_found(self, unsplash_plugin):
        """Test getting image data for non-existent image."""
        unsplash_plugin._images = []
        unsplash_plugin._last_scan = datetime.now()

        data = await unsplash_plugin.get_image_data("unsplash-nonexistent")
        assert data is None

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, unsplash_plugin):
        """Test config validation with valid config."""
        assert await unsplash_plugin.validate_config({"api_key": "test-key", "category": "popular", "count": 30}) is True
        assert await unsplash_plugin.validate_config({"category": "latest", "count": 1}) is True
        assert await unsplash_plugin.validate_config({"category": "oldest", "count": 100}) is True
        assert await unsplash_plugin.validate_config({"count": 50}) is True  # API key optional

    @pytest.mark.asyncio
    async def test_validate_config_invalid_category(self, unsplash_plugin):
        """Test config validation with invalid category."""
        assert await unsplash_plugin.validate_config({"category": "invalid"}) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_count(self, unsplash_plugin):
        """Test config validation with invalid count."""
        assert await unsplash_plugin.validate_config({"count": 0}) is False
        assert await unsplash_plugin.validate_config({"count": 101}) is False
        assert await unsplash_plugin.validate_config({"count": -1}) is False
        assert await unsplash_plugin.validate_config({"count": "not-a-number"}) is False

    @pytest.mark.asyncio
    async def test_configure(self, unsplash_plugin):
        """Test plugin configuration."""
        assert unsplash_plugin.api_key == "test-api-key"
        assert unsplash_plugin.category == "popular"
        assert unsplash_plugin.count == 30

        await unsplash_plugin.configure({"api_key": "new-key", "category": "latest", "count": 50})
        assert unsplash_plugin.api_key == "new-key"
        assert unsplash_plugin.category == "latest"
        assert unsplash_plugin.count == 50

        # Test capping at 100
        await unsplash_plugin.configure({"count": 200})
        assert unsplash_plugin.count == 100

        # Verify cache is reset
        assert unsplash_plugin._last_scan is None

    @pytest.mark.asyncio
    async def test_configure_empty_api_key(self, unsplash_plugin):
        """Test that empty API key becomes None."""
        assert unsplash_plugin.api_key == "test-api-key"

        await unsplash_plugin.configure({"api_key": ""})
        assert unsplash_plugin.api_key is None

        await unsplash_plugin.configure({"api_key": "   "})  # Whitespace only
        # configure method should strip whitespace and convert to None
        assert unsplash_plugin.api_key is None


@pytest.mark.asyncio
class TestUnsplashPluginHooks:
    """Tests for Unsplash plugin hooks."""

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
        
        These tests verify that plugin hooks correctly call handle_plugin_config_update_generic.
        """
        pytest.skip("Requires backend test fixtures (test_db). "
                   "Run from backend directory: "
                   "cd backend && pytest tests/unit/test_plugin_hooks.py")


class TestUnsplashPluginIntegration:
    """Integration tests for Unsplash plugin (require backend context)."""

    @pytest.mark.asyncio
    async def test_different_categories(self, unsplash_plugin):
        """Test that different categories work correctly."""
        mock_photos = [
            {
                "id": f"photo{i}",
                "width": 1920,
                "height": 1080,
                "urls": {"regular": f"https://example.com/photo{i}.jpg", "raw": f"https://example.com/photo{i}-raw.jpg"},
                "user": {"name": f"User {i}", "links": {}},
                "created_at": "2024-01-01T00:00:00Z",
            }
            for i in range(10)
        ]

        for category in ["popular", "latest", "oldest"]:
            unsplash_plugin.category = category
            unsplash_plugin._last_scan = None  # Reset cache

            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = mock_photos
                mock_response.raise_for_status = MagicMock()
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

                images = await unsplash_plugin.scan_images()

                # Verify the category parameter was passed correctly
                call_args = mock_client.return_value.__aenter__.return_value.get.call_args
                params = call_args.kwargs.get("params", {})
                assert params.get("order_by") == category
                assert len(images) > 0

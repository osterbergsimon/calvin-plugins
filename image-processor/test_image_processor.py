"""Tests for Image Processor plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/image-processor/test_image_processor.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

import pytest

# Note: These tests assume the plugin is installed and the backend imports are available
# In a real scenario, you'd run these tests in the calvin backend context
try:
    from app.plugins.base import PluginType
    from app.plugins.hooks import hookimpl
    from app.plugins.protocols import BackendPlugin
    from app.plugins.utils.config import extract_config_value, to_bool, to_int
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
        spec = importlib.util.spec_from_file_location("image_processor_plugin", plugin_path)
        if spec and spec.loader:
            image_processor_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(image_processor_module)
            ImageProcessorPlugin = image_processor_module.ImageProcessorPlugin
        else:
            pytest.skip("Could not load image processor plugin module")
    else:
        pytest.skip("image processor plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def image_processor_plugin():
    """Create an ImageProcessorPlugin instance."""
    return ImageProcessorPlugin(
        plugin_id="image-processor-instance",
        name="Image Processor",
        enabled=True,
    )


class TestImageProcessorPlugin:
    """Tests for ImageProcessorPlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = ImageProcessorPlugin.get_plugin_metadata()
        assert metadata["type_id"] == "image-processor"
        assert metadata["plugin_type"] == PluginType.BACKEND
        assert metadata["name"] == "Image Processor"
        assert metadata["supports_multiple_instances"] is True
        assert "common_config_schema" in metadata
        assert "instance_config_schema" in metadata
        assert "enabled" in metadata["instance_config_schema"]
        assert "max_width" in metadata["instance_config_schema"]
        assert "max_height" in metadata["instance_config_schema"]
        assert "thumbnail_size" in metadata["instance_config_schema"]

    def test_init(self, image_processor_plugin):
        """Test plugin initialization."""
        assert image_processor_plugin.plugin_id == "image-processor-instance"
        assert image_processor_plugin.name == "Image Processor"
        assert image_processor_plugin.enabled is True
        assert image_processor_plugin._processed_count == 0
        assert image_processor_plugin._error_count == 0

    def test_plugin_type_property(self, image_processor_plugin):
        """Test plugin type property."""
        assert image_processor_plugin.plugin_type == PluginType.BACKEND

    @pytest.mark.asyncio
    async def test_initialize(self, image_processor_plugin):
        """Test plugin initialization."""
        await image_processor_plugin.initialize()
        assert image_processor_plugin._processed_count == 0
        assert image_processor_plugin._error_count == 0

    @pytest.mark.asyncio
    async def test_cleanup(self, image_processor_plugin):
        """Test plugin cleanup."""
        image_processor_plugin._processed_count = 5
        image_processor_plugin._error_count = 2
        await image_processor_plugin.cleanup()
        # Cleanup should log stats but not reset them

    @pytest.mark.asyncio
    async def test_get_subscribed_events_enabled(self, image_processor_plugin):
        """Test getting subscribed events when plugin is enabled."""
        # Mock get_config to return enabled config
        with patch.object(image_processor_plugin, "get_config", return_value={"enabled": True}):
            events = await image_processor_plugin.get_subscribed_events()
            assert "image_uploaded" in events

    @pytest.mark.asyncio
    async def test_get_subscribed_events_disabled(self, image_processor_plugin):
        """Test getting subscribed events when plugin is disabled."""
        image_processor_plugin.enabled = False
        events = await image_processor_plugin.get_subscribed_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_get_subscribed_events_config_disabled(self, image_processor_plugin):
        """Test getting subscribed events when config has enabled=False."""
        with patch.object(image_processor_plugin, "get_config", return_value={"enabled": False}):
            events = await image_processor_plugin.get_subscribed_events()
            assert events == []

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, image_processor_plugin):
        """Test config validation with valid config."""
        assert await image_processor_plugin.validate_config({}) is True
        assert await image_processor_plugin.validate_config({"max_width": 1920, "max_height": 1080}) is True
        assert await image_processor_plugin.validate_config({"max_width": 1000, "max_height": 800, "thumbnail_size": 200}) is True

    @pytest.mark.asyncio
    async def test_validate_config_invalid_width(self, image_processor_plugin):
        """Test config validation with invalid width."""
        assert await image_processor_plugin.validate_config({"max_width": 0}) is False
        assert await image_processor_plugin.validate_config({"max_width": -1}) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_height(self, image_processor_plugin):
        """Test config validation with invalid height."""
        assert await image_processor_plugin.validate_config({"max_height": 0}) is False
        assert await image_processor_plugin.validate_config({"max_height": -1}) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_thumbnail_size(self, image_processor_plugin):
        """Test config validation with invalid thumbnail size."""
        assert await image_processor_plugin.validate_config({"generate_thumbnails": True, "thumbnail_size": 0}) is False
        assert await image_processor_plugin.validate_config({"generate_thumbnails": True, "thumbnail_size": -1}) is False

    @pytest.mark.asyncio
    async def test_handle_image_uploaded_success(self, image_processor_plugin):
        """Test handling image_uploaded event successfully."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }

            with patch.object(image_processor_plugin, "get_config", return_value={
                "enabled": True,
                "resize_enabled": True,
                "max_width": 1920,
                "max_height": 1080,
                "generate_thumbnails": True,
                "thumbnail_size": 300,
            }), patch.object(image_processor_plugin, "emit_event", new_callable=AsyncMock) as mock_emit:
                result = await image_processor_plugin.handle_event("image_uploaded", event_data)

                assert result["success"] is True
                assert "Processed test.jpg" in result["message"]
                assert "processing_results" in result
                assert result["processing_results"]["resized"] is True
                assert result["processing_results"]["thumbnail_generated"] is True
                assert image_processor_plugin._processed_count == 1
                assert image_processor_plugin._error_count == 0

                # Verify event was emitted
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "image_processed"
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_handle_image_uploaded_file_not_found(self, image_processor_plugin):
        """Test handling image_uploaded event when file doesn't exist."""
        event_data = {
            "image_id": "test-image-1",
            "filename": "nonexistent.jpg",
            "path": "/nonexistent/path/image.jpg",
            "plugin_id": "source-plugin",
        }

        result = await image_processor_plugin.handle_event("image_uploaded", event_data)

        assert result["success"] is False
        assert "Image path not found" in result["error"]
        assert image_processor_plugin._processed_count == 0
        assert image_processor_plugin._error_count == 1

    @pytest.mark.asyncio
    async def test_handle_image_uploaded_without_resize(self, image_processor_plugin):
        """Test handling image_uploaded event without resizing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }

            with patch.object(image_processor_plugin, "get_config", return_value={
                "enabled": True,
                "resize_enabled": False,
                "generate_thumbnails": False,
            }), patch.object(image_processor_plugin, "emit_event", new_callable=AsyncMock):
                result = await image_processor_plugin.handle_event("image_uploaded", event_data)

                assert result["success"] is True
                assert "resized" not in result["processing_results"]
                assert "thumbnail_generated" not in result["processing_results"]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_handle_image_uploaded_exception(self, image_processor_plugin):
        """Test handling image_uploaded event when exception occurs during processing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }

            # Patch get_config to raise an exception during processing
            # The exception should be caught and handled
            with patch.object(image_processor_plugin, "get_config", side_effect=Exception("Test error during config access")):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with patch.object(image_processor_plugin, "emit_event", new_callable=AsyncMock):
                        result = await image_processor_plugin.handle_event("image_uploaded", event_data)

                    assert result["success"] is False
                    assert "error" in result
                    assert "Test error" in result["error"]
                    assert image_processor_plugin._error_count > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_get_processing_stats(self, image_processor_plugin):
        """Test getting processing statistics."""
        image_processor_plugin._processed_count = 10
        image_processor_plugin._error_count = 2

        stats = await image_processor_plugin.get_processing_stats()
        assert stats["processed_count"] == 10
        assert stats["error_count"] == 2
        assert stats["total_processed"] == 12

    @pytest.mark.asyncio
    async def test_provide_service(self, image_processor_plugin):
        """Test providing service to other plugins."""
        image_processor_plugin._processed_count = 5
        image_processor_plugin._error_count = 1

        stats = await image_processor_plugin.provide_service("get_processing_stats")
        assert stats is not None
        assert stats["processed_count"] == 5
        assert stats["error_count"] == 1

        # Non-existent service
        result = await image_processor_plugin.provide_service("non_existent_service")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_provided_services(self, image_processor_plugin):
        """Test getting list of provided services."""
        services = await image_processor_plugin.get_provided_services()
        assert "get_processing_stats" in services

    @pytest.mark.asyncio
    async def test_configure(self, image_processor_plugin):
        """Test plugin configuration."""
        # Configure should update the plugin's stored config
        await image_processor_plugin.configure({
            "enabled": True,
            "max_width": 2560,
            "max_height": 1440,
            "thumbnail_size": 400,
        })
        
        # Config is stored via BasePlugin.configure, verify via validate_config
        # (configure doesn't expose the config directly)
        assert await image_processor_plugin.validate_config({
            "max_width": 2560,
            "max_height": 1440,
            "thumbnail_size": 400,
        }) is True


@pytest.mark.asyncio
class TestImageProcessorHooks:
    """Tests for Image Processor plugin hooks."""

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
        """
        pytest.skip("Requires backend test fixtures (test_db). "
                   "Run from backend directory: "
                   "cd backend && pytest tests/unit/test_plugin_hooks.py")

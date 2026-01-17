"""Tests for Mealie plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/mealie/test_mealie.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import pytest
import httpx

# Note: These tests assume the plugin is installed and the backend imports are available
# In a real scenario, you'd run these tests in the calvin backend context
try:
    from app.plugins.base import PluginType
    from app.plugins.hooks import hookimpl
    from app.plugins.protocols import ServicePlugin
    from app.plugins.utils.config import extract_config_value, to_int, to_str, to_bool
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
        spec = importlib.util.spec_from_file_location("mealie_plugin", plugin_path)
        if spec and spec.loader:
            mealie_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mealie_module)
            MealieServicePlugin = mealie_module.MealieServicePlugin
        else:
            pytest.skip("Could not load mealie plugin module")
    else:
        pytest.skip("mealie plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def mealie_plugin():
    """Create a MealieServicePlugin instance."""
    return MealieServicePlugin(
        plugin_id="mealie-instance",
        name="Mealie Meal Plan",
        mealie_url="http://mealie.local:9000",
        api_token="test-api-token",
        group_id=None,
        days_ahead=7,
        enabled=True,
        display_order=0,
        fullscreen=False,
    )


class TestMealieServicePlugin:
    """Tests for MealieServicePlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = MealieServicePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "mealie"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["name"] == "Mealie Meal Plan"
        assert metadata["supports_multiple_instances"] is False
        assert "common_config_schema" in metadata
        assert "instance_config_schema" in metadata
        assert "mealie_url" in metadata["instance_config_schema"]
        assert "api_token" in metadata["instance_config_schema"]
        assert "days_ahead" in metadata["instance_config_schema"]

    def test_init(self, mealie_plugin):
        """Test plugin initialization."""
        assert mealie_plugin.plugin_id == "mealie-instance"
        assert mealie_plugin.name == "Mealie Meal Plan"
        assert mealie_plugin.mealie_url == "http://mealie.local:9000"
        assert mealie_plugin.api_token == "test-api-token"
        assert mealie_plugin.group_id is None
        assert mealie_plugin.days_ahead == 7
        assert mealie_plugin.enabled is True
        assert mealie_plugin.display_order == 0
        assert mealie_plugin.fullscreen is False

    def test_init_with_group_id(self):
        """Test plugin initialization with group ID."""
        plugin = MealieServicePlugin(
            plugin_id="mealie-instance",
            name="Mealie Meal Plan",
            mealie_url="http://mealie.local:9000",
            api_token="test-token",
            group_id="test-group-id",
            days_ahead=14,
            enabled=False,
            display_order=5,
            fullscreen=True,
        )
        assert plugin.group_id == "test-group-id"
        assert plugin.days_ahead == 14
        assert plugin.enabled is False
        assert plugin.display_order == 5
        assert plugin.fullscreen is True

    def test_init_url_rstrip(self):
        """Test that URL trailing slashes are removed."""
        plugin = MealieServicePlugin(
            plugin_id="mealie-instance",
            name="Mealie Meal Plan",
            mealie_url="http://mealie.local:9000/",
            api_token="test-token",
        )
        assert plugin.mealie_url == "http://mealie.local:9000"

    @pytest.mark.asyncio
    async def test_initialize_success(self, mealie_plugin):
        """Test plugin initialization with valid URL and token."""
        await mealie_plugin.initialize()
        assert mealie_plugin._client is not None

    @pytest.mark.asyncio
    async def test_initialize_invalid_url(self):
        """Test plugin initialization with invalid URL."""
        plugin = MealieServicePlugin(
            plugin_id="mealie-instance",
            name="Mealie Meal Plan",
            mealie_url="invalid-url",
            api_token="test-token",
        )
        with pytest.raises(ValueError, match="Invalid Mealie URL"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_empty_url(self):
        """Test plugin initialization with empty URL."""
        plugin = MealieServicePlugin(
            plugin_id="mealie-instance",
            name="Mealie Meal Plan",
            mealie_url="",
            api_token="test-token",
        )
        with pytest.raises(ValueError, match="Invalid Mealie URL"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_empty_token(self):
        """Test plugin initialization with empty token."""
        plugin = MealieServicePlugin(
            plugin_id="mealie-instance",
            name="Mealie Meal Plan",
            mealie_url="http://mealie.local:9000",
            api_token="",
        )
        with pytest.raises(ValueError, match="API token is required"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_cleanup(self, mealie_plugin):
        """Test plugin cleanup."""
        await mealie_plugin.initialize()
        assert mealie_plugin._client is not None
        
        await mealie_plugin.cleanup()
        assert mealie_plugin._client is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self, mealie_plugin):
        """Test cleanup when client doesn't exist."""
        assert mealie_plugin._client is None
        await mealie_plugin.cleanup()
        # Should not raise an error

    @pytest.mark.asyncio
    async def test_get_content_success(self, mealie_plugin):
        """Test getting service content successfully."""
        content = await mealie_plugin.get_content()
        assert content["type"] == "mealie"
        assert content["url"] == "/api/web-services/mealie-instance/data"
        assert content["data"]["mealie_url"] == "http://mealie.local:9000"
        assert content["data"]["group_id"] is None
        assert "api_token" in content["data"]  # Token is in data but not exposed to frontend
        assert content["config"]["allowFullscreen"] is True

    @pytest.mark.asyncio
    async def test_get_content_with_group_id(self, mealie_plugin):
        """Test getting content with group ID."""
        mealie_plugin.group_id = "test-group"
        content = await mealie_plugin.get_content()
        assert content["data"]["group_id"] == "test-group"

    @pytest.mark.asyncio
    async def test_fetch_meal_plan_success(self, mealie_plugin):
        """Test fetching meal plan successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "date": "2024-01-01",
                    "meals": [{"type": "breakfast", "recipe": {"name": "Toast"}}],
                }
            ]
        }

        with patch.object(mealie_plugin, "_client") as mock_client:
            mock_client.__aenter__.return_value.get.return_value = mock_response
            await mealie_plugin.initialize()
            result = await mealie_plugin._fetch_meal_plan()
            assert "items" in result

    @pytest.mark.asyncio
    async def test_fetch_meal_plan_http_error(self, mealie_plugin):
        """Test fetching meal plan with HTTP error."""
        with patch.object(mealie_plugin, "_client") as mock_client:
            mock_client.__aenter__.return_value.get.side_effect = httpx.HTTPStatusError(
                "Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
            await mealie_plugin.initialize()
            result = await mealie_plugin._fetch_meal_plan()
            assert "error" in result

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, mealie_plugin):
        """Test config validation with valid config."""
        assert await mealie_plugin.validate_config({
            "mealie_url": "http://mealie.local:9000",
            "api_token": "test-token",
        }) is True

        assert await mealie_plugin.validate_config({
            "mealie_url": "https://mealie.example.com",
            "api_token": "test-token",
            "days_ahead": 14,
        }) is True

    @pytest.mark.asyncio
    async def test_validate_config_missing_url(self, mealie_plugin):
        """Test config validation with missing URL."""
        assert await mealie_plugin.validate_config({"api_token": "test-token"}) is False
        assert await mealie_plugin.validate_config({"mealie_url": "", "api_token": "test-token"}) is False

    @pytest.mark.asyncio
    async def test_validate_config_missing_token(self, mealie_plugin):
        """Test config validation with missing token."""
        assert await mealie_plugin.validate_config({"mealie_url": "http://mealie.local:9000"}) is False
        assert await mealie_plugin.validate_config({"mealie_url": "http://mealie.local:9000", "api_token": ""}) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_url(self, mealie_plugin):
        """Test config validation with invalid URL."""
        assert await mealie_plugin.validate_config({
            "mealie_url": "not-a-url",
            "api_token": "test-token",
        }) is False

        assert await mealie_plugin.validate_config({
            "mealie_url": "ftp://mealie.local",
            "api_token": "test-token",
        }) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_days_ahead(self, mealie_plugin):
        """Test config validation with invalid days_ahead."""
        assert await mealie_plugin.validate_config({
            "mealie_url": "http://mealie.local:9000",
            "api_token": "test-token",
            "days_ahead": 0,
        }) is False

        assert await mealie_plugin.validate_config({
            "mealie_url": "http://mealie.local:9000",
            "api_token": "test-token",
            "days_ahead": 31,
        }) is False

    @pytest.mark.asyncio
    async def test_configure(self, mealie_plugin):
        """Test plugin configuration."""
        await mealie_plugin.initialize()
        
        await mealie_plugin.configure({
            "mealie_url": "http://new-mealie.local:9000",
            "api_token": "new-token",
            "group_id": "new-group",
            "days_ahead": 14,
            "display_order": 5,
            "fullscreen": True,
        })

        assert mealie_plugin.mealie_url == "http://new-mealie.local:9000"
        assert mealie_plugin.api_token == "new-token"
        assert mealie_plugin.group_id == "new-group"
        assert mealie_plugin.days_ahead == 14
        assert mealie_plugin.display_order == 5
        assert mealie_plugin.fullscreen is True

    @pytest.mark.asyncio
    async def test_configure_url_rstrip(self, mealie_plugin):
        """Test that configure strips trailing slashes from URL."""
        await mealie_plugin.configure({
            "mealie_url": "http://mealie.local:9000/",
            "api_token": "test-token",
        })
        assert mealie_plugin.mealie_url == "http://mealie.local:9000"

    @pytest.mark.asyncio
    async def test_configure_empty_group_id(self, mealie_plugin):
        """Test that empty group_id becomes None."""
        await mealie_plugin.configure({
            "mealie_url": "http://mealie.local:9000",
            "api_token": "test-token",
            "group_id": "",
        })
        assert mealie_plugin.group_id is None

    @pytest.mark.asyncio
    async def test_configure_partial_update(self, mealie_plugin):
        """Test configuring with partial config."""
        await mealie_plugin.initialize()
        original_url = mealie_plugin.mealie_url
        
        await mealie_plugin.configure({"days_ahead": 10})
        
        # URL should remain unchanged
        assert mealie_plugin.mealie_url == original_url
        assert mealie_plugin.days_ahead == 10


@pytest.mark.asyncio
class TestMealiePluginHooks:
    """Tests for Mealie plugin hooks."""

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

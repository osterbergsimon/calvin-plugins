"""Tests for Weather Service plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/weather/test_weather.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Note: These tests assume the plugin is installed and the backend imports are available
# In a real scenario, you'd run these tests in the calvin backend context
try:
    from app.plugins.base import PluginType
    
    # Import the plugin
    import sys
    from pathlib import Path
    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("weather_plugin", plugin_path)
        if spec and spec.loader:
            weather_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(weather_module)
            WeatherServicePlugin = weather_module.WeatherServicePlugin
            handle_plugin_config_update = weather_module.handle_plugin_config_update
        else:
            pytest.skip("Could not load weather plugin module")
    else:
        pytest.skip("weather plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def weather_plugin():
    """Create a WeatherServicePlugin instance."""
    plugin = WeatherServicePlugin(
        plugin_id="weather-instance",
        name="Weather",
        api_key="test-api-key",
        location="London, UK",
        units="metric",
        forecast_days=3,
        enabled=True,
        display_order=0,
        fullscreen=False,
    )
    return plugin


class TestWeatherServicePlugin:
    """Tests for WeatherServicePlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = WeatherServicePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "weather"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["name"] == "Weather"
        assert metadata["supports_multiple_instances"] is True
        assert "common_config_schema" in metadata
        assert "instance_config_schema" in metadata
        assert "api_key" in metadata["common_config_schema"]
        assert "location" in metadata["instance_config_schema"]

    def test_init(self, weather_plugin):
        """Test plugin initialization."""
        assert weather_plugin.plugin_id == "weather-instance"
        assert weather_plugin.name == "Weather"
        assert weather_plugin.api_key == "test-api-key"
        assert weather_plugin.location == "London, UK"
        assert weather_plugin.units == "metric"
        assert weather_plugin.forecast_days == 3
        assert weather_plugin.display_order == 0
        assert weather_plugin.fullscreen is False
        assert weather_plugin.enabled is True

    def test_init_forecast_days_clamping(self):
        """Test that forecast_days is clamped between 1 and 5."""
        plugin = WeatherServicePlugin(
            plugin_id="test",
            name="Test",
            api_key="key",
            location="London",
            forecast_days=10,  # Too large
        )
        assert plugin.forecast_days == 5

        plugin = WeatherServicePlugin(
            plugin_id="test",
            name="Test",
            api_key="key",
            location="London",
            forecast_days=0,  # Too small
        )
        assert plugin.forecast_days == 1

    @pytest.mark.asyncio
    async def test_initialize(self, weather_plugin):
        """Test plugin initialization."""
        await weather_plugin.initialize()
        assert weather_plugin._client is not None
        assert str(weather_plugin._client.base_url).rstrip("/") == "https://api.openweathermap.org/data/2.5"

    @pytest.mark.asyncio
    async def test_initialize_missing_api_key(self):
        """Test initialization with missing API key."""
        plugin = WeatherServicePlugin(
            plugin_id="test",
            name="Test",
            api_key="",
            location="London",
        )
        with pytest.raises(ValueError, match="OpenWeatherMap API key is required"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_missing_location(self):
        """Test initialization with missing location."""
        plugin = WeatherServicePlugin(
            plugin_id="test",
            name="Test",
            api_key="key",
            location="",
        )
        with pytest.raises(ValueError, match="Location is required"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_cleanup(self, weather_plugin):
        """Test plugin cleanup."""
        await weather_plugin.initialize()
        assert weather_plugin._client is not None
        await weather_plugin.cleanup()
        assert weather_plugin._client is None

    @pytest.mark.asyncio
    async def test_configure(self, weather_plugin):
        """Test plugin configuration update."""
        await weather_plugin.initialize()
        original_client = weather_plugin._client

        await weather_plugin.configure({
            "api_key": "new-key",
            "location": "New York, US",
            "units": "imperial",
            "forecast_days": 5,
            "display_order": 1,
            "fullscreen": True,
        })

        assert weather_plugin.api_key == "new-key"
        assert weather_plugin.location == "New York, US"
        assert weather_plugin.units == "imperial"
        assert weather_plugin.forecast_days == 5
        assert weather_plugin.display_order == 1
        assert weather_plugin.fullscreen is True
        # Client should be reinitialized
        assert weather_plugin._client is not None
        assert weather_plugin._client != original_client

    @pytest.mark.asyncio
    async def test_configure_partial(self, weather_plugin):
        """Test plugin configuration update with partial config."""
        await weather_plugin.initialize()  # Initialize first so we have a client
        original_location = weather_plugin.location
        original_api_key = weather_plugin.api_key
        
        await weather_plugin.configure({
            "api_key": original_api_key,  # Must provide required fields
            "location": original_location,  # Must provide required fields
            "units": "imperial",
        })
        assert weather_plugin.location == original_location  # Should remain unchanged
        assert weather_plugin.units == "imperial"

    @pytest.mark.asyncio
    async def test_get_content(self, weather_plugin):
        """Test getting service content."""
        content = await weather_plugin.get_content()
        assert content["type"] == "weather"
        assert content["url"] == f"/api/plugins/{weather_plugin.plugin_id}/data"
        assert "data" in content
        assert content["data"]["api_key"] == "test-api-key"
        assert content["data"]["location"] == "London, UK"
        assert content["data"]["units"] == "metric"

    @pytest.mark.asyncio
    async def test_get_config(self, weather_plugin):
        """Test getting plugin configuration."""
        config = weather_plugin.get_config()
        assert config["api_key"] == "test-api-key"
        assert config["location"] == "London, UK"
        assert config["units"] == "metric"
        assert config["forecast_days"] == 3
        assert config["display_order"] == 0
        assert config["fullscreen"] is False

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, weather_plugin):
        """Test config validation with valid config."""
        assert await weather_plugin.validate_config({
            "api_key": "test-key",
            "location": "London, UK",
        }) is True

        # Test with string values
        assert await weather_plugin.validate_config({
            "api_key": "test-key",
            "location": "London, UK",
        }) is True

    @pytest.mark.asyncio
    async def test_validate_config_missing_api_key(self, weather_plugin):
        """Test config validation with missing api_key."""
        assert await weather_plugin.validate_config({
            "location": "London, UK",
        }) is False

    @pytest.mark.asyncio
    async def test_validate_config_empty_api_key(self, weather_plugin):
        """Test config validation with empty api_key."""
        assert await weather_plugin.validate_config({
            "api_key": "",
            "location": "London, UK",
        }) is False

    @pytest.mark.asyncio
    async def test_validate_config_missing_location(self, weather_plugin):
        """Test config validation with missing location."""
        assert await weather_plugin.validate_config({
            "api_key": "test-key",
        }) is False

    @pytest.mark.asyncio
    async def test_validate_config_empty_location(self, weather_plugin):
        """Test config validation with empty location."""
        assert await weather_plugin.validate_config({
            "api_key": "test-key",
            "location": "",
        }) is False

    @pytest.mark.asyncio
    async def test_fetch_service_data(self, weather_plugin):
        """Test fetching weather data."""
        # Mock HTTP client and responses
        mock_client = AsyncMock()
        weather_plugin._client = mock_client

        # Mock current weather response
        mock_current_response = MagicMock()
        mock_current_response.json.return_value = {
            "main": {
                "temp": 15.5,
                "feels_like": 14.0,
                "humidity": 65,
                "pressure": 1013,
            },
            "weather": [{"description": "clear sky", "icon": "01d"}],
            "wind": {"speed": 3.5, "deg": 180},
            "name": "London",
            "sys": {"country": "GB"},
        }
        mock_current_response.raise_for_status = MagicMock()

        # Mock forecast response
        from datetime import datetime, timedelta
        now = datetime.now()
        mock_forecast_response = MagicMock()
        mock_forecast_response.json.return_value = {
            "list": [
                {
                    "dt": int((now + timedelta(hours=3)).timestamp()),
                    "main": {"temp": 16.0},
                    "weather": [{"description": "sunny", "icon": "01d"}],
                },
                {
                    "dt": int((now + timedelta(hours=6)).timestamp()),
                    "main": {"temp": 17.0},
                    "weather": [{"description": "cloudy", "icon": "02d"}],
                },
            ],
        }
        mock_forecast_response.raise_for_status = MagicMock()

        mock_client.get = AsyncMock(side_effect=[
            mock_current_response,
            mock_forecast_response,
        ])

        weather_data = await weather_plugin.fetch_service_data()

        assert "current" in weather_data
        assert "forecast" in weather_data
        assert weather_data["current"]["temperature"] == 15.5
        assert weather_data["units"] == "metric"


class TestWeatherServicePluginHooks:
    """Tests for Weather Service plugin hooks."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Backend-dependent hook test. Run from backend/tests/unit/test_plugin_hooks.py instead.")
    async def test_handle_plugin_config_update(self, test_db):
        """Test Weather Service plugin handle_plugin_config_update hook.
        
        Note: This test requires backend fixtures (test_db). 
        Run the hook integration test from backend/tests/unit/test_plugin_hooks.py instead:
        
            pytest backend/tests/unit/test_plugin_hooks.py::TestPluginHooks::test_weather_handle_plugin_config_update
        """
        pytest.skip("Backend-dependent hook test. Run from backend/tests/unit/test_plugin_hooks.py instead.")

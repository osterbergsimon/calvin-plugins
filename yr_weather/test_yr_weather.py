"""Tests for Yr.no Weather plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/yr_weather/test_yr_weather.py
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
        spec = importlib.util.spec_from_file_location("yr_weather_plugin", plugin_path)
        if spec and spec.loader:
            yr_weather_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(yr_weather_module)
            YrWeatherServicePlugin = yr_weather_module.YrWeatherServicePlugin
            handle_plugin_config_update = yr_weather_module.handle_plugin_config_update
        else:
            pytest.skip("Could not load yr_weather plugin module")
    else:
        pytest.skip("yr_weather plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def yr_weather_plugin():
    """Create a YrWeatherServicePlugin instance."""
    plugin = YrWeatherServicePlugin(
        plugin_id="yr_weather-instance",
        name="Yr.no Weather",
        latitude=59.9139,
        longitude=10.7522,
        altitude=0,
        forecast_days=5,
        location="Oslo, Norway",
        enabled=True,
    )
    return plugin


class TestYrWeatherServicePlugin:
    """Tests for YrWeatherServicePlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = YrWeatherServicePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "yr_weather"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["name"] == "Yr.no Weather"
        assert metadata["supports_multiple_instances"] is True
        assert "common_config_schema" in metadata
        assert "instance_config_schema" in metadata
        assert "latitude" in metadata["instance_config_schema"]
        assert "longitude" in metadata["instance_config_schema"]

    def test_init(self, yr_weather_plugin):
        """Test plugin initialization."""
        assert yr_weather_plugin.plugin_id == "yr_weather-instance"
        assert yr_weather_plugin.name == "Yr.no Weather"
        assert yr_weather_plugin.latitude == 59.9139
        assert yr_weather_plugin.longitude == 10.7522
        assert yr_weather_plugin.altitude == 0
        assert yr_weather_plugin.forecast_days == 5
        assert yr_weather_plugin.location == "Oslo, Norway"
        assert yr_weather_plugin.enabled is True

    def test_init_coordinate_rounding(self):
        """Test that coordinates are rounded to 4 decimals."""
        plugin = YrWeatherServicePlugin(
            plugin_id="test",
            name="Test",
            latitude=59.91391234,
            longitude=10.75223456,
        )
        assert plugin.latitude == 59.9139
        assert plugin.longitude == 10.7522

    def test_init_forecast_days_clamping(self):
        """Test that forecast_days is clamped between 1 and 9."""
        plugin = YrWeatherServicePlugin(
            plugin_id="test",
            name="Test",
            latitude=59.9139,
            longitude=10.7522,
            forecast_days=15,  # Too large
        )
        assert plugin.forecast_days == 9

        plugin = YrWeatherServicePlugin(
            plugin_id="test",
            name="Test",
            latitude=59.9139,
            longitude=10.7522,
            forecast_days=0,  # Too small
        )
        assert plugin.forecast_days == 1

    @pytest.mark.asyncio
    async def test_initialize(self, yr_weather_plugin):
        """Test plugin initialization."""
        await yr_weather_plugin.initialize()
        assert yr_weather_plugin._client is not None
        # base_url is an httpx.URL object, convert to string for comparison
        assert str(yr_weather_plugin._client.base_url).rstrip("/") == "https://api.met.no/weatherapi/locationforecast/2.0"

    @pytest.mark.asyncio
    async def test_initialize_invalid_latitude(self):
        """Test initialization with invalid latitude."""
        plugin = YrWeatherServicePlugin(
            plugin_id="test",
            name="Test",
            latitude=100,  # Invalid
            longitude=10.7522,
        )
        with pytest.raises(ValueError, match="Invalid latitude"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_invalid_longitude(self):
        """Test initialization with invalid longitude."""
        plugin = YrWeatherServicePlugin(
            plugin_id="test",
            name="Test",
            latitude=59.9139,
            longitude=200,  # Invalid
        )
        with pytest.raises(ValueError, match="Invalid longitude"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_cleanup(self, yr_weather_plugin):
        """Test plugin cleanup."""
        await yr_weather_plugin.initialize()
        assert yr_weather_plugin._client is not None
        await yr_weather_plugin.cleanup()
        assert yr_weather_plugin._client is None

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, yr_weather_plugin):
        """Test config validation with valid config."""
        assert await yr_weather_plugin.validate_config({
            "latitude": 59.9139,
            "longitude": 10.7522,
        }) is True

        assert await yr_weather_plugin.validate_config({
            "latitude": "59.9139",
            "longitude": "10.7522",
        }) is True

    @pytest.mark.asyncio
    async def test_validate_config_missing_latitude(self, yr_weather_plugin):
        """Test config validation with missing latitude."""
        # Missing key should return None from extract_config_value
        result = await yr_weather_plugin.validate_config({
            "longitude": 10.7522,
        })
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_config_missing_longitude(self, yr_weather_plugin):
        """Test config validation with missing longitude."""
        # Missing key should return None from extract_config_value
        result = await yr_weather_plugin.validate_config({
            "latitude": 59.9139,
        })
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_coordinates(self, yr_weather_plugin):
        """Test config validation with invalid coordinates."""
        assert await yr_weather_plugin.validate_config({
            "latitude": 100,  # Invalid
            "longitude": 10.7522,
        }) is False

        assert await yr_weather_plugin.validate_config({
            "latitude": 59.9139,
            "longitude": 200,  # Invalid
        }) is False

    @pytest.mark.asyncio
    async def test_configure(self, yr_weather_plugin):
        """Test plugin configuration."""
        await yr_weather_plugin.initialize()
        
        with patch.object(yr_weather_plugin, "is_running", return_value=False):
            await yr_weather_plugin.configure({
                "latitude": 60.1699,
                "longitude": 24.9384,
                "altitude": 10,
                "forecast_days": 7,
                "location": "Helsinki, Finland",
            })

            assert yr_weather_plugin.latitude == 60.1699
            assert yr_weather_plugin.longitude == 24.9384
            assert yr_weather_plugin.altitude == 10
            assert yr_weather_plugin.forecast_days == 7
            assert yr_weather_plugin.location == "Helsinki, Finland"

    @pytest.mark.asyncio
    async def test_configure_forecast_days_clamping(self, yr_weather_plugin):
        """Test that forecast_days is clamped during configure."""
        await yr_weather_plugin.initialize()
        
        with patch.object(yr_weather_plugin, "is_running", return_value=False):
            # Too large
            await yr_weather_plugin.configure({"forecast_days": 15})
            assert yr_weather_plugin.forecast_days == 9

            # Too small
            await yr_weather_plugin.configure({"forecast_days": 0})
            assert yr_weather_plugin.forecast_days == 1

    @pytest.mark.asyncio
    async def test_get_content(self, yr_weather_plugin):
        """Test getting service content."""
        content = await yr_weather_plugin.get_content()
        assert content["type"] == "weather"
        assert "url" in content
        assert "data" in content
        assert content["data"]["latitude"] == 59.9139
        assert content["data"]["longitude"] == 10.7522


@pytest.mark.asyncio
class TestYrWeatherPluginHooks:
    """Tests for Yr.no Weather plugin hooks."""

    @pytest.mark.skip(reason="Backend-dependent hook test. Run from backend/tests/unit/test_plugin_hooks.py instead.")
    async def test_handle_plugin_config_update(self, test_db):
        """Test handle_plugin_config_update hook.
        
        Note: This test requires backend fixtures (test_db). 
        Run the hook integration test from backend/tests/unit/test_plugin_hooks.py instead:
        
            pytest backend/tests/unit/test_plugin_hooks.py::TestPluginHooks::test_yr_weather_handle_plugin_config_update
        """
        pytest.skip("Backend-dependent hook test. Run from backend/tests/unit/test_plugin_hooks.py instead.")

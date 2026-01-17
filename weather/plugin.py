"""Weather service plugin using OpenWeatherMap API."""

import hashlib
from typing import Any

import httpx
from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_str, to_int
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)

# Loguru automatically includes module/function info in logs


class WeatherServicePlugin(ServicePlugin):
    """Weather service plugin for displaying current conditions and forecast."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "weather",
            "plugin_type": PluginType.SERVICE,
            "name": "Weather",
            "description": "Display current weather conditions and forecast from OpenWeatherMap",
            "version": "1.0.0",
            "common_config_schema": {
                "api_key": {
                    "type": "password",
                    "description": "OpenWeatherMap API key",
                    "default": "",
                    "global_only": True,  # This field is global, not instance-specific
                    "ui": {
                        "component": "password",
                        "placeholder": "Enter your OpenWeatherMap API key",
                        "help_text": "Get a free API key at https://openweathermap.org/api",
                        "validation": {
                            "required": True,
                        },
                    },
                },
                "display_order": {
                    "type": "integer",
                    "description": "Display order for service instances",
                    "default": 0,
                    "ui": {
                        "component": "number",
                        "help_text": (
                            "Order for display/switching (lower numbers appear first). "
                            "This applies to all instances of this plugin type."
                        ),
                        "validation": {
                            "min": 0,
                        },
                    },
                },
            },
            "instance_config_schema": {
                "location": {
                    "type": "string",
                    "description": "Location (city name, state code, country code)",
                    "default": "",
                    "ui": {
                        "component": "input",
                        "placeholder": "London, UK or New York, US",
                        "help_text": "City name with optional state/country code (e.g., 'London, UK' or 'New York, US')",  # noqa: E501
                        "validation": {
                            "required": True,
                        },
                    },
                },
                "units": {
                    "type": "string",
                    "description": "Temperature units",
                    "default": "metric",
                    "ui": {
                        "component": "select",
                        "options": [
                            {"value": "metric", "label": "Metric (°C)"},
                            {"value": "imperial", "label": "Imperial (°F)"},
                            {"value": "kelvin", "label": "Kelvin (K)"},
                        ],
                        "help_text": "Temperature unit system",
                    },
                },
                "forecast_days": {
                    "type": "integer",
                    "description": "Number of forecast days to show (1-5)",
                    "default": 3,
                    "ui": {
                        "component": "number",
                        "placeholder": "3",
                        "help_text": "Number of days to show in forecast (1-5 days)",
                        "validation": {
                            "min": 1,
                            "max": 5,
                        },
                    },
                },
                "fullscreen": {
                    "type": "boolean",
                    "description": "Prefer fullscreen mode",
                    "default": False,
                    "ui": {
                        "component": "checkbox",
                        "help_text": "Open this service in fullscreen by default",
                    },
                },
            },
            "ui_actions": [
                {
                    "id": "save",
                    "type": "save",
                    "label": "Save Settings",
                    "style": "primary",
                },
                {
                    "id": "test",
                    "type": "test",
                    "label": "Test Connection",
                    "style": "secondary",
                },
            ],
            "display_schema": {
                "type": "api",
                "api_endpoint": "/api/plugins/{service_id}/data",
                "method": "GET",
                "data_schema": {
                    "current": {
                        "type": "object",
                        "description": "Current weather conditions",
                        "properties": {
                            "temperature": {"type": "number"},
                            "feels_like": {"type": "number"},
                            "humidity": {"type": "number"},
                            "pressure": {"type": "number"},
                            "description": {"type": "string"},
                            "icon": {"type": "string"},
                            "wind_speed": {"type": "number"},
                            "wind_direction": {"type": "number"},
                        },
                    },
                    "forecast": {
                        "type": "array",
                        "description": "Weather forecast",
                        "item_schema": {
                            "date": {"type": "string", "format": "date"},
                            "temperature": {"type": "number"},
                            "temp_min": {"type": "number"},
                            "temp_max": {"type": "number"},
                            "description": {"type": "string"},
                            "icon": {"type": "string"},
                        },
                    },
                    "location": {"type": "string"},
                    "units": {"type": "string"},
                },
                "render_template": "weather",
            },
            "supports_multiple_instances": True,  # Multi-instance plugin
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        api_key: str,
        location: str,
        units: str = "metric",
        forecast_days: int = 3,
        enabled: bool = True,
        display_order: int = 0,
        fullscreen: bool = False,
    ):
        """
        Initialize Weather service plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            api_key: OpenWeatherMap API key
            location: Location (city name, state code, country code)
            units: Temperature units (metric, imperial, kelvin)
            forecast_days: Number of forecast days to show (1-5)
            enabled: Whether the plugin is enabled
            display_order: Display order for service rotation
            fullscreen: Whether to display in fullscreen mode
        """
        super().__init__(plugin_id, name, enabled)
        self.api_key = api_key
        self.location = location
        self.units = units
        self.forecast_days = min(max(forecast_days, 1), 5)  # Clamp between 1 and 5
        self.display_order = display_order
        self.fullscreen = fullscreen
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize the plugin."""
        # Validate API key
        if not self.api_key or not self.api_key.strip():
            raise ValueError("OpenWeatherMap API key is required")

        # Validate location
        if not self.location or not self.location.strip():
            raise ValueError("Location is required")

        # Create HTTP client
        self._client = httpx.AsyncClient(
            base_url="https://api.openweathermap.org/data/2.5",
            timeout=30.0,
        )

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_content(self) -> dict[str, Any]:
        """
        Get service content for display.

        Returns:
            Dictionary with content information
        """
        # Return a special URL that points to our backend endpoint
        weather_api_url = f"/api/plugins/{self.plugin_id}/data"

        return {
            "type": "weather",
            "url": weather_api_url,
            "data": {
                "api_key": self.api_key,  # Not sent to frontend, used by backend
                "location": self.location,
                "units": self.units,
            },
            "config": {
                "allowFullscreen": True,
            },
        }

    def get_config(self) -> dict[str, Any]:
        """
        Get plugin configuration.

        Returns:
            Configuration dictionary
        """
        weather_api_url = f"/api/plugins/{self.plugin_id}/data"
        return {
            "url": weather_api_url,
            "api_key": self.api_key,
            "location": self.location,
            "units": self.units,
            "forecast_days": self.forecast_days,
            "display_order": self.display_order,
            "fullscreen": self.fullscreen,
        }

    async def fetch_service_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch weather data from OpenWeatherMap API (protocol-defined method).

        Args:
            start_date: Not used for weather (kept for protocol compatibility)
            end_date: Not used for weather (kept for protocol compatibility)

        Returns:
            Dictionary with weather data in format compatible with WeatherWidget
        """
        return await self._fetch_weather()

    async def _fetch_weather(self) -> dict[str, Any]:
        """
        Fetch weather data from OpenWeatherMap API.

        Returns:
            Dictionary with weather data
        """
        if not self._client:
            await self.initialize()

        try:
            # Fetch current weather
            current_params = {
                "q": self.location,
                "appid": self.api_key,
                "units": self.units,
            }

            current_response = await self._client.get("/weather", params=current_params)
            current_response.raise_for_status()
            current_data = current_response.json()

            # Fetch forecast
            forecast_params = {
                "q": self.location,
                "appid": self.api_key,
                "units": self.units,
                "cnt": self.forecast_days * 8,  # 8 forecasts per day (3-hour intervals)
            }

            forecast_response = await self._client.get("/forecast", params=forecast_params)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            # Process current weather
            current = {
                "temperature": current_data["main"]["temp"],
                "feels_like": current_data["main"]["feels_like"],
                "humidity": current_data["main"]["humidity"],
                "pressure": current_data["main"]["pressure"],
                "description": current_data["weather"][0]["description"],
                "icon": current_data["weather"][0]["icon"],
                "wind_speed": current_data.get("wind", {}).get("speed", 0),
                "wind_direction": current_data.get("wind", {}).get("deg", 0),
            }

            # Process forecast - group by day and get daily min/max
            from collections import defaultdict
            from datetime import datetime, timedelta

            forecast_by_date = defaultdict(lambda: {"temps": [], "descriptions": [], "icons": []})

            for item in forecast_data.get("list", []):
                dt = datetime.fromtimestamp(item["dt"])
                date_str = dt.date().isoformat()

                forecast_by_date[date_str]["temps"].append(item["main"]["temp"])
                forecast_by_date[date_str]["descriptions"].append(item["weather"][0]["description"])
                forecast_by_date[date_str]["icons"].append(item["weather"][0]["icon"])

            # Build forecast list (limit to forecast_days)
            forecast = []
            today = datetime.now().date()
            for i in range(1, self.forecast_days + 1):
                forecast_date = today + timedelta(days=i)
                date_str = forecast_date.isoformat()

                if date_str in forecast_by_date:
                    day_data = forecast_by_date[date_str]
                    forecast.append(
                        {
                            "date": date_str,
                            "temperature": sum(day_data["temps"]) / len(day_data["temps"]),
                            "temp_min": min(day_data["temps"]),
                            "temp_max": max(day_data["temps"]),
                            "description": day_data["descriptions"][0],  # Use first description
                            "icon": day_data["icons"][0],  # Use first icon
                        }
                    )

            location_name = (
                f"{current_data['name']}, {current_data.get('sys', {}).get('country', '')}"
            )

            return {
                "current": current,
                "forecast": forecast,
                "location": location_name,
                "units": self.units,
            }

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching weather: {} - {}", e.response.status_code, e)
            return {
                "error": f"HTTP error: {e.response.status_code}",
                "message": e.response.text if hasattr(e.response, "text") else str(e),
            }
        except httpx.HTTPError as e:
            logger.exception("Error fetching weather")
            return {
                "error": str(e),
            }
        except Exception as e:
            logger.exception("Unexpected error fetching weather")
            return {
                "error": str(e),
            }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """
        Validate plugin configuration.

        Args:
            config: Configuration dictionary

        Returns:
            True if configuration is valid
        """
        # Check if required keys exist
        if "api_key" not in config or "location" not in config:
            return False

        api_key = extract_config_value(config, "api_key", converter=to_str)
        location = extract_config_value(config, "location", converter=to_str)

        if not api_key or not api_key.strip():
            return False

        if not location or not location.strip():
            return False

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with new settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)

        # Close existing client if any
        if self._client:
            await self._client.aclose()

        api_key = extract_config_value(config, "api_key", converter=to_str)
        location = extract_config_value(config, "location", converter=to_str)
        units = extract_config_value(config, "units", default="metric", converter=to_str)
        forecast_days = extract_config_value(config, "forecast_days", default=3, converter=to_int)
        display_order = extract_config_value(config, "display_order", default=0, converter=to_int)
        fullscreen = extract_config_value(config, "fullscreen", default=False)

        if api_key is not None:
            self.api_key = str(api_key).strip()
        if location is not None:
            self.location = str(location).strip()
        if units is not None:
            self.units = str(units).strip() or "metric"
        if forecast_days is not None:
            self.forecast_days = min(max(int(forecast_days), 1), 5)
        if display_order is not None:
            self.display_order = int(display_order)
        if fullscreen is not None:
            self.fullscreen = bool(fullscreen)

        # Reinitialize with new config
        await self.initialize()


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register WeatherServicePlugin type."""
    return [WeatherServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> WeatherServicePlugin | None:
    """Create a WeatherServicePlugin instance."""
    if type_id != "weather":
        return None

    enabled = config.get("enabled", False)  # Default to disabled
    display_order = extract_config_value(config, "display_order", default=0, converter=to_int)
    fullscreen = extract_config_value(config, "fullscreen", default=False)

    # Extract config values
    api_key = extract_config_value(config, "api_key", default="", converter=to_str)
    location = extract_config_value(config, "location", default="", converter=to_str)
    units = extract_config_value(config, "units", default="metric", converter=to_str)
    forecast_days = extract_config_value(config, "forecast_days", default=3, converter=to_int)

    # Clean up values
    api_key = str(api_key).strip() if api_key else ""
    location = str(location).strip() if location else ""
    units = str(units).strip() if units else "metric"
    forecast_days = min(max(int(forecast_days), 1), 5) if forecast_days else 3

    return WeatherServicePlugin(
        plugin_id=plugin_id,
        name=name,
        api_key=api_key,
        location=location,
        units=units,
        forecast_days=forecast_days,
        enabled=enabled,
        display_order=display_order,
        fullscreen=fullscreen,
    )


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle Weather plugin configuration update and instance management."""
    if type_id != "weather":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        api_key = extract_config_value(c, "api_key", converter=to_str)
        location = extract_config_value(c, "location", converter=to_str)
        units = extract_config_value(c, "units", default="metric", converter=to_str)
        forecast_days = extract_config_value(c, "forecast_days", default=3, converter=to_int)
        display_order = extract_config_value(c, "display_order", default=0, converter=to_int)
        fullscreen = extract_config_value(c, "fullscreen", default=False)

        return {
            "api_key": str(api_key).strip() if api_key else "",
            "location": str(location).strip() if location else "",
            "units": str(units).strip() if units else "metric",
            "forecast_days": min(max(int(forecast_days), 1), 5) if forecast_days else 3,
            "display_order": display_order or 0,
            "fullscreen": fullscreen or False,
        }

    def validate_config(c: dict[str, Any]) -> bool:
        """Validate config has required api_key and location."""
        # Check if required keys exist
        if "api_key" not in c or "location" not in c:
            return False

        api_key = extract_config_value(c, "api_key", converter=to_str)
        location = extract_config_value(c, "location", converter=to_str)

        if not api_key or not api_key.strip():
            return False

        if not location or not location.strip():
            return False

        return True

    def generate_instance_id(c: dict[str, Any], t: str) -> str:
        """Generate instance ID from location."""
        location = extract_config_value(c, "location", converter=to_str)
        if location:
            # Generate hash from location (same instance for same location)
            loc_hash = hashlib.md5(location.encode()).hexdigest()[:8]
            return f"{t}-{loc_hash}"
        # Fallback ID if location not available
        return f"{t}-instance"

    manager_config = InstanceManagerConfig(
        type_id="weather",
        single_instance=False,  # Multi-instance plugin
        normalize_config=normalize_config,
        validate_config=validate_config,
        generate_instance_id=generate_instance_id,
        default_instance_name="Weather",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )

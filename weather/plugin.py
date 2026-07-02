"""Weather service plugin using the OpenWeatherMap API.

Calvin plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, a kind-based `display_schema` /
`statusbar_schema`, and `fetch()` as the single data verb. There are no
module-level hooks — the host discovers this class and derives everything
else from `metadata`.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin

# OpenWeatherMap icon codes -> Calvin weather icon ids. The weather-forecast
# renderer resolves these via frontend/src/utils/weatherIcons.js — only
# `mdi:weather-*` identifiers listed there render; anything else falls back
# to the cloudy glyph.
OWM_ICON_TO_MDI = {
    "01d": "mdi:weather-sunny",
    "01n": "mdi:weather-night",
    "02d": "mdi:weather-partly-cloudy",
    "02n": "mdi:weather-partly-cloudy",
    "03d": "mdi:weather-cloudy",
    "03n": "mdi:weather-cloudy",
    "04d": "mdi:weather-cloudy",
    "04n": "mdi:weather-cloudy",
    "09d": "mdi:weather-pouring",
    "09n": "mdi:weather-pouring",
    "10d": "mdi:weather-rainy",
    "10n": "mdi:weather-rainy",
    "11d": "mdi:weather-lightning",
    "11n": "mdi:weather-lightning",
    "13d": "mdi:weather-snowy",
    "13n": "mdi:weather-snowy",
    "50d": "mdi:weather-fog",
    "50n": "mdi:weather-fog",
}

# Compact text glyphs for the statusbar `status` renderer, which displays the
# icon string literally (it is not an mdi lookup).
MDI_TO_GLYPH = {
    "mdi:weather-sunny": "☀️",
    "mdi:weather-night": "🌙",
    "mdi:weather-partly-cloudy": "⛅",
    "mdi:weather-cloudy": "☁️",
    "mdi:weather-rainy": "🌧️",
    "mdi:weather-pouring": "🌧️",
    "mdi:weather-snowy": "❄️",
    "mdi:weather-lightning": "⛈️",
    "mdi:weather-fog": "🌫️",
    "mdi:weather-windy": "💨",
}

# OWM wind speed is m/s for metric/standard and mph for imperial; the payload
# always carries m/s so the display schema can declare one wind unit.
_MPH_TO_MS = 0.44704


def _owm_icon(code: str | None) -> str:
    return OWM_ICON_TO_MDI.get(str(code or ""), "mdi:weather-cloudy")


def _glyph(mdi_icon: str) -> str:
    return MDI_TO_GLYPH.get(mdi_icon, "☁️")


class WeatherServicePlugin(ServicePlugin):
    """Weather service plugin for displaying current conditions and forecast."""

    metadata = PluginMetadata(
        type_id="weather",
        name="Weather",
        description="Display current weather conditions and forecast from OpenWeatherMap",
        default_instance_name="Weather",
        instance_label="Location",
        # Same location -> same instance
        instance_identity=["location"],
        common_config_schema={
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
        },
        instance_config_schema={
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
            "show_in_statusbar": {
                "type": "boolean",
                "description": "Show temperature in the clock bar",
                "default": False,
                "ui": {
                    "component": "checkbox",
                    "help_text": "Display current temperature next to the clock",
                },
            },
        },
        ui_actions=[
            {
                "id": "save",
                "type": "save",
                "label": "Save Settings",
                "style": "primary",
                "scope": "global",
            },
            {
                "id": "test",
                "type": "test",
                "label": "Test Connection",
                "style": "secondary",
                "scope": "instance",
            },
        ],
        # The payload from fetch() feeds the built-in weather-forecast renderer.
        display_schema={
            "kind": "weather-forecast",
            "current_path": "$.current",
            "forecast_path": "$.forecast",
            "current": {
                "temperature_path": "$.temperature",
                "description_path": "$.description",
                "icon_path": "$.icon",
                "feels_like_path": "$.feels_like",
                "humidity_path": "$.humidity",
                "pressure_path": "$.pressure",
                "wind_speed_path": "$.wind_speed",
            },
            "forecast": {
                "date_path": "$.date",
                "icon_path": "$.icon",
                "temp_min_path": "$.temp_min",
                "temp_max_path": "$.temp_max",
                "description_path": "$.description",
            },
            # The unit system is per-instance config, but the schema is
            # class-level — "°" is unit-agnostic; wind is normalized to m/s
            # in fetch().
            "units": {"temperature": "°", "wind": "m/s"},
            "poll_interval_ms": 1800000,
        },
        # Statusbar item: condition glyph + current temperature, bound to the
        # same fetch() payload.
        statusbar_schema={
            "kind": "status",
            "item": {
                "icon_path": "$.current.glyph",
                "value_path": "$.current.temperature",
                "unit": "°",
            },
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._client: httpx.AsyncClient | None = None

    # Config accessors — values live in self.config (schema-normalized);
    # these apply the trims/clamps the wire format doesn't guarantee.

    @property
    def api_key(self) -> str:
        return str(self.config.get("api_key") or "").strip()

    @property
    def location(self) -> str:
        return str(self.config.get("location") or "").strip()

    @property
    def units(self) -> str:
        return str(self.config.get("units") or "").strip() or "metric"

    @property
    def forecast_days(self) -> int:
        return min(max(int(self.config.get("forecast_days") or 3), 1), 5)

    async def initialize(self) -> None:
        """Validate config and create the HTTP client."""
        if not self.api_key:
            raise ValueError("OpenWeatherMap API key is required")
        if not self.location:
            raise ValueError("Location is required")

        self._client = httpx.AsyncClient(
            base_url="https://api.openweathermap.org/data/2.5",
            timeout=30.0,
        )

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration; drop the client so it's rebuilt with new settings."""
        await super().configure(config)
        if self._client:
            await self._client.aclose()
            self._client = None

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require an API key and a location."""
        normalized = cls.normalize_config(config)
        api_key = str(normalized.get("api_key") or "").strip()
        location = str(normalized.get("location") or "").strip()
        return bool(api_key and location)

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch weather data and shape it for the weather-forecast display schema.

        Args:
            start_date: Not used for weather (kept for protocol compatibility)
            end_date: Not used for weather (kept for protocol compatibility)

        Returns:
            {"current": {...}, "forecast": [...], "location", "units"} on
            success; {"error", "message"?} on failure.
        """
        if not self._client:
            await self.initialize()

        try:
            common_params = {
                "q": self.location,
                "appid": self.api_key,
                "units": self.units,
            }

            current_response = await self._client.get("/weather", params=common_params)
            current_response.raise_for_status()

            forecast_response = await self._client.get(
                "/forecast",
                params={
                    **common_params,
                    # 8 forecasts per day (3-hour intervals)
                    "cnt": self.forecast_days * 8,
                },
            )
            forecast_response.raise_for_status()

            return self._shape_for_display(current_response.json(), forecast_response.json())

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching weather: {} - {}", e.response.status_code, e)
            return {
                "error": f"HTTP error: {e.response.status_code}",
                "message": e.response.text if hasattr(e.response, "text") else str(e),
            }
        except httpx.HTTPError as e:
            logger.exception("Error fetching weather")
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Unexpected error fetching weather")
            return {"error": str(e)}

    def _shape_for_display(
        self,
        current_data: dict[str, Any],
        forecast_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Shape raw OpenWeatherMap responses into the display-schema payload."""
        icon = _owm_icon(current_data["weather"][0].get("icon"))
        wind_speed = current_data.get("wind", {}).get("speed", 0)
        current = {
            "temperature": round(current_data["main"]["temp"]),
            "feels_like": round(current_data["main"]["feels_like"]),
            "humidity": current_data["main"]["humidity"],
            "pressure": current_data["main"]["pressure"],
            "description": current_data["weather"][0]["description"],
            "icon": icon,
            "glyph": _glyph(icon),
            "wind_speed": self._wind_to_ms(wind_speed),
            "wind_direction": current_data.get("wind", {}).get("deg", 0),
        }

        # Group 3-hourly forecast entries by day for daily min/max.
        forecast_by_date: dict[str, dict[str, list]] = defaultdict(
            lambda: {"temps": [], "descriptions": [], "icons": []}
        )
        for item in forecast_data.get("list", []):
            date_str = datetime.fromtimestamp(item["dt"]).date().isoformat()
            forecast_by_date[date_str]["temps"].append(item["main"]["temp"])
            forecast_by_date[date_str]["descriptions"].append(item["weather"][0]["description"])
            forecast_by_date[date_str]["icons"].append(item["weather"][0]["icon"])

        forecast = []
        today = datetime.now().date()
        for i in range(1, self.forecast_days + 1):
            date_str = (today + timedelta(days=i)).isoformat()
            if date_str not in forecast_by_date:
                continue
            day_data = forecast_by_date[date_str]
            forecast.append(
                {
                    "date": date_str,
                    "temperature": sum(day_data["temps"]) / len(day_data["temps"]),
                    "temp_min": min(day_data["temps"]),
                    "temp_max": max(day_data["temps"]),
                    "description": day_data["descriptions"][0],
                    "icon": _owm_icon(day_data["icons"][0]),
                }
            )

        location_name = (
            f"{current_data.get('name', self.location)}, "
            f"{current_data.get('sys', {}).get('country', '')}"
        ).rstrip(", ")

        return {
            "current": current,
            "forecast": forecast,
            "location": location_name,
            "units": self.units,
        }

    def _wind_to_ms(self, wind_speed: float) -> float:
        """Normalize OWM wind speed to m/s (imperial responses are mph)."""
        if self.units == "imperial":
            return wind_speed * _MPH_TO_MS
        return wind_speed

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Test OpenWeatherMap connectivity for the configured location."""
        normalized = cls.normalize_config(config)
        api_key = str(normalized.get("api_key") or "").strip()
        location = str(normalized.get("location") or "").strip()
        units = str(normalized.get("units") or "").strip() or "metric"

        if not api_key or not location:
            return {
                "success": False,
                "message": "OpenWeatherMap API key and location are required.",
            }

        try:
            async with httpx.AsyncClient(
                base_url="https://api.openweathermap.org/data/2.5",
                timeout=10.0,
            ) as client:
                response = await client.get(
                    "/weather",
                    params={
                        "q": location,
                        "appid": api_key,
                        "units": units,
                    },
                )

            if response.status_code == 200:
                data = response.json()
                location_name = data.get("name", location)
                country = data.get("sys", {}).get("country", "")
                resolved_location = f"{location_name}, {country}" if country else location_name
                description = data.get("weather", [{}])[0].get("description", "unknown conditions")
                temperature = data.get("main", {}).get("temp")
                temp_suffix = (
                    f" Current temperature: {round(temperature)}°."
                    if temperature is not None
                    else ""
                )
                return {
                    "success": True,
                    "message": (
                        f"Connected successfully. Resolved location: {resolved_location}. "
                        f"Weather: {description}.{temp_suffix}"
                    ),
                }

            if response.status_code == 401:
                return {
                    "success": False,
                    "message": "Authentication failed. Check your OpenWeatherMap API key.",
                }

            if response.status_code == 404:
                return {
                    "success": False,
                    "message": f"Location '{location}' was not found by OpenWeatherMap.",
                }

            return {
                "success": False,
                "message": f"OpenWeatherMap returned status {response.status_code}.",
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Connection to OpenWeatherMap timed out.",
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "Could not connect to OpenWeatherMap.",
            }
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"Network error: {str(e)}",
            }
        except Exception as e:
            logger.exception("Unexpected error testing weather plugin connection")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
            }

"""Yr.no weather service plugin using the MET Norway Weather API.

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

_USER_AGENT = "Calvin-Dashboard/1.0 (https://github.com/osterbergsimon/calvin)"

# Yr.no symbol codes -> Calvin weather icon ids. The weather-forecast renderer
# resolves these via frontend/src/utils/weatherIcons.js — only `mdi:weather-*`
# identifiers listed there render; anything else falls back to the cloudy
# glyph. See https://api.met.no/weatherapi/weathericon/2.0/documentation
SYMBOL_TO_ICON = {
    # Clear sky
    "clearsky_day": "mdi:weather-sunny",
    "clearsky_polartwilight": "mdi:weather-sunny",
    "clearsky_night": "mdi:weather-night",
    # Fair
    "fair_day": "mdi:weather-partly-cloudy",
    "fair_polartwilight": "mdi:weather-partly-cloudy",
    "fair_night": "mdi:weather-partly-cloudy",
    # Partly cloudy
    "partlycloudy_day": "mdi:weather-partly-cloudy",
    "partlycloudy_polartwilight": "mdi:weather-partly-cloudy",
    "partlycloudy_night": "mdi:weather-partly-cloudy",
    # Cloudy
    "cloudy": "mdi:weather-cloudy",
    # Rain
    "rainshowers_day": "mdi:weather-pouring",
    "rainshowers_polartwilight": "mdi:weather-pouring",
    "rainshowers_night": "mdi:weather-pouring",
    "rain": "mdi:weather-rainy",
    "heavyrain": "mdi:weather-pouring",
    "heavyrainshowers_day": "mdi:weather-pouring",
    "heavyrainshowers_polartwilight": "mdi:weather-pouring",
    "heavyrainshowers_night": "mdi:weather-pouring",
    # Sleet
    "sleet": "mdi:weather-snowy",
    "sleetshowers_day": "mdi:weather-snowy",
    "sleetshowers_polartwilight": "mdi:weather-snowy",
    "sleetshowers_night": "mdi:weather-snowy",
    # Snow
    "snow": "mdi:weather-snowy",
    "snowshowers_day": "mdi:weather-snowy",
    "snowshowers_polartwilight": "mdi:weather-snowy",
    "snowshowers_night": "mdi:weather-snowy",
    "heavysnow": "mdi:weather-snowy",
    "heavysnowshowers_day": "mdi:weather-snowy",
    "heavysnowshowers_polartwilight": "mdi:weather-snowy",
    "heavysnowshowers_night": "mdi:weather-snowy",
    # Fog
    "fog": "mdi:weather-fog",
    # Thunder
    "rainshowersandthunder_day": "mdi:weather-lightning",
    "rainshowersandthunder_polartwilight": "mdi:weather-lightning",
    "rainshowersandthunder_night": "mdi:weather-lightning",
    "thunder": "mdi:weather-lightning",
    "heavyrainshowersandthunder_day": "mdi:weather-lightning",
    "heavyrainshowersandthunder_polartwilight": "mdi:weather-lightning",
    "heavyrainshowersandthunder_night": "mdi:weather-lightning",
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

_DESCRIPTIONS = {
    "clearsky": "clear sky",
    "fair": "fair",
    "partlycloudy": "partly cloudy",
    "cloudy": "cloudy",
    "rainshowers": "rain showers",
    "rain": "rain",
    "heavyrain": "heavy rain",
    "heavyrainshowers": "heavy rain showers",
    "sleet": "sleet",
    "sleetshowers": "sleet showers",
    "snow": "snow",
    "snowshowers": "snow showers",
    "heavysnow": "heavy snow",
    "heavysnowshowers": "heavy snow showers",
    "fog": "fog",
    "rainshowersandthunder": "rain showers and thunder",
    "thunder": "thunder",
    "heavyrainshowersandthunder": "heavy rain showers and thunder",
}


def _symbol_icon(symbol_code: str | None) -> str:
    return SYMBOL_TO_ICON.get(str(symbol_code or ""), "mdi:weather-cloudy")


def _glyph(mdi_icon: str) -> str:
    return MDI_TO_GLYPH.get(mdi_icon, "☁️")


def _symbol_description(symbol_code: str) -> str:
    """Convert a Yr.no symbol code to a human-readable description."""
    base_code = (
        symbol_code.replace("_day", "").replace("_night", "").replace("_polartwilight", "")
    )
    return _DESCRIPTIONS.get(base_code, "unknown")


class YrWeatherServicePlugin(ServicePlugin):
    """Yr.no weather service plugin for displaying current conditions and forecast."""

    metadata = PluginMetadata(
        type_id="yr_weather",
        name="Yr.no Weather",
        description=(
            "Display current weather conditions and forecast from Yr.no "
            "(Norwegian Meteorological Institute)"
        ),
        default_instance_name="Yr.no Weather",
        instance_label="Location",
        # Same coordinates -> same instance
        instance_identity=["latitude", "longitude"],
        instance_config_schema={
            "location": {
                "type": "string",
                "description": "Location name (city, address, etc.)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Oslo, Norway or London, UK",
                    "help_text": "Enter a city name or address to automatically get coordinates. Or enter coordinates manually below.",  # noqa: E501
                },
            },
            "latitude": {
                "type": "number",
                "description": "Latitude (decimal degrees, max 4 decimals)",
                # No default: an unconfigured coordinate must read as "unset" so
                # merely enabling the plugin type can't auto-create a phantom
                # instance. See validate_config. (calvin-8p0)
                "ui": {
                    "component": "number",
                    "placeholder": "59.9139",
                    "help_text": "Latitude in decimal degrees. Will be auto-filled when using location search above.",  # noqa: E501
                    "validation": {
                        "required": True,
                        "min": -90,
                        "max": 90,
                    },
                },
            },
            "longitude": {
                "type": "number",
                "description": "Longitude (decimal degrees, max 4 decimals)",
                # No default — see latitude above. (calvin-8p0)
                "ui": {
                    "component": "number",
                    "placeholder": "10.7522",
                    "help_text": "Longitude in decimal degrees. Will be auto-filled when using location search above.",  # noqa: E501
                    "validation": {
                        "required": True,
                        "min": -180,
                        "max": 180,
                    },
                },
            },
            "altitude": {
                "type": "integer",
                "description": "Altitude in meters (optional, defaults to sea level)",
                "default": 0,
                "ui": {
                    "component": "number",
                    "placeholder": "0",
                    "help_text": "Altitude above sea level in meters (optional)",
                    "validation": {
                        "min": 0,
                    },
                },
            },
            "forecast_days": {
                "type": "integer",
                "description": "Number of forecast days to show (1-9)",
                "default": 5,
                "ui": {
                    "component": "number",
                    "placeholder": "5",
                    "help_text": "Number of days to show in forecast (1-9 days, Yr.no provides up to 9 days)",  # noqa: E501
                    "validation": {
                        "min": 1,
                        "max": 9,
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
                "scope": "instance",
            },
            {
                "id": "test",
                "type": "test",
                "label": "Test Connection",
                "style": "secondary",
                "scope": "instance",
            },
            # Declares the host /geocode endpoint (location -> coordinates);
            # the route is gated on this action.
            {
                "id": "geocode",
                "type": "geocode",
                "label": "Look up coordinates",
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
            # Yr.no is always metric.
            "units": {"temperature": "°C", "wind": "m/s"},
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
    # these apply the rounding/clamps the wire format doesn't guarantee.

    @property
    def latitude(self) -> float:
        # Round to 4 decimals as per API requirements
        return round(float(self.config.get("latitude") or 59.9139), 4)

    @property
    def longitude(self) -> float:
        return round(float(self.config.get("longitude") or 10.7522), 4)

    @property
    def altitude(self) -> int:
        return int(self.config.get("altitude") or 0)

    @property
    def forecast_days(self) -> int:
        return min(max(int(self.config.get("forecast_days") or 5), 1), 9)

    @property
    def location(self) -> str | None:
        return str(self.config.get("location") or "").strip() or None

    async def initialize(self) -> None:
        """Validate coordinates and create the HTTP client."""
        if not (-90 <= self.latitude <= 90):
            raise ValueError(f"Invalid latitude: {self.latitude} (must be between -90 and 90)")
        if not (-180 <= self.longitude <= 180):
            raise ValueError(f"Invalid longitude: {self.longitude} (must be between -180 and 180)")

        # Per Yr.no terms of service, we must identify ourselves.
        self._client = httpx.AsyncClient(
            base_url="https://api.met.no/weatherapi/locationforecast/2.0",
            headers={"User-Agent": _USER_AGENT},
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
        """Require real, in-range coordinates.

        The schema declares no lat/lon defaults, so an unconfigured instance
        normalizes to 0.0/0.0 (``to_float(None)``). Because the host normalizes
        config *before* calling this hook, a key-presence check alone can't tell
        "user supplied coordinates" from "defaults filled in" — so we reject the
        0/0 sentinel (Null Island, never a real dashboard location). That stops a
        bare plugin-type enable from auto-creating a phantom instance. A genuine
        equator/meridian location (one axis 0, the other not) still passes.
        (calvin-8p0)
        """
        if "latitude" not in config or "longitude" not in config:
            return False
        normalized = cls.normalize_config(config)
        latitude = normalized.get("latitude")
        longitude = normalized.get("longitude")
        if latitude is None or longitude is None:
            return False
        if float(latitude) == 0.0 and float(longitude) == 0.0:
            return False
        return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180

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
            params: dict[str, Any] = {
                "lat": self.latitude,
                "lon": self.longitude,
            }
            if self.altitude > 0:
                params["altitude"] = self.altitude

            response = await self._client.get("/compact", params=params)
            response.raise_for_status()
            return self._shape_for_display(response.json())

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

    def _shape_for_display(self, data: dict[str, Any]) -> dict[str, Any]:
        """Shape a raw Yr.no locationforecast response into the display-schema payload."""
        # Structure: { "properties": { "timeseries": [...] } }
        timeseries = data.get("properties", {}).get("timeseries", [])
        if not timeseries:
            return {"error": "No weather data available"}

        # Current weather: first entry in the timeseries.
        current_entry = timeseries[0]
        instant = current_entry.get("data", {}).get("instant", {}).get("details", {})
        symbol_code = self._entry_symbol_code(current_entry)
        icon = _symbol_icon(symbol_code)

        current = {
            "temperature": round(instant.get("air_temperature", 0)),
            # Yr.no doesn't provide feels_like; use air temperature.
            "feels_like": round(instant.get("air_temperature", 0)),
            "humidity": instant.get("relative_humidity", 0),
            # air_pressure_at_sea_level is already hPa.
            "pressure": instant.get("air_pressure_at_sea_level", 0),
            "description": _symbol_description(symbol_code),
            "icon": icon,
            "glyph": _glyph(icon),
            "wind_speed": instant.get("wind_speed", 0),
            "wind_direction": instant.get("wind_from_direction", 0),
        }

        # Group hourly entries by day for daily min/max.
        forecast_by_date: dict[str, dict[str, list]] = defaultdict(
            lambda: {"temps": [], "symbols": []}
        )
        today = datetime.now().date()
        for entry in timeseries:
            time_str = entry.get("time", "")
            if not time_str:
                continue
            entry_date = datetime.fromisoformat(time_str.replace("Z", "+00:00")).date()
            days_ahead = (entry_date - today).days
            if days_ahead < 1 or days_ahead > self.forecast_days:
                continue

            temp = entry.get("data", {}).get("instant", {}).get("details", {}).get(
                "air_temperature"
            )
            if temp is None:
                continue
            date_str = entry_date.isoformat()
            forecast_by_date[date_str]["temps"].append(temp)
            forecast_by_date[date_str]["symbols"].append(self._entry_symbol_code(entry))

        forecast = []
        for i in range(1, self.forecast_days + 1):
            date_str = (today + timedelta(days=i)).isoformat()
            day_data = forecast_by_date.get(date_str)
            if not day_data or not day_data["temps"]:
                continue
            day_symbol = day_data["symbols"][0]
            forecast.append(
                {
                    "date": date_str,
                    "temperature": sum(day_data["temps"]) / len(day_data["temps"]),
                    "temp_min": min(day_data["temps"]),
                    "temp_max": max(day_data["temps"]),
                    "description": _symbol_description(day_symbol),
                    "icon": _symbol_icon(day_symbol),
                }
            )

        location_name = self.location or f"Lat {self.latitude}, Lon {self.longitude}"

        return {
            "current": current,
            "forecast": forecast,
            "location": location_name,
            "units": "metric",  # Yr.no always uses metric
        }

    @staticmethod
    def _entry_symbol_code(entry: dict[str, Any]) -> str:
        """Best available symbol code for a timeseries entry."""
        entry_data = entry.get("data", {})
        return (
            entry_data.get("next_1_hours", {}).get("summary", {}).get("symbol_code")
            or entry_data.get("next_6_hours", {}).get("summary", {}).get("symbol_code")
            or entry_data.get("next_12_hours", {}).get("summary", {}).get("symbol_code")
            or "clearsky_day"
        )

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Test Yr.no weather API connection."""
        # Presence is checked on the raw config: normalize_config would fill
        # the schema defaults (Oslo) and mask a missing configuration.
        if "latitude" not in config or "longitude" not in config:
            return {
                "success": False,
                "message": "Latitude and longitude are required. Use 'Look up coordinates' to find them.",  # noqa: E501
            }

        normalized = cls.normalize_config(config)
        latitude = float(normalized.get("latitude"))
        longitude = float(normalized.get("longitude"))
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return {
                "success": False,
                "message": "Invalid coordinates. Latitude must be between -90 and 90, longitude between -180 and 180.",  # noqa: E501
            }

        latitude = round(latitude, 4)
        longitude = round(longitude, 4)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.met.no/weatherapi/locationforecast/2.0/compact",
                    params={"lat": latitude, "lon": longitude},
                    headers={"User-Agent": _USER_AGENT},
                )

            if response.status_code == 200:
                data = response.json()
                if data.get("properties") and data.get("properties", {}).get("timeseries"):
                    return {
                        "success": True,
                        "message": f"Successfully connected to Yr.no API. Weather data available for coordinates ({latitude}, {longitude}).",  # noqa: E501
                    }
                return {
                    "success": False,
                    "message": "Connected to Yr.no API but received invalid data format.",
                }
            if response.status_code == 422:
                return {
                    "success": False,
                    "message": f"Location ({latitude}, {longitude}) is not covered by Yr.no weather service. Please try different coordinates.",  # noqa: E501
                }
            return {
                "success": False,
                "message": f"Yr.no API returned status {response.status_code}. Please check your coordinates.",  # noqa: E501
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Connection to Yr.no API timed out. Please check your internet connection.",  # noqa: E501
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "Could not connect to Yr.no API. Please check your internet connection.",
            }
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"Network error: {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error: {str(e)}",
            }

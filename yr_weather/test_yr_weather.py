"""Tests for the Yr.no Weather plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/yr_weather/test_yr_weather.py
"""

import importlib.util
import re
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("yr_weather_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


yr_weather_module = _load_plugin_module()
YrWeatherServicePlugin = yr_weather_module.YrWeatherServicePlugin

# Mirror of frontend/src/utils/weatherIcons.js — the only icon ids the
# weather-forecast renderer can draw.
KNOWN_WEATHER_ICONS = {
    "mdi:weather-sunny",
    "mdi:weather-night",
    "mdi:weather-partly-cloudy",
    "mdi:weather-cloudy",
    "mdi:weather-rainy",
    "mdi:weather-pouring",
    "mdi:weather-snowy",
    "mdi:weather-lightning",
    "mdi:weather-fog",
    "mdi:weather-windy",
}


def resolve_path(data, path):
    """Python mirror of frontend/src/utils/jsonPath.js resolvePath()."""
    if data is None:
        return None
    if not path or path == "$":
        return data
    expr = path[2:] if path.startswith("$.") else path.lstrip("$")
    if not expr:
        return data
    segments = []
    for m in re.finditer(r"([^.\[\]]+)|\[(\d+)\]", expr):
        segments.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
    cursor = data
    for seg in segments:
        if cursor is None:
            return None
        try:
            cursor = cursor[seg]
        except (KeyError, IndexError, TypeError):
            return None
    return cursor


def _yr_entry(date, hour, temp, symbol):
    return {
        "time": f"{date.isoformat()}T{hour:02d}:00:00Z",
        "data": {
            "instant": {
                "details": {
                    "air_temperature": temp,
                    "relative_humidity": 71.2,
                    "air_pressure_at_sea_level": 1012.5,
                    "wind_speed": 4.2,
                    "wind_from_direction": 180.0,
                }
            },
            "next_1_hours": {"summary": {"symbol_code": symbol}},
        },
    }


def _yr_response(days=2):
    today = datetime.now().date()
    timeseries = [_yr_entry(today, 12, 12.6, "rain")]
    for i in range(1, days + 1):
        day = today + timedelta(days=i)
        timeseries.append(_yr_entry(day, 6, 6.0 + i, "partlycloudy_day"))
        timeseries.append(_yr_entry(day, 12, 12.0 + i, "rain"))
    return {"properties": {"timeseries": timeseries}}


def _shaped_payload():
    instance = YrWeatherServicePlugin("yr-x", "Yr.no Weather")
    instance.config = {
        "latitude": 59.9139,
        "longitude": 10.7522,
        "forecast_days": 2,
        "location": "Oslo, Norway",
    }
    return instance._shape_for_display(_yr_response())


@pytest.fixture
async def plugin():
    """A configured plugin instance (no HTTP client yet)."""
    instance = YrWeatherServicePlugin(plugin_id="yr-test", name="Yr.no Weather", enabled=True)
    await instance.configure(
        {
            "latitude": "59.91391111",
            "longitude": "10.7522",
            "altitude": "12",
            "forecast_days": "2",
            "location": " Oslo, Norway ",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_yr_weather")
        module.YrWeatherServicePlugin = YrWeatherServicePlugin
        assert loader.register_module(module) == ["yr_weather"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(yr_weather_module, hook), hook

    def test_no_legacy_verbs(self):
        # Names assembled at runtime so the repo-wide legacy-API grep gate
        # doesn't match this negative assertion.
        for prefix, suffix in (
            ("get_", "content"),
            ("fetch_", "service_data"),
            ("get_", "plugin_metadata"),
            ("test_", "type_config"),
        ):
            legacy = prefix + suffix
            assert not hasattr(YrWeatherServicePlugin, legacy), legacy

    def test_metadata(self):
        md = YrWeatherServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "yr_weather"
        assert md.instance_identity == ["latitude", "longitude"]
        assert md.display_schema["kind"] == "weather-forecast"
        assert md.statusbar_schema["kind"] == "status"
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"latitude", "longitude"}

    def test_declares_geocode_action(self):
        """The host /geocode endpoint is gated on this action."""
        actions = YrWeatherServicePlugin.metadata.ui_actions
        geocode = [a for a in actions if a["type"] == "geocode"]
        assert len(geocode) == 1
        assert geocode[0]["id"] == "geocode"
        assert geocode[0]["scope"] == "instance"

    def test_is_service_plugin(self):
        assert issubclass(YrWeatherServicePlugin, ServicePlugin)

    def test_icon_map_only_emits_known_icons(self):
        assert set(yr_weather_module.SYMBOL_TO_ICON.values()) <= KNOWN_WEATHER_ICONS
        assert set(yr_weather_module.MDI_TO_GLYPH) == KNOWN_WEATHER_ICONS


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.latitude == 59.9139  # rounded to 4 decimals
        assert plugin.longitude == 10.7522
        assert plugin.altitude == 12  # "12" converted by schema type
        assert plugin.forecast_days == 2
        assert plugin.location == "Oslo, Norway"  # whitespace trimmed

    async def test_forecast_days_clamped(self):
        instance = YrWeatherServicePlugin("yr-x", "Yr")
        await instance.configure({"latitude": 1, "longitude": 1, "forecast_days": 99})
        assert instance.forecast_days == 9
        await instance.configure({"latitude": 1, "longitude": 1, "forecast_days": -1})
        assert instance.forecast_days == 1
        # 0/None falls back to the default (legacy behavior)
        await instance.configure({"latitude": 1, "longitude": 1, "forecast_days": 0})
        assert instance.forecast_days == 5

    async def test_validate_config(self):
        good = {"latitude": 59.9139, "longitude": 10.7522}
        assert await YrWeatherServicePlugin.validate_config(good) is True
        assert await YrWeatherServicePlugin.validate_config({**good, "latitude": 91}) is False
        assert await YrWeatherServicePlugin.validate_config({**good, "longitude": -181}) is False
        assert await YrWeatherServicePlugin.validate_config({"latitude": 59.9139}) is False
        assert await YrWeatherServicePlugin.validate_config({}) is False

    async def test_validate_config_rejects_unconfigured_coords(self):
        # calvin-8p0: enabling the plugin type runs normalize -> validate on an
        # empty config. With no lat/lon schema defaults that normalizes to 0/0,
        # which must NOT validate — otherwise a phantom instance is auto-created.
        empty_normalized = YrWeatherServicePlugin.normalize_config({})
        assert empty_normalized["latitude"] == 0.0
        assert empty_normalized["longitude"] == 0.0
        assert await YrWeatherServicePlugin.validate_config(empty_normalized) is False
        assert (
            await YrWeatherServicePlugin.validate_config({"latitude": 0.0, "longitude": 0.0})
            is False
        )
        # A genuine single-axis-zero location (equator or Greenwich) still validates.
        assert (
            await YrWeatherServicePlugin.validate_config({"latitude": 0.0, "longitude": 10.75})
            is True
        )
        assert (
            await YrWeatherServicePlugin.validate_config({"latitude": 51.5, "longitude": 0.0})
            is True
        )

    def test_instance_identity_stable_per_coordinates(self):
        config = {"latitude": 59.9139, "longitude": 10.7522}
        other = {"latitude": 51.5074, "longitude": -0.1278}
        assert YrWeatherServicePlugin.instance_id_for(
            config
        ) == YrWeatherServicePlugin.instance_id_for({**config, "location": "Oslo"})
        assert YrWeatherServicePlugin.instance_id_for(
            config
        ) != YrWeatherServicePlugin.instance_id_for(other)

    async def test_initialize_requires_valid_coordinates(self):
        instance = YrWeatherServicePlugin("yr-x", "Yr")
        instance.config = {"latitude": 91.0, "longitude": 10.0}
        with pytest.raises(ValueError):
            await instance.initialize()


class TestFetchShaping:
    """fetch() output binds to the weather-forecast display schema."""

    def test_payload_shape(self):
        payload = _shaped_payload()
        current = payload["current"]
        assert current["temperature"] == 13  # rounded for panel + statusbar
        assert current["feels_like"] == 13  # Yr.no has no feels_like; air temp
        assert current["humidity"] == 71.2
        assert current["pressure"] == 1012.5  # already hPa, no conversion
        assert current["description"] == "rain"
        assert current["icon"] == "mdi:weather-rainy"
        assert current["glyph"] == "🌧️"
        assert current["wind_speed"] == 4.2
        assert payload["location"] == "Oslo, Norway"
        assert payload["units"] == "metric"

        assert len(payload["forecast"]) == 2
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        day = payload["forecast"][0]
        assert day["date"] == tomorrow
        assert day["temp_min"] == 7.0
        assert day["temp_max"] == 13.0
        # first symbol of the day (partlycloudy_day)
        assert day["icon"] == "mdi:weather-partly-cloudy"
        assert day["description"] == "partly cloudy"

    def test_icons_are_renderable(self):
        payload = _shaped_payload()
        assert payload["current"]["icon"] in KNOWN_WEATHER_ICONS
        for day in payload["forecast"]:
            assert day["icon"] in KNOWN_WEATHER_ICONS

    def test_empty_timeseries_yields_error(self):
        instance = YrWeatherServicePlugin("yr-x", "Yr")
        payload = instance._shape_for_display({"properties": {"timeseries": []}})
        assert "error" in payload

    async def test_fetch_uses_client(self, plugin):
        response = MagicMock(status_code=200)
        response.json.return_value = _yr_response()
        client = AsyncMock()
        client.get.return_value = response
        plugin._client = client

        payload = await plugin.fetch()
        assert client.get.await_count == 1
        # altitude > 0 is passed to the API
        assert client.get.await_args.kwargs["params"]["altitude"] == 12
        assert payload["current"]["icon"] == "mdi:weather-rainy"
        assert len(payload["forecast"]) == 2

    async def test_fetch_error_payload(self, plugin):
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("no route")
        plugin._client = client
        payload = await plugin.fetch()
        assert "error" in payload

    def test_shape_skips_malformed_timestamp(self):
        """One malformed timestamp is skipped, not fatal to the whole forecast (calvin-p7n)."""
        instance = YrWeatherServicePlugin("yr-x", "Yr.no Weather")
        instance.config = {
            "latitude": 59.9139,
            "longitude": 10.7522,
            "forecast_days": 2,
            "location": "Oslo, Norway",
        }
        response = _yr_response(days=2)
        bad = _yr_entry(datetime.now().date() + timedelta(days=1), 9, 9.0, "rain")
        bad["time"] = "not-a-timestamp"
        response["properties"]["timeseries"].append(bad)
        payload = instance._shape_for_display(response)
        # The good days still render despite the malformed entry.
        assert len(payload["forecast"]) == 2


class TestSchemaPathConsistency:
    """Every *_path in the schemas resolves against a representative payload."""

    def test_display_schema_paths_resolve(self):
        payload = _shaped_payload()
        schema = YrWeatherServicePlugin.metadata.display_schema

        current = resolve_path(payload, schema["current_path"])
        assert isinstance(current, dict)
        for key, path in schema["current"].items():
            assert key.endswith("_path")
            assert resolve_path(current, path) is not None, f"current.{key} -> {path}"

        forecast = resolve_path(payload, schema["forecast_path"])
        assert isinstance(forecast, list) and forecast
        for key, path in schema["forecast"].items():
            assert key.endswith("_path")
            assert resolve_path(forecast[0], path) is not None, f"forecast.{key} -> {path}"

    def test_statusbar_schema_paths_resolve(self):
        payload = _shaped_payload()
        schema = YrWeatherServicePlugin.metadata.statusbar_schema
        item = schema["item"]
        for key, path in item.items():
            if not key.endswith("_path"):
                continue
            assert resolve_path(payload, path) is not None, f"item.{key} -> {path}"
        # icon + current temperature, per the statusbar contract
        assert resolve_path(payload, item["icon_path"]) == payload["current"]["glyph"]
        assert resolve_path(payload, item["value_path"]) == payload["current"]["temperature"]


class TestConnectionTest:
    async def test_missing_config_fails_fast(self):
        result = await YrWeatherServicePlugin.test_connection({})
        assert result["success"] is False

    async def test_out_of_range_coordinates_fail(self):
        result = await YrWeatherServicePlugin.test_connection({"latitude": 95, "longitude": 10})
        assert result["success"] is False

    async def test_connect_error_reported(self, monkeypatch):
        async def raise_connect(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx.AsyncClient, "get", raise_connect)
        result = await YrWeatherServicePlugin.test_connection(
            {"latitude": 59.9139, "longitude": 10.7522}
        )
        assert result["success"] is False
        assert "connect" in result["message"].lower()

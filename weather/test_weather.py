"""Tests for the Weather plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/weather/test_weather.py
"""

import importlib.util
import re
import types
from datetime import datetime, time, timedelta
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
    spec = importlib.util.spec_from_file_location("weather_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


weather_module = _load_plugin_module()
WeatherServicePlugin = weather_module.WeatherServicePlugin

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


def _owm_current_response():
    return {
        "name": "London",
        "sys": {"country": "GB"},
        "main": {"temp": 21.4, "feels_like": 20.9, "humidity": 60, "pressure": 1015},
        "weather": [{"description": "light rain", "icon": "10d"}],
        "wind": {"speed": 3.6, "deg": 200},
    }


def _owm_forecast_response(days=2):
    """3-hourly forecast entries at 09:00 and 15:00 local for the next `days` days."""
    today = datetime.now().date()
    items = []
    for i in range(1, days + 1):
        day = today + timedelta(days=i)
        for hour, temp, icon in ((9, 10.0 + i, "03d"), (15, 16.0 + i, "10d")):
            items.append(
                {
                    "dt": int(datetime.combine(day, time(hour)).timestamp()),
                    "main": {"temp": temp},
                    "weather": [{"description": "scattered clouds", "icon": icon}],
                }
            )
    return {"list": items}


def _shaped_payload(units="metric"):
    instance = WeatherServicePlugin("weather-x", "Weather")
    instance.config = {
        "api_key": "k",
        "location": "London, UK",
        "units": units,
        "forecast_days": 2,
    }
    return instance._shape_for_display(_owm_current_response(), _owm_forecast_response())


@pytest.fixture
async def plugin():
    """A configured plugin instance (no HTTP client yet)."""
    instance = WeatherServicePlugin(plugin_id="weather-test", name="Weather", enabled=True)
    await instance.configure(
        {
            "api_key": " test-api-key ",
            "location": " London, UK ",
            "units": "metric",
            "forecast_days": "2",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_weather")
        module.WeatherServicePlugin = WeatherServicePlugin
        assert loader.register_module(module) == ["weather"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(weather_module, hook), hook

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
            assert not hasattr(WeatherServicePlugin, legacy), legacy

    def test_metadata(self):
        md = WeatherServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "weather"
        assert md.instance_identity == ["location"]
        assert md.display_schema["kind"] == "weather-forecast"
        assert md.statusbar_schema["kind"] == "status"
        # api_key is global (shared across instances), location is per-instance.
        assert md.common_config_schema["api_key"]["global_only"] is True
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"location"}

    def test_is_service_plugin(self):
        assert issubclass(WeatherServicePlugin, ServicePlugin)

    def test_icon_map_only_emits_known_icons(self):
        assert set(weather_module.OWM_ICON_TO_MDI.values()) <= KNOWN_WEATHER_ICONS
        assert set(weather_module.MDI_TO_GLYPH) == KNOWN_WEATHER_ICONS


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.api_key == "test-api-key"  # whitespace trimmed
        assert plugin.location == "London, UK"  # whitespace trimmed
        assert plugin.units == "metric"
        assert plugin.forecast_days == 2  # "2" converted by schema type

    async def test_forecast_days_clamped(self):
        instance = WeatherServicePlugin("weather-x", "Weather")
        await instance.configure({"api_key": "k", "location": "x", "forecast_days": 99})
        assert instance.forecast_days == 5
        await instance.configure({"api_key": "k", "location": "x", "forecast_days": -1})
        assert instance.forecast_days == 1
        # 0/None falls back to the default (legacy behavior)
        await instance.configure({"api_key": "k", "location": "x", "forecast_days": 0})
        assert instance.forecast_days == 3

    async def test_validate_config(self):
        good = {"api_key": "k", "location": "London, UK"}
        assert await WeatherServicePlugin.validate_config(good) is True
        assert await WeatherServicePlugin.validate_config({**good, "api_key": " "}) is False
        assert await WeatherServicePlugin.validate_config({**good, "location": ""}) is False
        assert await WeatherServicePlugin.validate_config({}) is False

    def test_instance_identity_stable_per_location(self):
        config = {"api_key": "a", "location": "London, UK"}
        other = {"api_key": "a", "location": "Oslo, NO"}
        assert WeatherServicePlugin.instance_id_for(config) == WeatherServicePlugin.instance_id_for(
            {**config, "api_key": "b"}
        )
        assert WeatherServicePlugin.instance_id_for(config) != WeatherServicePlugin.instance_id_for(
            other
        )

    async def test_initialize_requires_api_key_and_location(self):
        instance = WeatherServicePlugin("weather-x", "Weather")
        await instance.configure({"api_key": "", "location": ""})
        with pytest.raises(ValueError):
            await instance.initialize()
        await instance.configure({"api_key": "k", "location": ""})
        with pytest.raises(ValueError):
            await instance.initialize()


class TestFetchShaping:
    """fetch() output binds to the weather-forecast display schema."""

    def test_payload_shape(self):
        payload = _shaped_payload()
        current = payload["current"]
        assert current["temperature"] == 21  # rounded for panel + statusbar
        assert current["feels_like"] == 21
        assert current["humidity"] == 60
        assert current["pressure"] == 1015
        assert current["description"] == "light rain"
        assert current["icon"] == "mdi:weather-rainy"  # 10d mapped
        assert current["glyph"] == "🌧️"
        assert current["wind_speed"] == 3.6  # metric already m/s
        assert payload["location"] == "London, GB"
        assert payload["units"] == "metric"

        assert len(payload["forecast"]) == 2
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        day = payload["forecast"][0]
        assert day["date"] == tomorrow
        assert day["temp_min"] == 11.0
        assert day["temp_max"] == 17.0
        assert day["icon"] == "mdi:weather-cloudy"  # first icon of the day (03d)
        assert day["description"] == "scattered clouds"

    def test_icons_are_renderable(self):
        payload = _shaped_payload()
        assert payload["current"]["icon"] in KNOWN_WEATHER_ICONS
        for day in payload["forecast"]:
            assert day["icon"] in KNOWN_WEATHER_ICONS

    def test_imperial_wind_normalized_to_ms(self):
        payload = _shaped_payload(units="imperial")
        assert payload["current"]["wind_speed"] == pytest.approx(3.6 * 0.44704)

    async def test_fetch_uses_client(self, plugin):
        current_resp = MagicMock(status_code=200)
        current_resp.json.return_value = _owm_current_response()
        forecast_resp = MagicMock(status_code=200)
        forecast_resp.json.return_value = _owm_forecast_response()
        client = AsyncMock()
        client.get.side_effect = [current_resp, forecast_resp]
        plugin._client = client

        payload = await plugin.fetch()
        assert client.get.await_count == 2
        assert payload["current"]["icon"] == "mdi:weather-rainy"
        assert len(payload["forecast"]) == 2

    async def test_fetch_error_payload(self, plugin):
        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("no route")
        plugin._client = client
        payload = await plugin.fetch()
        assert "error" in payload


class TestSchemaPathConsistency:
    """Every *_path in the schemas resolves against a representative payload."""

    def test_display_schema_paths_resolve(self):
        payload = _shaped_payload()
        schema = WeatherServicePlugin.metadata.display_schema

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
        schema = WeatherServicePlugin.metadata.statusbar_schema
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
        result = await WeatherServicePlugin.test_connection({})
        assert result["success"] is False

    async def test_connect_error_reported(self, monkeypatch):
        async def raise_connect(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx.AsyncClient, "get", raise_connect)
        result = await WeatherServicePlugin.test_connection(
            {"api_key": "k", "location": "London, UK"}
        )
        assert result["success"] is False
        assert "connect" in result["message"].lower()

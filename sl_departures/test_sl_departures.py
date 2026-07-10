"""Tests for the SL Departures plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/sl_departures/test_sl_departures.py
"""

import importlib.util
import types
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
    spec = importlib.util.spec_from_file_location("sl_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sl_module = _load_plugin_module()
SLDeparturesServicePlugin = sl_module.SLDeparturesServicePlugin


class TestContractShape:
    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_sl_departures")
        module.SLDeparturesServicePlugin = SLDeparturesServicePlugin
        assert loader.register_module(module) == ["sl_departures"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(sl_module, hook), hook

    def test_metadata(self):
        md = SLDeparturesServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "sl_departures"
        assert md.display_schema["kind"] == "status"
        assert md.display_schema["layout"] == "list"
        assert md.statusbar_schema["kind"] == "status"

    def test_is_service_plugin(self):
        assert issubclass(SLDeparturesServicePlugin, ServicePlugin)


@pytest.fixture
async def plugin():
    instance = SLDeparturesServicePlugin(plugin_id="sl-test", name="SL", enabled=True)
    await instance.configure(
        {
            "stop_name": " Tappström ",
            "lines": "176, 177",
            "modes": "bus, Train",
            "direction": "Any",
            "max_departures": "8",
            "forecast_minutes": "60",
        }
    )
    return instance


class TestConfig:
    async def test_accessors_normalize(self, plugin):
        assert plugin.stop_name == "Tappström"
        assert plugin.lines == {"176", "177"}
        assert plugin.modes == {"BUS", "TRAIN"}
        assert plugin.direction == "Any"
        assert plugin.max_departures == 8
        assert plugin.forecast_minutes == 60
        assert plugin.clockbar_show_following is True
        assert plugin.site_id is None  # 0/blank means unset

    async def test_site_id_override(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "site_id": "3002"})
        assert instance.site_id == 3002

    async def test_bounds_clamped(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "max_departures": 999, "forecast_minutes": 1})
        assert instance.max_departures == 30
        assert instance.forecast_minutes == 5

    async def test_validate_config(self):
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "Tappström"}) is True
        assert await SLDeparturesServicePlugin.validate_config({"site_id": 3002}) is True
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "", "site_id": 0}) is False
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "x", "direction": "9"}) is False


def _dep(line="176", mode="BUS", dest="Stenhamra", dcode=1, expected="2026-07-10T23:48:00",
         display="3 min", state="EXPECTED", deviations=None):
    return {
        "destination": dest,
        "direction_code": dcode,
        "state": state,
        "display": display,
        "expected": expected,
        "scheduled": expected,
        "line": {"designation": line, "transport_mode": mode},
        "deviations": deviations or [],
    }


class TestFiltering:
    async def test_filter_by_lines_and_modes(self, plugin):
        deps = [
            _dep(line="176", mode="BUS"),
            _dep(line="177", mode="BUS"),
            _dep(line="317", mode="BUS"),
            _dep(line="10", mode="METRO"),
        ]
        kept = plugin._filter_departures(deps)  # lines={176,177}, modes={BUS,TRAIN}
        assert sorted(d["line"]["designation"] for d in kept) == ["176", "177"]

    async def test_filter_by_direction(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "direction": "2"})
        deps = [_dep(dcode=1), _dep(dcode=2)]
        kept = instance._filter_departures(deps)
        assert [d["direction_code"] for d in kept] == [2]

    async def test_no_filters_keeps_all(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x"})
        deps = [_dep(line="1"), _dep(line="2", mode="METRO")]
        assert len(instance._filter_departures(deps)) == 2

    async def test_sort_and_limit(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "max_departures": 2})
        deps = [
            _dep(expected="2026-07-10T23:50:00"),
            _dep(expected="2026-07-10T23:45:00"),
            _dep(expected="2026-07-10T23:48:00"),
        ]
        ordered = instance._sort_and_limit(deps)
        assert [d["expected"] for d in ordered] == ["2026-07-10T23:45:00", "2026-07-10T23:48:00"]


class TestShaping:
    async def test_shape_departure_label_and_status(self, plugin):
        assert plugin._status_for(_dep()) == "ok"
        assert plugin._status_for(_dep(state="CANCELLED")) == "error"
        assert plugin._status_for(_dep(deviations=[{"importance_level": 5}])) == "warn"
        shaped = plugin._shape_departure(_dep(line="176", dest="Stenhamra", display="3 min"))
        assert shaped == {"label": "176 · Stenhamra", "display": "3 min", "status": "ok"}

    async def test_full_shape_filters_sorts_and_builds_clockbar(self, plugin):
        raw = {
            "departures": [
                _dep(line="317", mode="BUS", expected="2026-07-10T23:40:00"),  # filtered out
                _dep(line="177", mode="BUS", dest="Skärvik", display="6 min",
                     expected="2026-07-10T23:51:00"),
                _dep(line="176", mode="BUS", dest="Stenhamra", display="3 min",
                     expected="2026-07-10T23:48:00"),
            ]
        }
        shaped = plugin._shape_for_display(raw)
        assert shaped["stop"] == "Tappström"
        assert [d["label"] for d in shaped["departures"]] == ["176 · Stenhamra", "177 · Skärvik"]
        # clock bar shows next + following (toggle default on), each with its own line
        assert shaped["clockbar"] == {"label": "Tappström", "value": "176·3′ · 177·6′", "status": "ok"}

    async def test_clockbar_next_only_when_toggle_off(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "Tappström", "clockbar_show_following": False})
        raw = {"departures": [_dep(line="176", display="3 min", expected="2026-07-10T23:48:00"),
                              _dep(line="177", display="6 min", expected="2026-07-10T23:51:00")]}
        assert instance._shape_for_display(raw)["clockbar"]["value"] == "176·3′"

    async def test_empty_board_message_and_clockbar(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "Tappström", "forecast_minutes": 60})
        shaped = instance._shape_for_display({"departures": []})
        assert shaped["departures"] == [
            {"label": "No departures in the next 60 min", "display": "", "status": "ok"}
        ]
        assert shaped["clockbar"] == {"label": "Tappström", "value": "—", "status": "ok"}

    async def test_error_passes_through(self, plugin):
        shaped = plugin._shape_for_display({"error": "Couldn't reach SL — retrying"})
        assert shaped["error"] == "Couldn't reach SL — retrying"
        assert shaped["departures"] == []
        assert shaped["clockbar"] == {"label": "Tappström", "value": "—", "status": "ok"}


_SITES = [
    {"id": 3002, "name": "Tappström"},
    {"id": 1002, "name": "Stockholm City"},
    {"id": 9001, "name": "T-Centralen"},
    {"id": 5000, "name": "Centralnav"},
]


class TestSiteResolution:
    def test_match_exact_preferred(self):
        matches = SLDeparturesServicePlugin._match_sites(_SITES, "Tappström")
        assert matches == [{"id": 3002, "name": "Tappström"}]

    def test_match_contains_multiple(self):
        matches = SLDeparturesServicePlugin._match_sites(_SITES, "central")
        assert {m["id"] for m in matches} == {9001, 5000}

    def test_match_none(self):
        assert SLDeparturesServicePlugin._match_sites(_SITES, "Nowhere") == []

    async def test_resolve_uses_site_id_override(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "Tappström", "site_id": 3002})
        site_id, name, candidates = await instance._resolve_site()
        assert (site_id, candidates) == (3002, [])

    async def test_resolve_single_match(self, monkeypatch):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "Tappström"})
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        site_id, name, candidates = await instance._resolve_site()
        assert (site_id, name, candidates) == (3002, "Tappström", [])

    async def test_resolve_ambiguous_returns_candidates(self, monkeypatch):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "central"})
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        site_id, name, candidates = await instance._resolve_site()
        assert site_id is None
        assert {c["id"] for c in candidates} == {9001, 5000}


class TestFetch:
    async def test_fetch_resolves_then_shapes(self, plugin, monkeypatch):
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_resolve_site",
            AsyncMock(return_value=(3002, "Tappström", [])),
        )
        raw = {"departures": [_dep(line="176", dest="Stenhamra", display="3 min")]}
        monkeypatch.setattr(SLDeparturesServicePlugin, "_get_departures", AsyncMock(return_value=raw))
        shaped = await plugin.fetch()
        assert shaped["stop"] == "Tappström"
        assert shaped["departures"][0]["label"] == "176 · Stenhamra"

    async def test_fetch_ambiguous_stop_returns_error(self, plugin, monkeypatch):
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_resolve_site",
            AsyncMock(return_value=(None, None, [{"id": 9001, "name": "T-Centralen"},
                                                 {"id": 5000, "name": "Centralnav"}])),
        )
        shaped = await plugin.fetch()
        assert "T-Centralen" in shaped["error"]
        assert shaped["departures"] == []

    async def test_fetch_unresolved_stop_returns_error(self, plugin, monkeypatch):
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_resolve_site",
            AsyncMock(return_value=(None, None, [])),
        )
        shaped = await plugin.fetch()
        assert "Tappström" in shaped["error"]

    async def test_fetch_departures_network_error_is_wrapped(self, plugin, monkeypatch):
        async def boom(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(SLDeparturesServicePlugin, "_get_departures", boom)
        raw = await plugin._fetch_departures(3002)
        assert raw["error"].startswith("Couldn't reach SL")

    async def test_get_departures_calls_api(self, monkeypatch):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"departures": []}
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.get.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=client))
        raw = await SLDeparturesServicePlugin._get_departures(3002, 60)
        assert raw == {"departures": []}
        called_url = client.get.call_args[0][0]
        assert called_url.endswith("/v1/sites/3002/departures")

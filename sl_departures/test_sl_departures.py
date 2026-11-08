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
from loguru import logger

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

    def test_stop_name_is_optional(self):
        """A stop ID alone is valid, so the host must not require stop_name.

        The host checks schema-required fields before validate_config, so
        marking stop_name required would reject site-id-only instances.
        """
        field = SLDeparturesServicePlugin.metadata.instance_config_schema["stop_name"]
        assert field.get("required") is not True
        assert not (field.get("ui") or {}).get("validation", {}).get("required")

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

    async def test_validate_config_accepts_legacy_directions(self):
        for value in ("Any", "1", "2"):
            assert await SLDeparturesServicePlugin.validate_config({"stop_name": "x", "direction": value})

    async def test_schema_has_towards_and_no_direction_picker(self):
        schema = SLDeparturesServicePlugin.metadata.instance_config_schema
        assert "direction" not in schema
        assert schema["towards"]["label"] == "Going towards"
        assert schema["towards"]["default"] == ""
        assert schema["towards"]["ui"]["component"] == "input"

    async def test_legacy_direction_survives_configure(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "direction": "2"})
        assert instance.direction == "2"

    async def test_validate_config_accepts_site_id_only(self):
        """An existing instance configured by stop ID must pass on its own."""
        assert (
            await SLDeparturesServicePlugin.validate_config({"stop_name": "", "site_id": 3002})
            is True
        )

    async def test_validate_config_failure_names_both_options(self):
        messages = []
        handler_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
        try:
            assert (
                await SLDeparturesServicePlugin.validate_config({"stop_name": "", "site_id": 0})
                is False
            )
        finally:
            logger.remove(handler_id)
        assert any(
            "stop name" in message.lower() and "stop id" in message.lower()
            for message in messages
        ), messages


def _dep(line="176", mode="BUS", dest="Stenhamra", dcode=1, expected="2026-07-10T23:48:00",
         display="3 min", state="EXPECTED", deviations=None, direction=None):
    out = {
        "destination": dest,
        "direction_code": dcode,
        "state": state,
        "display": display,
        "expected": expected,
        "scheduled": expected,
        "line": {"designation": line, "transport_mode": mode},
        "deviations": deviations or [],
    }
    if direction is not None:
        out["direction"] = direction
    return out


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

    async def _towards(self, towards, **extra):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "towards": towards, **extra})
        return instance

    async def test_towards_partial_case_insensitive(self):
        instance = await self._towards("hässel")
        deps = [_dep(direction="Hässelby strand"), _dep(direction="Ropsten")]
        assert [d["direction"] for d in instance._filter_departures(deps)] == ["Hässelby strand"]
        upper = await self._towards("HÄSSELBY")
        assert len(upper._filter_departures(deps)) == 1

    async def test_towards_several_terms(self):
        instance = await self._towards("Hässelby, ropsten ,")
        deps = [_dep(direction="Hässelby strand"), _dep(direction="Ropsten"), _dep(direction="Norsborg")]
        assert [d["direction"] for d in instance._filter_departures(deps)] == ["Hässelby strand", "Ropsten"]

    async def test_towards_matches_direction_not_short_trip_destination(self):
        instance = await self._towards("Hässelby")
        dep = _dep(line="17", dest="Vällingby", direction="Hässelby strand")
        assert instance._filter_departures([dep]) == [dep]
        other = await self._towards("Vällingby")
        assert other._filter_departures([dep]) == []

    async def test_towards_falls_back_to_destination_when_direction_blank(self):
        instance = await self._towards("Stenhamra")
        missing = _dep(dest="Stenhamra")
        blank = _dep(dest="Stenhamra", direction="  ")
        assert instance._filter_departures([missing, blank, _dep(dest="Ekerö")]) == [missing, blank]

    async def test_empty_towards_keeps_all(self):
        instance = await self._towards("  ")
        deps = [_dep(direction="A"), _dep(direction="B")]
        assert instance._filter_departures(deps) == deps

    async def test_towards_overrides_legacy_direction(self):
        instance = await self._towards("Ropsten", direction="2")
        deps = [_dep(dcode=1, direction="Ropsten"), _dep(dcode=2, direction="Norsborg")]
        assert [d["direction"] for d in instance._filter_departures(deps)] == ["Ropsten"]

    async def test_legacy_direction_applies_when_towards_empty(self):
        instance = await self._towards("", direction="1")
        deps = [_dep(dcode=1, direction="Ropsten"), _dep(dcode=2, direction="Norsborg")]
        assert [d["direction_code"] for d in instance._filter_departures(deps)] == [1]

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

    async def test_compact_display_empty_display(self, plugin):
        # SL always sends a display string; document the fallback if it were ever empty.
        entry = plugin._compact_display(_dep(line="176", display=""))
        assert entry == "176"


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
        assert "set the site id in settings" in shaped["error"]

    async def test_fetch_unresolved_stop_returns_error(self, plugin, monkeypatch):
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_resolve_site",
            AsyncMock(return_value=(None, None, [])),
        )
        shaped = await plugin.fetch()
        assert "Tappström" in shaped["error"]
        assert "check the spelling in settings" in shaped["error"]

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
        client_cls = MagicMock(return_value=client)
        monkeypatch.setattr(httpx, "AsyncClient", client_cls)
        raw = await SLDeparturesServicePlugin._get_departures(3002, 60)
        assert raw == {"departures": []}
        called_url = client.get.call_args[0][0]
        assert called_url.endswith("/v1/sites/3002/departures")
        assert client.get.call_args.kwargs["params"] == {"forecast": 60}
        assert client_cls.call_args.kwargs["timeout"] == 30.0


class TestConnection:
    async def test_missing_stop_fails_fast(self):
        result = await SLDeparturesServicePlugin.test_connection({})
        assert result["success"] is False
        assert "stop name" in result["message"]

    async def test_single_match_reports_next_departure(self, monkeypatch):
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_get_departures",
            AsyncMock(return_value={"departures": [_dep(line="176", dest="Stenhamra", display="3 min")]}),
        )
        result = await SLDeparturesServicePlugin.test_connection({"stop_name": "Tappström"})
        assert result["success"] is True
        assert result["site_id"] == 3002
        assert "176" in result["message"] and "Stenhamra" in result["message"]

    async def _connect(self, monkeypatch, deps, config):
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        monkeypatch.setattr(
            SLDeparturesServicePlugin, "_get_departures", AsyncMock(return_value={"departures": deps})
        )
        return await SLDeparturesServicePlugin.test_connection({"stop_name": "Tappström", **config})

    async def test_lists_end_stations_per_line(self, monkeypatch):
        deps = [
            _dep(line="14", dest="Mörby centrum", direction="Mörby centrum"),
            _dep(line="13", dest="Ropsten", direction="Ropsten"),
            _dep(line="13", dest="Ropsten", direction="Ropsten"),
            _dep(line="13", dest="Norsborg", direction="Norsborg"),
            _dep(line="2", dest="Odenplan", direction="Odenplan"),
        ]
        result = await self._connect(monkeypatch, deps, {})
        assert result["success"] is True
        msg = result["message"]
        assert "2 → Odenplan · 13 → Ropsten / Norsborg · 14 → Mörby centrum" in msg
        assert msg.count("Ropsten") == 1

    async def test_end_station_list_capped(self, monkeypatch):
        deps = [_dep(line=str(n), direction=f"End{n}") for n in range(1, 21)]
        result = await self._connect(monkeypatch, deps, {})
        assert "+8 more" in result["message"]
        assert "12 → End12" in result["message"] and "13 → End13" not in result["message"]

    async def test_end_stations_respect_lines_and_modes(self, monkeypatch):
        deps = [
            _dep(line="13", mode="METRO", direction="Ropsten"),
            _dep(line="176", mode="BUS", direction="Stenhamra"),
        ]
        by_line = await self._connect(monkeypatch, deps, {"lines": "176"})
        assert "176 → Stenhamra" in by_line["message"] and "Ropsten" not in by_line["message"]
        by_mode = await self._connect(monkeypatch, deps, {"modes": "metro"})
        assert "Ropsten" in by_mode["message"] and "Stenhamra" not in by_mode["message"].split("End stations")[1]

    async def test_towards_no_match_warns_but_succeeds(self, monkeypatch):
        deps = [_dep(line="13", direction="Ropsten"), _dep(line="14", direction="Mörby centrum")]
        result = await self._connect(monkeypatch, deps, {"towards": "Kungsträdgården"})
        assert result["success"] is True
        assert "Warning" in result["message"]
        assert "Mörby centrum, Ropsten" in result["message"]

    async def test_towards_match_has_no_warning(self, monkeypatch):
        deps = [_dep(line="13", direction="Ropsten")]
        result = await self._connect(monkeypatch, deps, {"towards": "rops"})
        assert result["success"] is True and "Warning" not in result["message"]

    async def test_ambiguous_lists_candidates(self, monkeypatch):
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        result = await SLDeparturesServicePlugin.test_connection({"stop_name": "central"})
        assert result["success"] is False
        assert "9001" in result["message"] and "5000" in result["message"]

    async def test_no_match(self, monkeypatch):
        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", AsyncMock(return_value=_SITES))
        result = await SLDeparturesServicePlugin.test_connection({"stop_name": "Nowhere"})
        assert result["success"] is False
        assert "Nowhere" in result["message"]

    async def test_network_error_reported(self, monkeypatch):
        async def boom(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(SLDeparturesServicePlugin, "_fetch_sites", boom)
        result = await SLDeparturesServicePlugin.test_connection({"stop_name": "Tappström"})
        assert result["success"] is False
        assert "reach SL" in result["message"]

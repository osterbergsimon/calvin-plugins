"""Tests for the Homey plugin (plugin contract 1.0).

Run with the Calvin backend venv, from this repo's root:
    PYTHONPATH="$PWD:<calvin>/backend" <calvin>/backend/.venv/bin/python -m pytest homey -q

The hub is always mocked: no test contacts a real Homey.
"""

import asyncio
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)

PLUGIN_DIR = Path(__file__).parent
KEY = "k-secret-0000"
BASE = "http://hub.example"
D1 = "00000000-0000-4000-8000-000000000001"
D2 = "00000000-0000-4000-8000-000000000002"
D3 = "00000000-0000-4000-8000-000000000003"
Z1 = "00000000-0000-4000-8000-0000000000a1"


def _load(name: str, filename: str):
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


client_mod = _load("homey_client", "homey_client.py")
HomeyClient = client_mod.HomeyClient
HomeyDevice = client_mod.HomeyDevice
HomeyUnreachable = client_mod.HomeyUnreachable
HomeyAuthError = client_mod.HomeyAuthError


devices_mod = _load("homey_devices", "homey_devices.py")
parse_device_ids = devices_mod.parse_device_ids


plugin_mod = _load("homey_plugin_under_test", "plugin.py")
HomeyServicePlugin = plugin_mod.HomeyServicePlugin


def _dev(did, name, *, zone=Z1, onoff=True, available=True, caps=("onoff",)):
    obj = {"onoff": {"value": onoff}} if "onoff" in caps else {}
    return {
        "id": did,
        "name": name,
        "zone": zone,
        "available": available,
        "capabilities": list(caps),
        "capabilitiesObj": obj,
    }


def _hub(handler):
    return httpx.MockTransport(handler)


def _client(handler, base=BASE):
    return HomeyClient(base, KEY, transport=_hub(handler))


class TestHomeyClient:
    async def test_lists_devices_into_homey_device(self):
        def handler(request):
            if request.url.path == "/api/manager/devices/device":
                return httpx.Response(
                    200,
                    json={
                        D1: _dev(D1, "Lamp A"),
                        D2: _dev(D2, "Sensor B", caps=("measure_temperature",)),
                    },
                )
            if request.url.path == "/api/manager/zones/zone":
                return httpx.Response(200, json={Z1: {"id": Z1, "name": "Room A"}})
            return httpx.Response(404)

        devices = {d.id: d for d in await _client(handler).list_devices()}
        assert devices[D1] == HomeyDevice(D1, "Lamp A", "Room A", True, True, True)
        assert devices[D2].has_onoff is False
        assert devices[D2].on is None

    async def test_zone_lookup_failure_leaves_zone_empty(self):
        def handler(request):
            if request.url.path.endswith("/zones/zone"):
                return httpx.Response(403)
            return httpx.Response(200, json={D1: _dev(D1, "Lamp A")})

        [device] = await _client(handler).list_devices()
        assert device.zone is None
        assert device.name == "Lamp A"

    async def test_sends_the_key_only_in_the_auth_header(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={})

        await _client(handler).list_devices()
        assert seen
        for request in seen:
            assert request.headers["authorization"] == f"Bearer {KEY}"
            assert KEY not in str(request.url)
            assert KEY not in request.content.decode()

    async def test_trailing_slash_in_base_url_is_fine(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={})

        await _client(handler, base=BASE + "/").list_devices()
        assert seen[0] == "/api/manager/devices/device"

    async def test_connect_error_raises_unreachable(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        with pytest.raises(HomeyUnreachable):
            await _client(handler).list_devices()

    async def test_timeout_raises_unreachable(self):
        def handler(request):
            raise httpx.ReadTimeout("slow")

        with pytest.raises(HomeyUnreachable):
            await _client(handler).get_device(D1)

    async def test_default_timeout_is_well_under_the_host_limit(self):
        assert HomeyClient(BASE, KEY).timeout <= 5.0

    @pytest.mark.parametrize("status", [401, 403])
    async def test_refused_key_raises_auth_error(self, status):
        with pytest.raises(HomeyAuthError):
            await _client(lambda r: httpx.Response(status)).list_devices()

    async def test_server_error_raises_unreachable(self):
        with pytest.raises(HomeyUnreachable):
            await _client(lambda r: httpx.Response(500, text=KEY)).list_devices()

    async def test_unknown_device_returns_none(self):
        assert await _client(lambda r: httpx.Response(404)).get_device(D1) is None

    async def test_get_device_reads_one_device(self):
        def handler(request):
            if request.url.path.endswith("/zones/zone"):
                return httpx.Response(200, json={})
            assert request.url.path == f"/api/manager/devices/device/{D1}"
            return httpx.Response(200, json=_dev(D1, "Lamp A", onoff=False))

        device = await _client(handler).get_device(D1)
        assert device.on is False

    async def test_set_onoff_sends_a_json_boolean(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={})

        await _client(handler).set_onoff(D1, True)
        [request] = seen
        assert request.method == "PUT"
        assert request.url.path == f"/api/manager/devices/device/{D1}/capability/onoff"
        assert json.loads(request.content) == {"value": True}

    async def test_set_onoff_unknown_device_raises_unreachable_free_error(self):
        with pytest.raises(client_mod.HomeyDeviceNotFound):
            await _client(lambda r: httpx.Response(404)).set_onoff(D1, False)

    async def test_device_id_is_path_safe(self):
        seen = []

        def handler(request):
            seen.append(request.url.raw_path.decode())
            return httpx.Response(404)

        await _client(handler).get_device("a/../b?x=1")
        assert "/../" not in seen[0] and "?" not in seen[0]

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(200, text="not json"),
            httpx.Response(200, json=["a", "list"]),
            httpx.Response(200, json={D1: "not a device", D2: {"name": "no id"}}),
        ],
    )
    async def test_malformed_bodies_never_crash_listing(self, response):
        def handler(request):
            if request.url.path.endswith("/zones/zone"):
                return httpx.Response(200, json={})
            return response

        try:
            devices = await _client(handler).list_devices()
        except HomeyUnreachable:
            return
        assert all(isinstance(d, HomeyDevice) for d in devices)

    async def test_device_missing_fields_is_unavailable_not_a_crash(self):
        def handler(request):
            if request.url.path.endswith("/zones/zone"):
                return httpx.Response(200, json={})
            return httpx.Response(200, json={D1: {"id": D1}})

        [device] = await _client(handler).list_devices()
        assert device.available is False
        assert device.has_onoff is False
        assert device.on is None

    @pytest.mark.parametrize(
        "status,body",
        [(401, KEY), (500, KEY), (200, KEY)],
    )
    async def test_exception_messages_never_contain_the_key(self, status, body):
        try:
            await _client(lambda r: httpx.Response(status, text=body)).list_devices()
        except Exception as exc:  # noqa: BLE001
            assert KEY not in str(exc)
            assert KEY not in repr(exc)

    async def test_connect_error_text_never_contains_the_key(self):
        def handler(request):
            raise httpx.ConnectError(f"failed with {KEY} at {request.url}")

        with pytest.raises(HomeyUnreachable) as info:
            await _client(handler).list_devices()
        assert KEY not in str(info.value)
        assert info.value.__cause__ is None


class TestClientHardening:
    async def test_http_libraries_do_not_log_address_or_device_ids(self, caplog):
        caplog.set_level(0)
        logging.getLogger().setLevel(0)
        await _client(
            lambda r: httpx.Response(200, json={D1: _dev(D1, "Lamp A")})
        ).list_devices()
        await _client(lambda r: httpx.Response(200, json={})).set_onoff(D1, True)
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "hub.example" not in text
        assert D1 not in text

    async def test_slow_hub_hits_the_total_deadline(self):
        async def handler(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={})

        client = HomeyClient(BASE, KEY, transport=_hub(handler), deadline=0.05)
        with pytest.raises(HomeyUnreachable):
            await client.list_devices()

    def test_default_deadline_is_under_the_host_limit(self):
        assert HomeyClient(BASE, KEY).deadline < 10.0

    async def test_redirects_are_not_followed(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://other.example/"})

        with pytest.raises(HomeyUnreachable):
            await _client(handler).list_devices()
        assert len(seen) == 1

    def test_environment_proxies_are_ignored(self):
        assert HomeyClient(BASE, KEY)._http._trust_env is False

    async def test_deeply_nested_json_is_unreachable_not_a_crash(self):
        body = "[" * 100000 + "]" * 100000
        with pytest.raises(HomeyUnreachable):
            await _client(lambda r: httpx.Response(200, text=body)).list_devices()

    async def test_names_are_trimmed_and_duplicate_ids_dropped(self):
        def handler(request):
            if request.url.path.endswith("/zones/zone"):
                return httpx.Response(200, json={})
            return httpx.Response(
                200, json={"a": _dev(D1, "  Lamp A "), "b": _dev(D1, "Lamp A again")}
            )

        devices = await _client(handler).list_devices()
        assert [(d.id, d.name) for d in devices] == [(D1, "Lamp A")]


class TestChosenDevices:
    @pytest.mark.parametrize("raw", [None, "", " , ,", "   "])
    def test_empty_inputs_give_empty_list(self, raw):
        assert parse_device_ids(raw) == []

    def test_trims_drops_empties_and_later_duplicates(self):
        assert parse_device_ids(" a, b ,,a ") == ["a", "b"]

    def test_single_id(self):
        assert parse_device_ids(D1) == [D1]

    def test_keeps_order_and_case(self):
        assert parse_device_ids("B,a,A") == ["B", "a", "A"]

    def test_non_string_is_empty(self):
        assert parse_device_ids(5) == []


class FakeClient:
    """Stands in for HomeyClient; records constructor args and calls."""

    instances: list = []

    def __init__(self, base_url, api_key, **kwargs):
        self.base_url = base_url
        self.api_key = api_key
        self.list_devices = AsyncMock(return_value=[])
        self.set_onoff = AsyncMock()
        self.get_device = AsyncMock(return_value=None)
        self.aclose = AsyncMock()
        FakeClient.instances.append(self)


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(plugin_mod, "HomeyClient", FakeClient)
    return FakeClient


GOOD = {"host": "http://hub.example", "api_key": KEY}


def _homey_device(did, name, zone=None, has_onoff=True, on=False, available=True):
    return HomeyDevice(did, name, zone, has_onoff, on, available)


class TestContractShape:
    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_homey")
        module.HomeyServicePlugin = HomeyServicePlugin
        assert loader.register_module(module) == ["homey"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(plugin_mod, hook), hook

    def test_is_service_plugin(self):
        assert issubclass(HomeyServicePlugin, ServicePlugin)

    def test_metadata(self):
        md = HomeyServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "homey"
        assert md.name == "Homey"
        assert md.instance_identity is None
        assert md.display_schema["kind"] == "switch-grid"
        assert md.display_schema["poll_interval_ms"] == 15000
        assert md.display_schema["unreachable_text"] == "Couldn't reach Homey"
        assert md.display_schema["empty_text"] == "No devices chosen yet."
        [action] = md.actions
        assert action.name == "set_onoff"
        assert action.params["device"].type == "string"
        assert action.params["on"].type == "boolean"

    def test_devices_field_is_multi_select_scan(self):
        field = HomeyServicePlugin.metadata.instance_config_schema["devices"]
        assert field["type"] == "string"
        assert field["ui"]["component"] == "multi-select-scan"

    def test_host_is_an_endpoint_key_and_api_key_a_secret_key(self):
        from app.plugins.utils.secrets import endpoint_keys, secret_keys

        schema = HomeyServicePlugin.metadata.instance_config_schema
        assert schema["host"]["ui"]["endpoint"] is True
        assert "host" in endpoint_keys(schema)
        assert secret_keys(schema) == {"api_key"}
        assert schema["api_key"]["type"] == "password"

    def test_api_key_description_names_both_scopes(self):
        text = HomeyServicePlugin.metadata.instance_config_schema["api_key"][
            "description"
        ]
        assert "homey.device.readonly" in text
        assert "homey.device.control" in text


class TestConfig:
    async def test_validate_config(self):
        v = HomeyServicePlugin.validate_config
        assert await v(GOOD) is True
        assert await v({**GOOD, "api_key": " "}) is False
        assert await v({**GOOD, "host": "ftp://x"}) is False
        assert await v({**GOOD, "host": ""}) is False
        assert await v({"host": "https://hub.example", "api_key": "k"}) is True

    async def test_initialize_requires_host_and_key(self):
        instance = HomeyServicePlugin("homey-x", "Homey")
        await instance.configure({"host": "", "api_key": ""})
        with pytest.raises(ValueError):
            await instance.initialize()

    async def test_initialize_error_text_has_no_key(self):
        instance = HomeyServicePlugin("homey-x", "Homey")
        await instance.configure({"host": "nope", "api_key": KEY})
        with pytest.raises(ValueError) as info:
            await instance.initialize()
        assert KEY not in str(info.value)

    async def test_client_built_and_closed_on_configure(self, fake_client):
        instance = HomeyServicePlugin("homey-x", "Homey")
        await instance.configure({**GOOD, "host": "http://hub.example/"})
        await instance.initialize()
        [first] = fake_client.instances
        assert first.base_url == "http://hub.example"
        assert first.api_key == KEY
        await instance.configure(GOOD)
        first.aclose.assert_awaited()
        await instance.cleanup()

    async def test_no_log_line_holds_the_key(self, fake_client, caplog):
        from loguru import logger

        lines = []
        sink = logger.add(lines.append, level="DEBUG")
        try:
            instance = HomeyServicePlugin("homey-x", "Homey")
            await instance.configure(GOOD)
            await instance.initialize()
            await HomeyServicePlugin.test_connection(GOOD)
            await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
            await instance.cleanup()
        finally:
            logger.remove(sink)
        assert not any(KEY in str(line) for line in lines)
        assert not any(KEY in r.getMessage() for r in caplog.records)


class TestHostValidation:
    @pytest.mark.parametrize(
        "host",
        [
            "http://[bad",
            "http://a b",
            "http://user:pw@hub.example",
            "http://hub.example/?x=1",
            "http://hub.example/#f",
            "https://",
        ],
    )
    async def test_odd_hosts_are_rejected_without_calling_the_hub(
        self, fake_client, host
    ):
        cfg = {"host": host, "api_key": KEY}
        assert await HomeyServicePlugin.validate_config(cfg) is False
        result = await HomeyServicePlugin.test_connection(cfg)
        assert result["success"] is False and KEY not in result["message"]
        scan = await HomeyServicePlugin.scan_options_with_config("devices", cfg)
        assert scan["options"] == [] and scan["error"]
        assert fake_client.instances == []

    async def test_client_construction_failure_is_unreachable(self, monkeypatch):
        def boom(*a, **k):
            raise ValueError("http://hub.example leaked")

        monkeypatch.setattr(plugin_mod, "HomeyClient", boom)
        result = await HomeyServicePlugin.test_connection(GOOD)
        assert result == {"success": False, "message": "Couldn't reach Homey."}
        scan = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert scan == {"options": [], "error": "Couldn't reach Homey."}


class TestConnection:
    async def test_success(self, fake_client, monkeypatch):
        result = await HomeyServicePlugin.test_connection(GOOD)
        assert result["success"] is True
        assert KEY not in result["message"]
        [client] = fake_client.instances
        client.list_devices.assert_awaited_once()
        client.aclose.assert_awaited()

    async def test_auth_refused(self, fake_client, monkeypatch):
        monkeypatch.setattr(
            FakeClient, "__init__", _failing_init(HomeyAuthError()), raising=True
        )
        result = await HomeyServicePlugin.test_connection(GOOD)
        assert result == {"success": False, "message": "Homey refused the API key."}

    async def test_unreachable(self, fake_client, monkeypatch):
        monkeypatch.setattr(
            FakeClient, "__init__", _failing_init(HomeyUnreachable()), raising=True
        )
        result = await HomeyServicePlugin.test_connection(GOOD)
        assert result == {"success": False, "message": "Couldn't reach Homey."}

    async def test_blank_config_does_not_call_the_hub(self, fake_client):
        result = await HomeyServicePlugin.test_connection({"host": "", "api_key": ""})
        assert result["success"] is False
        assert fake_client.instances == []


def _failing_init(exc):
    def init(self, base_url, api_key, **kwargs):
        self.list_devices = AsyncMock(side_effect=exc)
        self.aclose = AsyncMock()
        FakeClient.instances.append(self)

    return init


class TestScan:
    async def test_lists_only_onoff_devices_sorted_by_label(
        self, fake_client, monkeypatch
    ):
        devices = [
            _homey_device(D2, "Lamp B", "Room A"),
            _homey_device(D3, "Sensor", "Room A", has_onoff=False, on=None),
            _homey_device(D1, "Lamp A", None),
        ]
        monkeypatch.setattr(
            FakeClient, "__init__", _listing_init(devices), raising=True
        )
        result = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert result == {
            "options": [
                {"value": D1, "label": "Lamp A"},
                {"value": D2, "label": "Lamp B (Room A)"},
            ]
        }

    async def test_other_field_returns_none(self, fake_client):
        assert await HomeyServicePlugin.scan_options_with_config("host", GOOD) is None
        assert fake_client.instances == []

    async def test_unreachable(self, fake_client, monkeypatch):
        monkeypatch.setattr(
            FakeClient, "__init__", _failing_init(HomeyUnreachable()), raising=True
        )
        result = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert result == {"options": [], "error": "Couldn't reach Homey."}

    async def test_auth_refused(self, fake_client, monkeypatch):
        monkeypatch.setattr(
            FakeClient, "__init__", _failing_init(HomeyAuthError()), raising=True
        )
        result = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert result == {"options": [], "error": "Homey refused the API key."}

    async def test_blank_config_gives_error_without_calling_hub(self, fake_client):
        result = await HomeyServicePlugin.scan_options_with_config(
            "devices", {"host": "http://hub.example", "api_key": ""}
        )
        assert result["options"] == []
        assert result["error"]
        assert fake_client.instances == []

    async def test_result_never_contains_the_key(self, fake_client, monkeypatch):
        monkeypatch.setattr(
            FakeClient,
            "__init__",
            _listing_init([_homey_device(D1, "Lamp A")]),
            raising=True,
        )
        result = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert KEY not in json.dumps(result)

    async def test_hub_data_oddities_do_not_crash_the_scan(
        self, fake_client, monkeypatch
    ):
        monkeypatch.setattr(
            FakeClient,
            "__init__",
            _listing_init([_homey_device(D1, "  ", "Room A")]),
            raising=True,
        )
        result = await HomeyServicePlugin.scan_options_with_config("devices", GOOD)
        assert result["options"][0]["value"] == D1


def _listing_init(devices):
    def init(self, base_url, api_key, **kwargs):
        self.list_devices = AsyncMock(return_value=devices)
        self.aclose = AsyncMock()
        FakeClient.instances.append(self)

    return init


try:
    from app.plugins.actions import PluginActionError, PluginActionRefused
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)

HomeyDeviceNotFound = client_mod.HomeyDeviceNotFound


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
async def live(fake_client):
    """A configured, initialized plugin with a stubbed client and a fake clock."""

    async def make(devices_cfg=f"{D2},{D1}", hub=None):
        instance = HomeyServicePlugin("homey-x", "Homey")
        await instance.configure({**GOOD, "devices": devices_cfg})
        instance._clock = Clock()
        await instance.initialize()
        client = fake_client.instances[-1]
        client.list_devices.return_value = (
            hub
            if hub is not None
            else [
                _homey_device(D1, "Lamp A", "Room A", on=False),
                _homey_device(D2, "Lamp B", "Room B", on=True),
                _homey_device(D3, "Lamp C", "Room A", on=True),
            ]
        )
        return instance, client

    return make


class TestFetch:
    async def test_chosen_devices_in_chosen_order_with_explicit_targets(self, live):
        plugin, _ = await live()
        data = await plugin.fetch()
        assert [i["id"] for i in data["items"]] == [D2, D1]
        lamp_b, lamp_a = data["items"]
        assert lamp_b == {
            "id": D2,
            "label": "Lamp B",
            "group": "Room B",
            "state": "on",
            "action": {"name": "set_onoff", "params": {"device": D2, "on": False}},
        }
        assert lamp_a["state"] == "off"
        assert lamp_a["action"]["params"] == {"device": D1, "on": True}

    async def test_unchosen_device_never_appears(self, live):
        plugin, _ = await live()
        ids = [i["id"] for i in (await plugin.fetch())["items"]]
        assert D3 not in ids

    async def test_nothing_chosen_gives_no_items_and_no_hub_call(self, live):
        plugin, client = await live(devices_cfg="")
        assert await plugin.fetch() == {"items": []}
        client.list_devices.assert_not_awaited()

    async def test_missing_non_onoff_or_unavailable_device_is_unavailable(self, live):
        hub = [
            _homey_device(D1, "Sensor", "Room A", has_onoff=False, on=None),
            _homey_device(D2, "Lamp B", "Room A", on=True, available=False),
        ]
        plugin, _ = await live(devices_cfg=f"{D1},{D2},{D3}", hub=hub)
        sensor, lamp, missing = (await plugin.fetch())["items"]
        for item in (sensor, lamp, missing):
            assert item["state"] == "unavailable"
            assert item["action"] is None
        assert sensor["label"] == "Sensor"
        assert lamp["label"] == "Lamp B"
        assert missing["label"] == "Missing device"
        assert missing["group"] is None

    async def test_device_with_unknown_on_state_is_unavailable(self, live):
        plugin, _ = await live(
            hub=[_homey_device(D1, "Lamp A", on=None)], devices_cfg=D1
        )
        [item] = (await plugin.fetch())["items"]
        assert item["state"] == "unavailable" and item["action"] is None

    @pytest.mark.parametrize(
        "exc", [HomeyUnreachable(), HomeyAuthError(), ValueError("x")]
    )
    async def test_hub_failure_makes_every_chosen_tile_unavailable(self, live, exc):
        plugin, client = await live()
        client.list_devices.side_effect = exc
        data = await plugin.fetch()
        assert [i["id"] for i in data["items"]] == [D2, D1]
        assert all(
            i["state"] == "unavailable" and i["action"] is None for i in data["items"]
        )
        assert KEY not in json.dumps(data)

    async def test_duplicate_chosen_ids_make_one_tile(self, live):
        plugin, _ = await live(devices_cfg=f"{D1}, {D1},")
        assert [i["id"] for i in (await plugin.fetch())["items"]] == [D1]

    async def test_two_fetches_within_two_seconds_make_one_hub_call(self, live):
        plugin, client = await live()
        await plugin.fetch()
        plugin._clock.now += 1.9
        await plugin.fetch()
        assert client.list_devices.await_count == 1
        plugin._clock.now += 0.2
        await plugin.fetch()
        assert client.list_devices.await_count == 2

    async def test_cache_is_not_shared_between_instances(self, live):
        a, client_a = await live()
        b, client_b = await live()
        await a.fetch()
        await b.fetch()
        client_a.list_devices.assert_awaited_once()
        client_b.list_devices.assert_awaited_once()

    async def test_configure_clears_the_cache(self, live):
        plugin, client = await live()
        await plugin.fetch()
        await plugin.configure({**GOOD, "devices": D1})
        # a new client is built lazily with the new config
        assert (await plugin.fetch())["items"][0]["id"] == D1

    async def test_fetch_output_has_no_config(self, live):
        plugin, _ = await live()
        text = json.dumps(await plugin.fetch())
        assert KEY not in text and "hub.example" not in text


class TestAction:
    async def test_sets_onoff_then_returns_the_read_back_item(self, live):
        plugin, client = await live()
        client.get_device.return_value = _homey_device(D1, "Lamp A", "Room A", on=True)
        result = await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        client.set_onoff.assert_awaited_once_with(D1, True)
        client.get_device.assert_awaited_once_with(D1)
        assert result == {
            "item": {
                "id": D1,
                "label": "Lamp A",
                "group": "Room A",
                "state": "on",
                "action": {"name": "set_onoff", "params": {"device": D1, "on": False}},
            }
        }

    async def test_returns_the_real_state_not_the_requested_one(self, live):
        plugin, client = await live()
        client.get_device.return_value = _homey_device(D1, "Lamp A", on=False)
        result = await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert result["item"]["state"] == "off"

    @pytest.mark.parametrize(
        "device", [D3, "", f" {D1}", f"{D1} ", D1[:-1], f"{D1},{D2}"]
    )
    async def test_device_not_chosen_is_refused_and_hub_never_called(
        self, live, device
    ):
        plugin, client = await live(devices_cfg=D1)
        with pytest.raises(PluginActionRefused):
            await plugin.perform_action("set_onoff", {"device": device, "on": True})
        client.set_onoff.assert_not_awaited()
        client.get_device.assert_not_awaited()
        client.list_devices.assert_not_awaited()

    async def test_case_difference_is_refused(self, live):
        plugin, client = await live(devices_cfg="abc-def")
        with pytest.raises(PluginActionRefused):
            await plugin.perform_action("set_onoff", {"device": "ABC-DEF", "on": True})
        client.set_onoff.assert_not_awaited()

    async def test_device_removed_from_settings_after_screen_loaded_is_refused(
        self, live
    ):
        plugin, client = await live(devices_cfg=f"{D1},{D2}")
        await plugin.fetch()
        await plugin.configure({**GOOD, "devices": D2})
        client = FakeClient.instances[-1]
        with pytest.raises(PluginActionRefused):
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        client.set_onoff.assert_not_awaited()

    async def test_empty_chosen_list_refuses_everything(self, live):
        plugin, client = await live(devices_cfg="")
        with pytest.raises(PluginActionRefused):
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        client.set_onoff.assert_not_awaited()

    async def test_refusal_message_is_plain_words(self, live):
        plugin, _ = await live()
        with pytest.raises(PluginActionRefused) as info:
            await plugin.perform_action("set_onoff", {"device": D3, "on": True})
        assert info.value.message == "Can't be switched from here."
        assert D3 not in info.value.message

    @pytest.mark.parametrize(
        "params",
        [
            {"on": True},
            {"device": 5, "on": True},
            {"device": D1},
            {"device": D1, "on": "true"},
            {"device": D1, "on": 1},
            {},
        ],
    )
    async def test_wrong_params_never_reach_the_hub(self, live, params):
        plugin, client = await live()
        with pytest.raises(PluginActionError):
            await plugin.perform_action("set_onoff", params)
        client.set_onoff.assert_not_awaited()

    async def test_action_clears_the_cache(self, live):
        plugin, client = await live()
        client.get_device.return_value = _homey_device(D1, "Lamp A", on=True)
        await plugin.fetch()
        await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        await plugin.fetch()
        assert client.list_devices.await_count == 2

    async def test_failed_action_also_clears_the_cache(self, live):
        plugin, client = await live()
        client.set_onoff.side_effect = HomeyUnreachable()
        await plugin.fetch()
        with pytest.raises(PluginActionError):
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        await plugin.fetch()
        assert client.list_devices.await_count == 2

    async def test_unreachable_during_action(self, live):
        plugin, client = await live()
        client.set_onoff.side_effect = HomeyUnreachable()
        with pytest.raises(PluginActionError) as info:
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert not isinstance(info.value, PluginActionRefused)
        assert info.value.message == "Couldn't reach Homey."

    async def test_bad_key_during_action(self, live):
        plugin, client = await live()
        client.set_onoff.side_effect = HomeyAuthError()
        with pytest.raises(PluginActionError) as info:
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert info.value.message == "Homey refused the API key."

    async def test_device_gone_on_hub(self, live):
        plugin, client = await live()
        client.set_onoff.side_effect = HomeyDeviceNotFound()
        with pytest.raises(PluginActionError) as info:
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert info.value.message == "That device isn't available."

    async def test_failed_read_back_is_an_error_not_a_success_item(self, live):
        plugin, client = await live()
        client.get_device.side_effect = HomeyUnreachable()
        with pytest.raises(PluginActionError) as info:
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert info.value.message == "Couldn't reach Homey."

    async def test_read_back_missing_device_is_an_error(self, live):
        plugin, client = await live()
        client.get_device.return_value = None
        with pytest.raises(PluginActionError):
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})

    async def test_unexpected_exception_text_never_escapes_as_action_error(self, live):
        plugin, client = await live()
        client.set_onoff.side_effect = RuntimeError(f"boom {KEY}")
        with pytest.raises(
            Exception
        ) as info:  # host maps any non-action error to a generic 500
            await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert (
            not isinstance(info.value, PluginActionError)
            or KEY not in info.value.message
        )

    async def test_unknown_action_name(self, live):
        plugin, client = await live()
        with pytest.raises(PluginActionError):
            await plugin.perform_action("reboot", {"device": D1, "on": True})
        client.set_onoff.assert_not_awaited()

    async def test_unavailable_read_back_item_has_no_action(self, live):
        plugin, client = await live()
        client.get_device.return_value = _homey_device(
            D1, "Lamp A", on=True, available=False
        )
        result = await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert result["item"]["state"] == "unavailable"
        assert result["item"]["action"] is None

    async def test_result_has_no_config(self, live):
        plugin, client = await live()
        client.get_device.return_value = _homey_device(D1, "Lamp A", on=True)
        result = await plugin.perform_action("set_onoff", {"device": D1, "on": True})
        assert KEY not in json.dumps(result)

"""Tests for the Homey plugin (plugin contract 1.0).

Run with the Calvin backend venv, from this repo's root:
    PYTHONPATH="$PWD:<calvin>/backend" <calvin>/backend/.venv/bin/python -m pytest homey -q

The hub is always mocked: no test contacts a real Homey.
"""

import importlib.util
import json
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

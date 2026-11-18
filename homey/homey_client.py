"""The only code in the Homey plugin that talks to the hub.

Endpoints follow Athom's public Web API reference; points the reference does
not state are listed as assumptions in API_NOTES.md. The key goes only in the
Authorization header. Every error raised here carries a fixed plain-words
message with no key, address or response text, because the host shows plugin
errors on screen and writes them to the server log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

# Well under the host's 10 s action limit, so a dead hub answers
# "Couldn't reach Homey." instead of a host timeout.
DEFAULT_TIMEOUT = 5.0

_DEVICES = "/api/manager/devices/device"
_ZONES = "/api/manager/zones/zone"


class HomeyUnreachable(Exception):
    """The hub did not answer, or answered with something unusable."""

    def __init__(self) -> None:
        super().__init__("Couldn't reach Homey.")


class HomeyAuthError(Exception):
    """The hub refused the key (bad key, or a scope the key lacks)."""

    def __init__(self) -> None:
        super().__init__("Homey refused the API key.")


class HomeyDeviceNotFound(Exception):
    """The hub has no device with that id."""

    def __init__(self) -> None:
        super().__init__("Homey has no such device.")


@dataclass(frozen=True)
class HomeyDevice:
    id: str
    name: str
    zone: str | None
    has_onoff: bool
    on: bool | None
    available: bool


def _parse_device(raw: Any, zones: dict[str, str]) -> HomeyDevice | None:
    """Build a device from one hub entry; a malformed entry never raises."""
    if not isinstance(raw, dict):
        return None
    device_id = raw.get("id")
    if not isinstance(device_id, str) or not device_id:
        return None
    name = raw.get("name")
    name = name if isinstance(name, str) and name.strip() else device_id
    zone_id = raw.get("zone")
    zone = zones.get(zone_id) if isinstance(zone_id, str) else None
    capabilities = raw.get("capabilities")
    has_onoff = isinstance(capabilities, list) and "onoff" in capabilities
    on: bool | None = None
    objs = raw.get("capabilitiesObj")
    if has_onoff and isinstance(objs, dict):
        onoff = objs.get("onoff")
        value = onoff.get("value") if isinstance(onoff, dict) else None
        on = value if isinstance(value, bool) else None
    # Missing or odd fields mean the device is not usable, not that we crash.
    available = raw.get("available") is True
    return HomeyDevice(device_id, name, zone, has_onoff, on, available)


class HomeyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=base_url.strip().rstrip("/"),
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:  # never leak the key through a repr
        return "HomeyClient()"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except (httpx.HTTPError, ValueError):
            raise HomeyUnreachable() from None
        if response.status_code in (401, 403):
            raise HomeyAuthError()
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise HomeyUnreachable() from None

    @staticmethod
    def _device_path(device_id: str) -> str | None:
        if not device_id or device_id in (".", ".."):
            return None
        return f"{_DEVICES}/{quote(device_id, safe='')}"

    async def _zone_names(self) -> dict[str, str]:
        """Zone id -> name. Any failure (including a missing scope) gives no labels."""
        try:
            response = await self._request("GET", _ZONES)
            body = self._json(response)
        except (HomeyUnreachable, HomeyAuthError):
            return {}
        if response.status_code != 200 or not isinstance(body, dict):
            return {}
        return {
            zone_id: zone["name"]
            for zone_id, zone in body.items()
            if isinstance(zone, dict) and isinstance(zone.get("name"), str)
        }

    async def list_devices(self) -> list[HomeyDevice]:
        response = await self._request("GET", _DEVICES)
        if response.status_code != 200:
            raise HomeyUnreachable()
        body = self._json(response)
        if not isinstance(body, dict):
            raise HomeyUnreachable()
        zones = await self._zone_names()
        devices = (_parse_device(raw, zones) for raw in body.values())
        return [d for d in devices if d is not None]

    async def get_device(self, device_id: str) -> HomeyDevice | None:
        path = self._device_path(device_id)
        if path is None:
            return None
        response = await self._request("GET", path)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise HomeyUnreachable()
        device = _parse_device(self._json(response), await self._zone_names())
        if device is None:
            raise HomeyUnreachable()
        return device

    async def set_onoff(self, device_id: str, on: bool) -> None:
        path = self._device_path(device_id)
        if path is None:
            raise HomeyDeviceNotFound()
        response = await self._request(
            "PUT", f"{path}/capability/onoff", json={"value": bool(on)}
        )
        if response.status_code == 404:
            raise HomeyDeviceNotFound()
        if not 200 <= response.status_code < 300:
            raise HomeyUnreachable()

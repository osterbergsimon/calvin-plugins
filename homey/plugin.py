"""Homey on/off tiles: switch chosen Homey Pro devices from a Calvin screen.

One declarative class (plugin contract 1.0). The hub address and API key are
used only by `HomeyClient`; nothing here logs config, and every message shown
to a caller is plain words with no key, address or device detail.
"""

import asyncio
import copy
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.plugins.actions import PluginActionError, PluginActionRefused
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin

# -- Hub client ----------------------------------------------------------
# The only code that talks to the hub. Endpoints follow Athom's public Web API
# reference (see API_NOTES.md). Every error raised here carries a fixed
# plain-words message: no key, address or response text.

# Well under the host's 10 s action limit, so a dead hub answers
# "Couldn't reach Homey." instead of a host timeout.
DEFAULT_TIMEOUT = 5.0
# One public call may make several requests (devices, then zones), and each
# timeout applies per phase. This caps the whole call under the host's limit.
DEFAULT_DEADLINE = 4.0

# The hub is trusted to be a Homey, not to send sane text or small bodies.
MAX_NAME_CHARS = 80
MAX_ID_CHARS = 256
MAX_BODY_BYTES = 2_000_000
# Zone names change rarely; a failed zone read is retried sooner.
ZONE_CACHE_SECONDS = 60.0
ZONE_FAILURE_SECONDS = 5.0

# httpx logs every request URL at INFO and httpcore logs the host at DEBUG;
# the server log must hold no hub address or device id.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

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


def _clean_text(value: Any, fallback: str = "", limit: int = MAX_NAME_CHARS) -> str:
    """Printable, single-spaced text of at most `limit` characters.

    Drops control, format, surrogate, private-use, unassigned and line/paragraph
    separator characters (they carry bidi overrides and escapes, or cannot be
    encoded), turns other whitespace into one space and ends
    an over-long text with an ellipsis. Empty results use `fallback`.
    """
    for candidate in (value, fallback):
        if not isinstance(candidate, str):
            continue
        head = candidate[: limit * 8]  # never walk a multi-megabyte string
        kept = "".join(
            " "
            if ch.isspace()
            else ""
            if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
            else ch
            for ch in head
        )
        text = " ".join(kept.split())
        if len(text) > limit or (text and len(candidate) > len(head)):
            text = text[: limit - 1].rstrip() + "\u2026"
        if text:
            return text
    return ""


def _valid_key(key: str) -> bool:
    """A key that can sit in an HTTP header: ASCII, printable, no spaces."""
    return bool(key) and key.isascii() and key.isprintable() and " " not in key


def _parse_device(raw: Any, zones: dict[str, str]) -> HomeyDevice | None:
    """Build a device from one hub entry; a malformed entry never raises."""
    if not isinstance(raw, dict):
        return None
    device_id = raw.get("id")
    if (
        not isinstance(device_id, str)
        or not device_id
        or len(device_id) > MAX_ID_CHARS
        or not device_id.isprintable()
    ):
        return None
    name = _clean_text(raw.get("name"), device_id)
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


@dataclass(frozen=True)
class _Reply:
    status_code: int
    content: bytes


class HomeyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        deadline: float = DEFAULT_DEADLINE,
    ) -> None:
        self.timeout = timeout
        self.deadline = deadline
        self._clock = time.monotonic
        # Zone id -> name, and when it stops being fresh. get_device() reuses
        # the last names however old; only list reads refresh them.
        self._zones: dict[str, str] = {}
        self._zones_until = 0.0
        headers: dict[str, str] | None = None
        try:
            if not _valid_key(api_key.strip()):
                raise ValueError
            headers = {"Authorization": f"Bearer {api_key.strip()}"}
            self._http = httpx.AsyncClient(
                base_url=base_url.strip().rstrip("/"),
                headers=headers,
                timeout=timeout,
                transport=transport,
                # Never let the environment route the key through a proxy, and
                # never follow a redirect (the key would go to the new address).
                trust_env=False,
                follow_redirects=False,
            )
        except Exception:  # noqa: BLE001 - fixed words; the key must not travel
            # The raised error's traceback keeps this frame, so empty the
            # locals that hold the key (loguru prints frame variables).
            api_key = ""
            headers = None
            raise ValueError("The Homey API key or address can't be used.") from None

    def __repr__(self) -> str:  # never leak the key through a repr
        return "HomeyClient()"

    async def _within_deadline(self, work: Any) -> Any:
        try:
            async with asyncio.timeout(self.deadline):
                return await work
        except TimeoutError:
            raise HomeyUnreachable() from None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> "_Reply":
        try:
            async with self._http.stream(method, path, **kwargs) as response:
                status = response.status_code
                body = bytearray()
                if status not in (401, 403):
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BODY_BYTES:
                            raise HomeyUnreachable()
        except Exception:  # noqa: BLE001 - any failure is "not reachable", text never kept
            raise HomeyUnreachable() from None
        if status in (401, 403):
            raise HomeyAuthError()
        return _Reply(status, bytes(body))

    @staticmethod
    def _json(reply: "_Reply") -> Any:
        try:
            return json.loads(reply.content)
        except Exception:  # noqa: BLE001 - bad JSON, or nesting too deep
            raise HomeyUnreachable() from None

    @staticmethod
    def _device_path(device_id: str) -> str | None:
        if not device_id or device_id in (".", ".."):
            return None
        return f"{_DEVICES}/{quote(device_id, safe='')}"

    async def _zone_names(self) -> dict[str, str]:
        """Zone id -> name, cached. A failure (including a missing scope) keeps the
        last good names, or none if there never were any."""
        now = self._clock()
        if now < self._zones_until:
            return self._zones
        zones = self._zones  # a failed read keeps the last good names
        ttl = ZONE_FAILURE_SECONDS
        try:
            response = await self._request("GET", _ZONES)
            body = self._json(response)
            if response.status_code == 200 and isinstance(body, dict):
                zones = {}
                for zone_id, zone in body.items():
                    name = (
                        _clean_text(zone.get("name")) if isinstance(zone, dict) else ""
                    )
                    if name:
                        zones[zone_id] = name
                ttl = ZONE_CACHE_SECONDS
        except (HomeyUnreachable, HomeyAuthError):
            pass
        self._zones, self._zones_until = zones, now + ttl
        return zones

    async def _list_devices(self) -> list[HomeyDevice]:
        response = await self._request("GET", _DEVICES)
        if response.status_code != 200:
            raise HomeyUnreachable()
        body = self._json(response)
        if not isinstance(body, dict):
            raise HomeyUnreachable()
        zones = await self._zone_names()
        unique: dict[str, HomeyDevice] = {}
        for raw in body.values():
            device = _parse_device(raw, zones)
            if device is not None:
                unique.setdefault(device.id, device)
        return list(unique.values())

    async def _get_device(self, device_id: str) -> HomeyDevice | None:
        path = self._device_path(device_id)
        if path is None:
            return None
        response = await self._request("GET", path)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise HomeyUnreachable()
        # No zones call: the last listing's names are enough for a read-back.
        device = _parse_device(self._json(response), self._zones)
        if device is None or device.id != device_id:
            raise HomeyUnreachable()
        return device

    async def _set_onoff(self, device_id: str, on: bool) -> None:
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

    async def list_devices(self) -> list[HomeyDevice]:
        return await self._within_deadline(self._list_devices())

    async def get_device(self, device_id: str) -> HomeyDevice | None:
        return await self._within_deadline(self._get_device(device_id))

    async def set_onoff(self, device_id: str, on: bool) -> None:
        return await self._within_deadline(self._set_onoff(device_id, on))


# -- Chosen devices ------------------------------------------------------
# One comma-separated string of Homey device ids (config values are bare
# scalars). This is the only parser: the scan, fetch() and the action
# allowlist all use it. Homey device ids are UUIDs, so they never contain commas.


def parse_device_ids(raw: object) -> list[str]:
    """Split on commas, trim, drop empties and later duplicates, keep order."""
    if not isinstance(raw, str):
        return []
    seen: dict[str, None] = {}
    for part in raw.split(","):
        part = part.strip()
        if part:
            seen.setdefault(part, None)
    return list(seen)


MSG_UNREACHABLE = "Couldn't reach Homey."
MSG_KEY_REFUSED = "Homey refused the API key."
MSG_REFUSED = "Can't be switched from here."
MSG_GONE = "That device isn't available."

# A short per-instance cache so the refetches every open screen makes after an
# action become one hub request. An action clears it.
FETCH_CACHE_SECONDS = 2.0

# One budget for a whole tap (the switch and its read-back, and the settle
# wait between two reads), inside the host's 10 s action limit.
ACTION_BUDGET_SECONDS = 7.0
# A hub can answer the switch before the device reports; one wait and one more
# read, then the answer is whatever the hub says.
SETTLE_SECONDS = 0.4


def _clean(config: dict[str, Any]) -> tuple[str, str]:
    """(host without trailing slash, trimmed key) from a normalized config."""
    host = str(config.get("host") or "").strip().rstrip("/")
    key = str(config.get("api_key") or "").strip()
    return host, key


_NETLOC_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$"
)


def _valid_host(host: str) -> bool:
    """An http(s) address: a host name or IP and optional port, no login, query or fragment."""
    scheme, sep, rest = host.partition("://")
    if scheme not in ("http", "https") or not sep:
        return False
    netloc, _, path = rest.partition("/")
    if not _NETLOC_RE.match(netloc) or any(c in path for c in "?#@ \t\n"):
        return False
    try:
        httpx.URL(host)
    except Exception:  # noqa: BLE001 - never echo the parser's text
        return False
    return True


def _usable(host: str, key: str) -> bool:
    return _valid_host(host) and _valid_key(key)


class HomeyServicePlugin(ServicePlugin):
    """Switch chosen Homey Pro devices on and off."""

    metadata = PluginMetadata(
        type_id="homey",
        name="Homey",
        description="On/off tiles for chosen Homey Pro devices.",
        icon="mdi:lightbulb-outline",
        default_instance_name="Homey",
        instance_label="hub",
        instance_config_schema={
            "host": {
                "type": "string",
                "label": "Hub address",
                "description": (
                    "The address of your Homey Pro on your network, "
                    "for example http://homey.local."
                ),
                "required": True,
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "http://homey.local",
                    "endpoint": True,
                    "validation": {"required": True, "type": "url"},
                },
            },
            "api_key": {
                "type": "password",
                "label": "API key",
                "description": (
                    "In the Homey app: Settings → API Keys. Give the key the scopes "
                    "homey.device.readonly and homey.device.control."
                ),
                "required": True,
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter your Homey API key",
                    "validation": {"required": True},
                },
            },
            "devices": {
                "type": "string",
                "label": "Devices",
                "description": "The devices a tap on this screen can switch.",
                "default": "",
                "ui": {"component": "multi-select-scan"},
            },
        },
        actions=[
            {
                "name": "set_onoff",
                "label": "Switch",
                "params": {
                    "device": {"type": "string"},
                    "on": {"type": "boolean"},
                },
            }
        ],
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
        ],
        display_schema={
            "kind": "switch-grid",
            "data_path": "$.items",
            "poll_interval_ms": 15000,
            "unreachable_text": "Couldn't reach Homey",
            "empty_text": "No devices chosen yet.",
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._client: HomeyClient | None = None
        self._clock = time.monotonic
        self._cache: tuple[float, tuple[str, ...], list[dict[str, Any]]] | None = None
        # Bumped by every action and config change; a fetch that began before
        # one of them must not write its (possibly stale) result to the cache.
        self._generation = 0

    @property
    def host(self) -> str:
        return _clean(self.config)[0]

    @property
    def api_key(self) -> str:
        return _clean(self.config)[1]

    async def initialize(self) -> None:
        """Validate config and build the hub client.

        No local here holds the key, so a traceback of an error raised from
        this frame (the host logs it with variables) cannot print it.
        """
        await self._close_client()
        if not _valid_host(self.host):
            raise ValueError(
                "The Homey hub address must be an http:// or https:// address"
            )
        if not _valid_key(self.api_key):
            raise ValueError("A usable Homey API key is required")
        try:
            self._client = HomeyClient(self.host, self.api_key)
        except Exception:  # noqa: BLE001 - fixed words only
            raise ValueError("The Homey API key or address can't be used.") from None

    async def cleanup(self) -> None:
        await self._close_client()

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply config; drop the client so it is rebuilt with the new key."""
        await super().configure(config)
        await self._close_client()

    async def _close_client(self) -> None:
        self._cache = None
        self._generation += 1
        client, self._client = self._client, None
        if client:
            await client.aclose()

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        return _usable(*_clean(cls.normalize_config(config)))

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """One device-list read with the typed (or stored) address and key."""
        host, key = _clean(cls.normalize_config(config))
        if not _usable(host, key):
            return {
                "success": False,
                "message": "Enter a valid hub address and API key.",
            }
        client = None
        try:
            client = HomeyClient(host, key)
            devices = await client.list_devices()
        except HomeyAuthError:
            return {"success": False, "message": MSG_KEY_REFUSED}
        except Exception:  # noqa: BLE001 - shown on screen: fixed words only
            return {"success": False, "message": MSG_UNREACHABLE}
        finally:
            if client is not None:
                await client.aclose()
        return {
            "success": True,
            "message": f"Connected to Homey ({len(devices)} devices).",
        }

    @classmethod
    async def scan_options_with_config(
        cls, field_key: str, config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """List devices that can be switched on and off, as {value, label}."""
        if field_key != "devices":
            return None
        host, key = _clean(cls.normalize_config(config))
        if not _usable(host, key):
            return {"options": [], "error": "Enter the hub address and API key first."}
        client = None
        try:
            client = HomeyClient(host, key)
            devices = await client.list_devices()
        except HomeyAuthError:
            return {"options": [], "error": MSG_KEY_REFUSED}
        except Exception:  # noqa: BLE001 - shown on screen: fixed words only
            return {"options": [], "error": MSG_UNREACHABLE}
        finally:
            if client is not None:
                await client.aclose()
        options = [
            {"value": d.id, "label": f"{d.name} ({d.zone})" if d.zone else d.name}
            for d in devices
            if d.has_onoff
        ]
        options.sort(key=lambda o: (o["label"].casefold(), o["value"]))
        return {"options": options}

    # -- items ------------------------------------------------------------

    @staticmethod
    def _item(
        device_id: str, device: HomeyDevice | None, label: str | None = None
    ) -> dict:
        """One tile. Anything that cannot be switched is unavailable with no action."""
        usable = (
            device is not None
            and device.has_onoff
            and device.available
            and device.on is not None
        )
        if device is not None:
            label = device.name
        state = ("on" if device.on else "off") if usable else "unavailable"
        return {
            "id": device_id,
            "label": label or "Missing device",
            "group": device.zone if device is not None else None,
            "state": state,
            "action": (
                {
                    "name": "set_onoff",
                    "params": {"device": device_id, "on": state == "off"},
                }
                if usable
                else None
            ),
        }

    async def _hub(self) -> HomeyClient:
        if self._client is None:
            # A stopped or cleaned-up plugin must not build a client nobody closes.
            if not self.is_running():
                raise HomeyUnreachable()
            await self.initialize()
        if self._client is None:  # pragma: no cover - initialize() sets it or raises
            raise HomeyUnreachable()
        return self._client

    async def fetch(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """The chosen devices, in the chosen order, from one hub read (cached 2 s)."""
        chosen = parse_device_ids(self.config.get("devices"))
        if not chosen:
            return {"items": []}
        now = self._clock()
        cached = self._cache
        if (
            cached
            and cached[1] == tuple(chosen)
            and now - cached[0] < FETCH_CACHE_SECONDS
        ):
            return {"items": copy.deepcopy(cached[2])}
        generation = self._generation
        try:
            client = await self._hub()
            by_id = {d.id: d for d in await client.list_devices()}
            items = [self._item(i, by_id.get(i)) for i in chosen]
        except Exception:  # noqa: BLE001 - keep the tiles on screen, say "Not responding"
            items = [self._item(i, None, "Unknown device") for i in chosen]
        # A failure is cached too, so a dead hub is asked once per window, not
        # once per open screen.
        if generation == self._generation:
            # Stamped when the read ended: a call that used up its deadline
            # must still hold for the full window.
            self._cache = (self._clock(), tuple(chosen), items)
        return {"items": copy.deepcopy(items)}

    async def perform_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Switch one chosen device. The chosen list is the only allowlist."""
        if name != "set_onoff":
            raise PluginActionError("This plugin has no such action.")
        device_id = params.get("device")
        on = params.get("on")
        if not isinstance(device_id, str) or not isinstance(on, bool):
            raise PluginActionError("That request wasn't understood.")
        # Exact string equality against the current chosen list, before any hub call.
        if device_id not in parse_device_ids(self.config.get("devices")):
            raise PluginActionRefused(MSG_REFUSED)
        try:
            client = await self._hub()
            self._cache = None
            self._generation += 1
            async with asyncio.timeout(ACTION_BUDGET_SECONDS):
                await client.set_onoff(device_id, on)
                device = await client.get_device(device_id)
                if device is not None and device.on != on:
                    # The hub may answer before the device reports: look once
                    # more, then show what the hub says, never the request.
                    await asyncio.sleep(SETTLE_SECONDS)
                    try:
                        device = await client.get_device(device_id)
                    except HomeyUnreachable:
                        pass  # keep the first honest read
        except TimeoutError:
            raise PluginActionError(MSG_UNREACHABLE) from None
        except HomeyAuthError:
            raise PluginActionError(MSG_KEY_REFUSED) from None
        except HomeyDeviceNotFound:
            raise PluginActionError(MSG_GONE) from None
        except (HomeyUnreachable, ValueError):  # ValueError: stored address unusable
            raise PluginActionError(MSG_UNREACHABLE) from None
        finally:
            self._cache = None
            self._generation += 1
        if device is None:
            raise PluginActionError(MSG_UNREACHABLE)
        return {"item": self._item(device_id, device)}

"""SL Departures service plugin — live SL public-transport board for one stop.

Calvin plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, `fetch()` as the single data verb, and the
built-in `status` renderer for both the panel (list) and the clock-bar strip.
Backed by the keyless SL Transport API (https://transport.integration.sl.se).
"""

from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class SLDeparturesServicePlugin(ServicePlugin):
    """Service plugin showing SL departures for a single stop."""

    BASE_URL = "https://transport.integration.sl.se"

    _sites_cache: list[dict[str, Any]] | None = None
    _sites_cache_at: float = 0.0
    _SITES_TTL_SECONDS = 6 * 3600

    metadata = PluginMetadata(
        type_id="sl_departures",
        name="SL Departures",
        description="Live SL departures for a Stockholm stop, filterable by line, mode and direction",
        default_instance_name="SL Departures",
        instance_label="Stop",
        supports_multiple_instances=True,
        instance_config_schema={
            "stop_name": {
                "type": "string",
                "description": "Stop name (resolved to a site id on Test Connection)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Tappström",
                    "validation": {"required": True},
                },
            },
            "site_id": {
                "type": "integer",
                "description": "SL site id (auto-filled after Test; wins over stop name if set)",
                "default": 0,
                "ui": {
                    "component": "number",
                    "placeholder": "auto-filled after Test",
                    "help_text": "Leave blank unless the stop name is ambiguous",
                },
            },
            "lines": {
                "type": "string",
                "description": "Only show these lines (comma-separated). Empty = all lines.",
                "default": "",
                "ui": {"component": "input", "placeholder": "176, 177"},
            },
            "modes": {
                "type": "string",
                "description": "Only show these modes (comma-separated): bus, metro, train, tram, ship. Empty = all.",
                "default": "",
                "ui": {"component": "input", "placeholder": "bus, train"},
            },
            "direction": {
                "type": "string",
                "description": "Filter by SL direction code",
                "default": "Any",
                "ui": {
                    "component": "select",
                    "options": [
                        {"value": "Any", "label": "Any direction"},
                        {"value": "1", "label": "Direction 1"},
                        {"value": "2", "label": "Direction 2"},
                    ],
                    "help_text": "SL's direction codes are arbitrary per line; usually leave Any and filter by line",
                },
            },
            "max_departures": {
                "type": "integer",
                "description": "Maximum rows on the panel",
                "default": 8,
                "ui": {"component": "number", "placeholder": "8", "validation": {"min": 1, "max": 30}},
            },
            "forecast_minutes": {
                "type": "integer",
                "description": "How far ahead to look (minutes)",
                "default": 60,
                "ui": {"component": "number", "placeholder": "60", "validation": {"min": 5, "max": 180}},
            },
            "clockbar_show_following": {
                "type": "boolean",
                "description": "Clock bar shows the departure after next as well",
                "default": True,
                "ui": {"component": "checkbox", "help_text": "Off = clock bar shows only the next departure"},
            },
        },
        ui_actions=[
            {"id": "save", "type": "save", "label": "Save Settings", "style": "primary", "scope": "instance"},
            {"id": "test", "type": "test", "label": "Test Connection", "style": "secondary", "scope": "instance"},
        ],
        # Panel: one row per departure, drawn by the built-in status list renderer.
        display_schema={
            "kind": "status",
            "layout": "list",
            "data_path": "$.departures",
            "item": {
                "label_path": "$.label",
                "value_path": "$.display",
                "status_path": "$.status",
            },
            "poll_interval_ms": 30000,
        },
        # Clock bar: stop name + next (and optionally following) departure.
        statusbar_schema={
            "kind": "status",
            "item": {
                "label_path": "$.clockbar.label",
                "value_path": "$.clockbar.value",
                "status_path": "$.clockbar.status",
            },
            "poll_interval_ms": 30000,
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)

    # Config accessors — values live in self.config (schema-normalized).

    @property
    def stop_name(self) -> str:
        return str(self.config.get("stop_name") or "").strip()

    @property
    def site_id(self) -> int | None:
        try:
            value = int(self.config.get("site_id"))
        except (TypeError, ValueError):
            return None
        return value or None

    @property
    def lines(self) -> set[str]:
        return {p.strip() for p in str(self.config.get("lines") or "").split(",") if p.strip()}

    @property
    def modes(self) -> set[str]:
        return {p.strip().upper() for p in str(self.config.get("modes") or "").split(",") if p.strip()}

    @property
    def direction(self) -> str:
        value = str(self.config.get("direction") or "Any").strip()
        return value if value in ("1", "2") else "Any"

    @property
    def max_departures(self) -> int:
        return min(max(int(self.config.get("max_departures") or 8), 1), 30)

    @property
    def forecast_minutes(self) -> int:
        return min(max(int(self.config.get("forecast_minutes") or 60), 5), 180)

    @property
    def clockbar_show_following(self) -> bool:
        return bool(self.config.get("clockbar_show_following", True))

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require a stop name or a site id; direction must be Any/1/2."""
        normalized = cls.normalize_config(config)
        stop_name = str(normalized.get("stop_name") or "").strip()
        try:
            has_site = bool(int(normalized.get("site_id")))
        except (TypeError, ValueError):
            has_site = False
        if not stop_name and not has_site:
            return False
        direction = str(normalized.get("direction") or "Any").strip()
        return direction in ("Any", "1", "2")

    def _filter_departures(self, departures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep departures matching the configured lines, modes and direction."""
        lines, modes, direction = self.lines, self.modes, self.direction
        kept: list[dict[str, Any]] = []
        for dep in departures:
            line = dep.get("line") or {}
            designation = str(line.get("designation") or "")
            mode = str(line.get("transport_mode") or "").upper()
            if lines and designation not in lines:
                continue
            if modes and mode not in modes:
                continue
            if direction != "Any" and str(dep.get("direction_code") or "") != direction:
                continue
            kept.append(dep)
        return kept

    def _sort_and_limit(self, departures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort by expected time (fallback scheduled) and cap at max_departures."""
        def when(dep: dict[str, Any]) -> str:
            return str(dep.get("expected") or dep.get("scheduled") or "")

        return sorted(departures, key=when)[: self.max_departures]

    @staticmethod
    def _status_for(dep: dict[str, Any]) -> str:
        """Color on the wall = disruption only: cancelled -> error, deviations -> warn."""
        if str(dep.get("state") or "").upper() == "CANCELLED":
            return "error"
        if dep.get("deviations"):
            return "warn"
        return "ok"

    @classmethod
    def _shape_departure(cls, dep: dict[str, Any]) -> dict[str, Any]:
        """One panel row: '176 · Stenhamra' with SL's human display time."""
        designation = str((dep.get("line") or {}).get("designation") or "").strip()
        destination = str(dep.get("destination") or "").strip()
        label = " · ".join(part for part in (designation, destination) if part)
        return {
            "label": label,
            "display": str(dep.get("display") or "").strip(),
            "status": cls._status_for(dep),
        }

    @staticmethod
    def _compact_display(dep: dict[str, Any]) -> str:
        """Clock-bar entry: '176·3′' ('N min' -> 'N′', 'Nu' kept as-is)."""
        designation = str((dep.get("line") or {}).get("designation") or "").strip()
        short = str(dep.get("display") or "").strip().replace(" min", "′")
        return f"{designation}·{short}" if short else designation

    def _shape_clockbar(self, departures: list[dict[str, Any]]) -> dict[str, Any]:
        """Next (and optionally following) filtered departure, stop name as label."""
        if not departures:
            return {"label": self.stop_name, "value": "—", "status": "ok"}
        count = 2 if self.clockbar_show_following else 1
        value = " · ".join(self._compact_display(dep) for dep in departures[:count])
        return {"label": self.stop_name, "value": value, "status": self._status_for(departures[0])}

    def _shape_for_display(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Filter/sort raw SL departures and shape for the status renderers."""
        if isinstance(raw, dict) and raw.get("error"):
            return {
                "stop": self.stop_name,
                "departures": [],
                "clockbar": self._shape_clockbar([]),
                "error": raw["error"],
            }
        raw_departures = raw.get("departures", []) if isinstance(raw, dict) else (raw or [])
        filtered = self._sort_and_limit(self._filter_departures(raw_departures))
        if not filtered:
            empty = {
                "label": f"No departures in the next {self.forecast_minutes} min",
                "display": "",
                "status": "ok",
            }
            return {"stop": self.stop_name, "departures": [empty], "clockbar": self._shape_clockbar([])}
        return {
            "stop": self.stop_name,
            "departures": [self._shape_departure(dep) for dep in filtered],
            "clockbar": self._shape_clockbar(filtered),
        }

    @staticmethod
    def _match_sites(sites: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Match a typed stop name against the Sites list: exact preferred, else contains."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        exact = [
            {"id": s.get("id"), "name": s.get("name")}
            for s in sites
            if str(s.get("name") or "").strip().lower() == needle
        ]
        if exact:
            return exact
        return [
            {"id": s.get("id"), "name": s.get("name")}
            for s in sites
            if needle in str(s.get("name") or "").strip().lower()
        ]

    @classmethod
    async def _fetch_sites(cls) -> list[dict[str, Any]]:
        """Fetch (and cache) the full SL Sites list. Shared across instances."""
        import time

        now = time.time()
        if cls._sites_cache is not None and (now - cls._sites_cache_at) < cls._SITES_TTL_SECONDS:
            return cls._sites_cache
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{cls.BASE_URL}/v1/sites")
            response.raise_for_status()
            cls._sites_cache = response.json()
            cls._sites_cache_at = now
        return cls._sites_cache

    async def _resolve_site(self) -> tuple[int | None, str | None, list[dict[str, Any]]]:
        """Resolve the configured stop to (site_id, name, candidates).

        site_id override wins. Otherwise fuzzy-match the name: a single match
        resolves, multiple matches return candidates, none/error returns empty.
        """
        if self.site_id:
            return self.site_id, self.stop_name, []
        try:
            sites = await self._fetch_sites()
        except httpx.HTTPError:
            logger.exception("[SL] Error fetching sites")
            return None, None, []
        matches = self._match_sites(sites, self.stop_name)
        if len(matches) == 1:
            return matches[0]["id"], matches[0]["name"], []
        return None, None, matches

    @classmethod
    async def _get_departures(cls, site_id: int, forecast: int = 60) -> dict[str, Any]:
        """Raw departures for a site from the SL Transport API (may raise httpx errors)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{cls.BASE_URL}/v1/sites/{site_id}/departures",
                params={"forecast": forecast},
            )
            response.raise_for_status()
            return response.json()

    async def _fetch_departures(self, site_id: int) -> dict[str, Any]:
        """Departures for a site, with network errors turned into a display error."""
        try:
            return await self._get_departures(site_id, self.forecast_minutes)
        except httpx.HTTPError:
            logger.exception("[SL] Error fetching departures")
            return {"error": "Couldn't reach SL — retrying"}

    async def fetch(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Resolve the stop, fetch its departures, and shape for the status renderers."""
        site_id, _name, candidates = await self._resolve_site()
        if site_id is None:
            if candidates:
                listed = ", ".join(f"{c['id']} {c['name']}" for c in candidates[:6])
                message = f"Several stops match '{self.stop_name}': {listed} — set the site id in settings"
            else:
                message = f"No SL stop matches '{self.stop_name}' — check the spelling in settings"
            return self._shape_for_display({"error": message})
        raw = await self._fetch_departures(site_id)
        return self._shape_for_display(raw)

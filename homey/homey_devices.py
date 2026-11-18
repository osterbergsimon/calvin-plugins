"""The chosen-devices list: one comma-separated string of Homey device ids.

Config values are bare scalars, so the devices live in one string. This is the
only parser: the scan, fetch() and the action allowlist all use it. Homey
device ids are UUIDs, so they never contain commas.
"""

from __future__ import annotations


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

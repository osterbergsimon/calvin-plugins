#!/usr/bin/env python3
"""Validate a Calvin plugin without installing it.

Usage:
    python scripts/validate_plugin.py <plugin-dir> [<plugin-dir> ...]
    python scripts/validate_plugin.py --all

Checks:
  - plugin.json is valid JSON and has the required manifest fields
  - plugin.py imports without error
  - register_plugin_types() returns a non-empty list
  - every returned definition normalizes via PluginDefinition.from_raw()
    (this is what catches display_schema.kind typos, missing required
    fields, unsupported protocol versions, etc. — the same validation
    Calvin runs at install time)

Requires the Calvin host repo as a sibling at ../calvin (or set the
CALVIN_REPO env var). Exits 0 on success, non-zero on any failure.

Examples:
    python scripts/validate_plugin.py mealie
    python scripts/validate_plugin.py mealie weather imap
    python scripts/validate_plugin.py --all
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MANIFEST_FIELDS = ("id", "name", "version", "type")
VALID_PLUGIN_TYPES = {"calendar", "image", "service", "backend", "theme"}


def find_calvin_repo() -> Path | None:
    """Locate the Calvin host repo so we can import app.plugins.definitions."""
    env = os.environ.get("CALVIN_REPO")
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if (candidate / "backend" / "app").is_dir() else None
    candidate = (REPO_ROOT.parent / "calvin").resolve()
    return candidate if (candidate / "backend" / "app").is_dir() else None


def _find_host_venv_python(calvin_repo: Path) -> Path | None:
    """Return the path to the host's venv python interpreter, if present."""
    for candidate in (
        calvin_repo / "backend" / ".venv" / "Scripts" / "python.exe",  # Windows
        calvin_repo / "backend" / ".venv" / "bin" / "python",  # POSIX
    ):
        if candidate.is_file():
            return candidate
    return None


def _reexec_under_host_venv_if_needed(calvin_repo: Path) -> None:
    """If we're not already running under the host's venv, re-exec there.

    Avoids 'ModuleNotFoundError: loguru' (and similar) when the script is
    invoked with the user's system python instead of the host backend's venv.
    """
    venv_python = _find_host_venv_python(calvin_repo)
    if venv_python is None:
        return  # No venv yet — let the import fail with a clear message.
    if Path(sys.executable).resolve() == venv_python.resolve():
        return  # Already running under the host venv.
    if os.environ.get("_CALVIN_VALIDATE_REEXECED"):
        return  # Guard against re-exec loops.
    os.environ["_CALVIN_VALIDATE_REEXECED"] = "1"
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


def load_plugin_definition_class():
    """Add the Calvin backend to sys.path and return PluginDefinition."""
    calvin_repo = find_calvin_repo()
    if calvin_repo is None:
        sys.stderr.write(
            "ERROR: could not locate the Calvin host repo.\n"
            "       Expected at ../calvin or set CALVIN_REPO env var.\n"
        )
        sys.exit(2)
    _reexec_under_host_venv_if_needed(calvin_repo)
    backend_dir = str(calvin_repo / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from app.plugins.definitions import PluginDefinition  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            f"ERROR: could not import {exc.name!r} from the Calvin backend.\n"
            f"       Make sure the host venv is set up (cd {calvin_repo}/backend && uv sync --extra dev).\n"
        )
        sys.exit(2)
    return PluginDefinition


def validate_manifest(plugin_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        errors.append("plugin.json is missing")
        return errors
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"plugin.json is not valid JSON: {exc}")
        return errors
    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            errors.append(f"plugin.json missing required field: {field!r}")
    plugin_type = manifest.get("type")
    if plugin_type is not None and plugin_type not in VALID_PLUGIN_TYPES:
        errors.append(
            f"plugin.json type={plugin_type!r} is not one of "
            f"{sorted(VALID_PLUGIN_TYPES)}"
        )
    return errors


def validate_module(plugin_dir: Path, plugin_definition_cls) -> list[str]:
    errors: list[str] = []
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.is_file():
        errors.append("plugin.py is missing")
        return errors
    module_name = f"_calvin_plugin_validate.{plugin_dir.name}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_py)
    if spec is None or spec.loader is None:
        errors.append(f"could not build import spec for {plugin_py}")
        return errors
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"plugin.py failed to import: {exc!r}")
        return errors
    register = getattr(module, "register_plugin_types", None)
    if not callable(register):
        errors.append("plugin.py does not define register_plugin_types()")
        return errors
    try:
        raw_definitions = register()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"register_plugin_types() raised: {exc!r}")
        return errors
    if not isinstance(raw_definitions, list) or not raw_definitions:
        errors.append("register_plugin_types() must return a non-empty list")
        return errors
    for index, raw in enumerate(raw_definitions):
        try:
            plugin_definition_cls.from_raw(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"definition[{index}] failed validation: {exc}")
    return errors


def validate_plugin(plugin_dir: Path, plugin_definition_cls) -> list[str]:
    errors = validate_manifest(plugin_dir)
    errors.extend(validate_module(plugin_dir, plugin_definition_cls))
    return errors


def discover_all_plugins() -> list[Path]:
    return sorted(p.parent for p in REPO_ROOT.glob("*/plugin.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plugins", nargs="*", help="Plugin directory names (relative to repo root)")
    parser.add_argument("--all", action="store_true", help="Validate every plugin in the repo")
    args = parser.parse_args()

    if args.all:
        plugin_dirs = discover_all_plugins()
    elif args.plugins:
        plugin_dirs = []
        for name in args.plugins:
            candidate = (REPO_ROOT / name).resolve()
            if not candidate.is_dir():
                sys.stderr.write(f"ERROR: not a directory: {candidate}\n")
                return 2
            plugin_dirs.append(candidate)
    else:
        parser.error("specify plugin names or --all")

    plugin_definition_cls = load_plugin_definition_class()

    failed = 0
    for plugin_dir in plugin_dirs:
        errors = validate_plugin(plugin_dir, plugin_definition_cls)
        if errors:
            failed += 1
            print(f"FAIL  {plugin_dir.name}")
            for err in errors:
                print(f"        - {err}")
        else:
            print(f"OK    {plugin_dir.name}")

    print()
    print(f"{len(plugin_dirs) - failed}/{len(plugin_dirs)} plugin(s) valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

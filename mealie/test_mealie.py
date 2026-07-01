"""Tests for the Mealie plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/mealie/test_mealie.py
"""

import importlib.util
import types
from datetime import datetime, timedelta
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
    spec = importlib.util.spec_from_file_location("mealie_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mealie_module = _load_plugin_module()
MealieServicePlugin = mealie_module.MealieServicePlugin


@pytest.fixture
async def plugin():
    """A configured plugin instance (no HTTP client yet)."""
    instance = MealieServicePlugin(plugin_id="mealie-test", name="Mealie", enabled=True)
    await instance.configure(
        {
            "mealie_url": "http://mealie.local:9000/",
            "api_token": " test-api-token ",
            "days_ahead": "7",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_mealie")
        module.MealieServicePlugin = MealieServicePlugin
        assert loader.register_module(module) == ["mealie"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(mealie_module, hook), hook

    def test_metadata(self):
        md = MealieServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "mealie"
        assert md.instance_identity == ["mealie_url"]
        assert md.display_schema["kind"] == "card-grid"
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"mealie_url", "api_token"}

    def test_is_service_plugin(self):
        assert issubclass(MealieServicePlugin, ServicePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.mealie_url == "http://mealie.local:9000"  # trailing slash trimmed
        assert plugin.api_token == "test-api-token"  # whitespace trimmed
        assert plugin.days_ahead == 7  # "7" converted by schema type

    async def test_validate_config(self):
        good = {"mealie_url": "http://mealie.local:9000", "api_token": "tok"}
        assert await MealieServicePlugin.validate_config(good) is True
        assert await MealieServicePlugin.validate_config({**good, "api_token": ""}) is False
        assert await MealieServicePlugin.validate_config({**good, "mealie_url": "ftp://x"}) is False
        assert await MealieServicePlugin.validate_config({**good, "days_ahead": 99}) is False

    def test_instance_identity_stable_per_server(self):
        config = {"mealie_url": "http://mealie.local:9000", "api_token": "a"}
        other = {"mealie_url": "http://other:9000", "api_token": "a"}
        assert MealieServicePlugin.instance_id_for(config) == MealieServicePlugin.instance_id_for(
            {**config, "api_token": "b"}
        )
        assert MealieServicePlugin.instance_id_for(config) != MealieServicePlugin.instance_id_for(
            other
        )

    async def test_initialize_requires_url_and_token(self):
        instance = MealieServicePlugin("mealie-x", "Mealie")
        await instance.configure({"mealie_url": "", "api_token": ""})
        with pytest.raises(ValueError):
            await instance.initialize()


class TestFetchShaping:
    """fetch() output binds to the card-grid display schema."""

    def test_groups_entries_into_day_cards(self):
        instance = MealieServicePlugin("mealie-x", "Mealie")
        instance.config = {"mealie_url": "http://m"}
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        shaped = instance._shape_for_display(
            {
                "items": [
                    {
                        "date": today.isoformat(),
                        "entryType": "dinner",
                        "recipe": {"name": "Pasta", "slug": "pasta"},
                    },
                    {
                        "date": today.isoformat(),
                        "entryType": "lunch",
                        "title": "Leftovers",
                    },
                    {
                        "date": tomorrow.isoformat(),
                        "entryType": "dinner",
                        "recipe": {"name": "Tacos", "slug": "tacos"},
                    },
                ]
            }
        )
        assert [d["title"] for d in shaped["days"]] == ["Today", "Tomorrow"]
        first = shaped["days"][0]["meals"]
        assert {m["name"] for m in first} == {"Pasta", "Leftovers"}
        pasta = next(m for m in first if m["name"] == "Pasta")
        assert pasta["url"] == "http://m/g/home/r/pasta"

    def test_error_passes_through(self):
        instance = MealieServicePlugin("mealie-x", "Mealie")
        shaped = instance._shape_for_display({"items": [], "error": "boom"})
        assert shaped["days"] == []
        assert shaped["error"] == "boom"

    async def test_fetch_uses_client(self, plugin, monkeypatch):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"items": []}
        client = AsyncMock()
        client.get.return_value = response
        plugin._client = client
        monkeypatch.setattr(plugin, "_reload_config_from_db", AsyncMock())
        shaped = await plugin.fetch()
        assert shaped["days"] == []
        assert client.get.await_count == 1


class TestConnectionTest:
    async def test_missing_config_fails_fast(self):
        result = await MealieServicePlugin.test_connection({})
        assert result["success"] is False

    async def test_connect_error_reported(self, monkeypatch):
        async def raise_connect(*args, **kwargs):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx.AsyncClient, "get", raise_connect)
        result = await MealieServicePlugin.test_connection(
            {"mealie_url": "http://mealie.local:9000", "api_token": "tok"}
        )
        assert result["success"] is False
        assert "connect" in result["message"].lower()

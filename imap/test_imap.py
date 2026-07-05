"""Tests for the IMAP plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/imap/test_imap.py
"""

import asyncio
import imaplib
import importlib.util
import types
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import BackendPlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("imap_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imap_module = _load_plugin_module()
ImapBackendPlugin = imap_module.ImapBackendPlugin


@pytest.fixture
async def plugin(tmp_path):
    """A configured plugin instance saving into a temp directory."""
    instance = ImapBackendPlugin(plugin_id="imap-test", name="Email (IMAP)", enabled=True)
    await instance.configure(
        {
            "email_address": " test@example.com ",
            "email_password": "test-password",
            "imap_server": "imap.gmail.com",
            "imap_port": "993",
            "check_interval": "300",
            "target_directory": str(tmp_path),
            "mark_as_read": "true",
        }
    )
    return instance


def _email_with_attachment(filename: str, payload: bytes = b"fake image data") -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Photos"
    message.set_content("see attachment")
    message.add_attachment(
        payload, maintype="image", subtype="png", filename=filename
    )
    return message


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_imap")
        module.ImapBackendPlugin = ImapBackendPlugin
        assert loader.register_module(module) == ["imap"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(imap_module, hook), hook

    def test_metadata(self):
        md = ImapBackendPlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "imap"
        assert md.supports_multiple_instances is True
        assert md.fixed_instance_id is None
        assert md.instance_identity == ["email_address", "imap_server"]
        assert md.display_schema is None  # backend plugin: no panel
        action_types = {action["type"] for action in md.ui_actions}
        assert {"save", "test", "fetch"} <= action_types
        required = {
            key
            for key, field in md.instance_config_schema.items()
            if (field.get("ui") or {}).get("validation", {}).get("required")
        }
        assert required == {"email_address", "email_password"}

    def test_is_backend_plugin(self):
        assert issubclass(ImapBackendPlugin, BackendPlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin, tmp_path):
        assert plugin.email_address == "test@example.com"  # whitespace trimmed
        assert plugin.email_password == "test-password"
        assert plugin.imap_server == "imap.gmail.com"
        assert plugin.imap_port == 993  # "993" converted by schema type
        assert plugin.check_interval == 300
        assert plugin.mark_as_read is True  # "true" converted by schema type
        assert plugin.target_directory == tmp_path.resolve()
        assert plugin.target_directory.exists()

    async def test_mark_as_read_string_false(self, plugin, tmp_path):
        await plugin.configure(
            {
                "email_address": "test@example.com",
                "email_password": "test-password",
                "target_directory": str(tmp_path),
                "mark_as_read": "false",
            }
        )
        assert plugin.mark_as_read is False

    async def test_target_directory_defaults_to_image_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("IMAGE_DIR", str(tmp_path / "images"))
        instance = ImapBackendPlugin("imap-x", "Email (IMAP)")
        assert instance.target_directory == (tmp_path / "images").resolve()

    async def test_validate_config(self):
        good = {"email_address": "test@example.com", "email_password": "secret"}
        assert await ImapBackendPlugin.validate_config(good) is True
        assert await ImapBackendPlugin.validate_config({**good, "email_address": ""}) is False
        assert await ImapBackendPlugin.validate_config({**good, "email_password": " "}) is False
        assert await ImapBackendPlugin.validate_config({**good, "imap_port": 0}) is False
        assert await ImapBackendPlugin.validate_config({**good, "imap_port": 65536}) is False
        assert await ImapBackendPlugin.validate_config({**good, "check_interval": 30}) is False
        assert await ImapBackendPlugin.validate_config({**good, "check_interval": 5000}) is False
        assert await ImapBackendPlugin.validate_config({**good, "imap_port": 143}) is True

    def test_instance_identity_stable_per_account_and_server(self):
        config = {"email_address": "a@example.com", "imap_server": "imap.gmail.com"}
        assert ImapBackendPlugin.instance_id_for(config) == ImapBackendPlugin.instance_id_for(
            {**config, "email_password": "different"}
        )
        assert ImapBackendPlugin.instance_id_for(config) != ImapBackendPlugin.instance_id_for(
            {**config, "email_address": "b@example.com"}
        )
        assert ImapBackendPlugin.instance_id_for(config) != ImapBackendPlugin.instance_id_for(
            {**config, "imap_server": "imap.other.com"}
        )


class TestScheduling:
    """Scheduled-task behavior is preserved exactly."""

    async def test_schedule_config_uses_check_interval(self, plugin, tmp_path):
        await plugin.configure(
            {
                "email_address": "test@example.com",
                "email_password": "test-password",
                "target_directory": str(tmp_path),
                "check_interval": 600,
            }
        )
        schedule = await plugin.get_schedule_config()
        assert schedule == {"interval": 600, "enabled": True, "max_concurrent": 1}

    async def test_schedule_config_none_when_disabled(self, plugin):
        plugin.disable()
        assert await plugin.get_schedule_config() is None

    async def test_run_scheduled_task_reports_downloads(self, plugin, monkeypatch):
        monkeypatch.setattr(
            plugin,
            "_check_emails_sync",
            lambda: {"success": True, "message": "ok", "images_downloaded": 2},
        )
        result = await plugin.run_scheduled_task()
        assert result["success"] is True
        assert result["data"]["images_downloaded"] == 2
        assert "2 image(s)" in result["message"]

    async def test_run_scheduled_task_reports_failure(self, plugin, monkeypatch):
        monkeypatch.setattr(
            plugin,
            "_check_emails_sync",
            lambda: {"success": False, "message": "boom", "images_downloaded": 0},
        )
        result = await plugin.run_scheduled_task()
        assert result["success"] is False
        assert result["message"] == "boom"

    async def test_configure_reregisters_schedule_on_interval_change(
        self, plugin, tmp_path, monkeypatch
    ):
        import app.services.backend_scheduler as scheduler_module

        scheduler = MagicMock()
        scheduler.scheduler.running = True
        scheduler.unregister_plugin_tasks = AsyncMock()
        scheduler.register_plugin_tasks = AsyncMock()
        monkeypatch.setattr(scheduler_module, "backend_plugin_scheduler", scheduler)

        plugin.start()
        await plugin.configure(
            {
                "email_address": "test@example.com",
                "email_password": "test-password",
                "target_directory": str(tmp_path),
                "check_interval": 900,
            }
        )
        scheduler.unregister_plugin_tasks.assert_awaited_once_with("imap-test")
        scheduler.register_plugin_tasks.assert_awaited_once_with(plugin)


class TestCheckMail:
    """Email checking against a mocked IMAP client."""

    def _mail_mock(self, message: EmailMessage):
        mail = MagicMock()
        mail.search.return_value = ("OK", [b"1"])
        mail.fetch.return_value = ("OK", [(b"1 (RFC822)", message.as_bytes())])
        return mail

    async def test_check_downloads_attachment_and_marks_read(
        self, plugin, tmp_path, monkeypatch
    ):
        mail = self._mail_mock(_email_with_attachment("photo.png"))
        monkeypatch.setattr(imaplib, "IMAP4_SSL", MagicMock(return_value=mail))

        result = plugin._check_emails_sync()

        assert result["success"] is True
        assert result["images_downloaded"] == 1
        assert (tmp_path / "photo.png").read_bytes() == b"fake image data"
        mail.login.assert_called_once_with("test@example.com", "test-password")
        mail.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")
        mail.logout.assert_called_once()

    async def test_check_skips_unsupported_attachment(self, plugin, tmp_path, monkeypatch):
        mail = self._mail_mock(_email_with_attachment("notes.txt"))
        monkeypatch.setattr(imaplib, "IMAP4_SSL", MagicMock(return_value=mail))

        result = plugin._check_emails_sync()

        assert result["success"] is True
        assert result["images_downloaded"] == 0
        assert not (tmp_path / "notes.txt").exists()
        mail.store.assert_not_called()

    async def test_check_reports_auth_failure(self, plugin, monkeypatch):
        monkeypatch.setattr(
            imaplib,
            "IMAP4_SSL",
            MagicMock(side_effect=imaplib.IMAP4.error("Authentication failed")),
        )
        result = plugin._check_emails_sync()
        assert result["success"] is False
        assert "authentication failed" in result["message"].lower()

    async def test_avoids_overwriting_existing_files(self, plugin, tmp_path):
        (tmp_path / "photo.png").write_bytes(b"existing")
        downloaded = plugin._extract_images(_email_with_attachment("photo.png"))
        assert downloaded == 1
        assert (tmp_path / "photo.png").read_bytes() == b"existing"
        assert (tmp_path / "photo_1.png").read_bytes() == b"fake image data"


class TestFetch:
    """Instance-level fetch() replaces the retired class-level fetch verb."""

    async def test_fetch_runs_check_and_shapes_result(self, plugin, monkeypatch):
        monkeypatch.setattr(
            plugin,
            "run_scheduled_task",
            AsyncMock(
                return_value={
                    "success": True,
                    "message": "Downloaded 3 image(s) from email",
                    "data": {"images_downloaded": 3},
                }
            ),
        )
        result = await plugin.fetch()
        assert result == {
            "success": True,
            "message": "Downloaded 3 image(s) from email",
            "images_downloaded": 3,
        }


class TestConnectionTest:
    async def test_missing_config_fails_fast(self):
        result = await ImapBackendPlugin.test_connection({})
        assert result["success"] is False
        assert "required" in result["message"].lower()

    async def test_successful_connection(self, monkeypatch):
        mail = MagicMock()
        ssl_factory = MagicMock(return_value=mail)
        monkeypatch.setattr(imaplib, "IMAP4_SSL", ssl_factory)
        result = await ImapBackendPlugin.test_connection(
            {"email_address": "test@example.com", "email_password": "secret"}
        )
        assert result["success"] is True
        # A socket timeout must be applied so an unreachable host can't hang the
        # event loop (calvin-8kn).
        ssl_factory.assert_called_once_with("imap.gmail.com", 993, timeout=10)
        mail.login.assert_called_once_with("test@example.com", "secret")

    async def test_connection_runs_off_the_event_loop(self, monkeypatch):
        """The blocking imaplib work must be offloaded via asyncio.to_thread (calvin-8kn)."""
        monkeypatch.setattr(imaplib, "IMAP4_SSL", MagicMock(return_value=MagicMock()))
        called = {}
        real_to_thread = asyncio.to_thread

        async def spy(func, *args, **kwargs):
            called["used"] = True
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy)
        result = await ImapBackendPlugin.test_connection(
            {"email_address": "test@example.com", "email_password": "secret"}
        )
        assert result["success"] is True
        assert called.get("used") is True

    async def test_auth_failure_reported(self, monkeypatch):
        monkeypatch.setattr(
            imaplib,
            "IMAP4_SSL",
            MagicMock(side_effect=imaplib.IMAP4.error("invalid credentials")),
        )
        result = await ImapBackendPlugin.test_connection(
            {"email_address": "test@example.com", "email_password": "wrong"}
        )
        assert result["success"] is False
        assert "authentication failed" in result["message"].lower()

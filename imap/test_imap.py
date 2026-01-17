"""Tests for IMAP plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/imap/test_imap.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile
import os

import pytest

# Note: These tests assume the plugin is installed and the backend imports are available
# In a real scenario, you'd run these tests in the calvin backend context
try:
    from app.plugins.base import PluginType
    from app.plugins.hooks import hookimpl
    from app.plugins.protocols import BackendPlugin
    from app.plugins.utils.config import extract_config_value, to_int, to_str, to_bool
    from app.plugins.utils.instance_manager import (
        InstanceManagerConfig,
        handle_plugin_config_update_generic,
    )
    
    # Import the plugin
    import sys
    from pathlib import Path
    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("imap_plugin", plugin_path)
        if spec and spec.loader:
            imap_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(imap_module)
            ImapBackendPlugin = imap_module.ImapBackendPlugin
        else:
            pytest.skip("Could not load imap plugin module")
    else:
        pytest.skip("imap plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def imap_plugin():
    """Create an ImapBackendPlugin instance."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Set IMAGE_DIR env var for test
        os.environ["IMAGE_DIR"] = tmp_dir
        
        plugin = ImapBackendPlugin(
            plugin_id="imap-instance",
            name="Email (IMAP)",
            email_address="test@example.com",
            email_password="test-password",
            imap_server="imap.gmail.com",
            imap_port=993,
            target_directory=None,
            check_interval=300,
            mark_as_read=True,
            enabled=True,
        )
        yield plugin
        
        # Cleanup
        if "IMAGE_DIR" in os.environ:
            del os.environ["IMAGE_DIR"]


class TestImapBackendPlugin:
    """Tests for ImapBackendPlugin class."""

    def test_get_plugin_metadata(self):
        """Test plugin metadata."""
        metadata = ImapBackendPlugin.get_plugin_metadata()
        assert metadata["type_id"] == "imap"
        assert metadata["plugin_type"] == PluginType.BACKEND
        assert metadata["name"] == "Email (IMAP)"
        assert metadata["supports_multiple_instances"] is True
        assert "common_config_schema" in metadata
        assert "instance_config_schema" in metadata
        assert "email_address" in metadata["instance_config_schema"]
        assert "email_password" in metadata["instance_config_schema"]
        assert "imap_server" in metadata["instance_config_schema"]
        assert "imap_port" in metadata["instance_config_schema"]

    def test_init(self, imap_plugin):
        """Test plugin initialization."""
        assert imap_plugin.plugin_id == "imap-instance"
        assert imap_plugin.name == "Email (IMAP)"
        assert imap_plugin.email_address == "test@example.com"
        assert imap_plugin.email_password == "test-password"
        assert imap_plugin.imap_server == "imap.gmail.com"
        assert imap_plugin.imap_port == 993
        assert imap_plugin.check_interval == 300
        assert imap_plugin.mark_as_read is True
        assert imap_plugin.enabled is True
        assert imap_plugin.target_directory.exists()

    def test_init_with_custom_target_directory(self):
        """Test plugin initialization with custom target directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = ImapBackendPlugin(
                plugin_id="imap-instance",
                name="Email (IMAP)",
                email_address="test@example.com",
                email_password="test-password",
                target_directory=tmp_dir,
            )
            assert plugin.target_directory == Path(tmp_dir).resolve()
            assert plugin.target_directory.exists()

    @pytest.mark.asyncio
    async def test_initialize(self, imap_plugin):
        """Test plugin initialization."""
        await imap_plugin.initialize()
        # Should not raise any errors

    @pytest.mark.asyncio
    async def test_cleanup(self, imap_plugin):
        """Test plugin cleanup."""
        await imap_plugin.cleanup()
        # Should not raise any errors

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, imap_plugin):
        """Test config validation with valid config."""
        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
        }) is True

        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
            "imap_server": "imap.outlook.com",
            "imap_port": 143,
            "check_interval": 600,
        }) is True

    @pytest.mark.asyncio
    async def test_validate_config_missing_email(self, imap_plugin):
        """Test config validation with missing email address."""
        assert await imap_plugin.validate_config({"email_password": "test-password"}) is False
        assert await imap_plugin.validate_config({"email_address": "", "email_password": "test-password"}) is False

    @pytest.mark.asyncio
    async def test_validate_config_missing_password(self, imap_plugin):
        """Test config validation with missing password."""
        assert await imap_plugin.validate_config({"email_address": "test@example.com"}) is False
        assert await imap_plugin.validate_config({"email_address": "test@example.com", "email_password": ""}) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_port(self, imap_plugin):
        """Test config validation with invalid port."""
        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
            "imap_port": 0,
        }) is False

        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
            "imap_port": 65536,
        }) is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_check_interval(self, imap_plugin):
        """Test config validation with invalid check interval."""
        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
            "check_interval": 30,  # Too small
        }) is False

        assert await imap_plugin.validate_config({
            "email_address": "test@example.com",
            "email_password": "test-password",
            "check_interval": 5000,  # Too large
        }) is False

    @pytest.mark.asyncio
    async def test_configure(self, imap_plugin):
        """Test plugin configuration."""
        with patch.object(imap_plugin, "is_running", return_value=False):
            await imap_plugin.configure({
                "email_address": "new@example.com",
                "email_password": "new-password",
                "imap_server": "imap.outlook.com",
                "imap_port": 143,
                "check_interval": 600,
                "mark_as_read": False,
            })

            assert imap_plugin.email_address == "new@example.com"
            assert imap_plugin.email_password == "new-password"
            assert imap_plugin.imap_server == "imap.outlook.com"
            assert imap_plugin.imap_port == 143
            assert imap_plugin.check_interval == 600
            assert imap_plugin.mark_as_read is False

    @pytest.mark.asyncio
    async def test_configure_target_directory(self, imap_plugin):
        """Test configuring with custom target directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(imap_plugin, "is_running", return_value=False):
                await imap_plugin.configure({
                    "email_address": "test@example.com",
                    "email_password": "test-password",
                    "target_directory": tmp_dir,
                })

                assert imap_plugin.target_directory == Path(tmp_dir).resolve()
                assert imap_plugin.target_directory.exists()

    @pytest.mark.asyncio
    async def test_configure_mark_as_read_string(self, imap_plugin):
        """Test configuring mark_as_read with string value."""
        with patch.object(imap_plugin, "is_running", return_value=False):
            await imap_plugin.configure({
                "email_address": "test@example.com",
                "email_password": "test-password",
                "mark_as_read": "false",
            })

            assert imap_plugin.mark_as_read is False

            await imap_plugin.configure({
                "mark_as_read": "true",
            })

            assert imap_plugin.mark_as_read is True

    @pytest.mark.asyncio
    async def test_configure_partial_update(self, imap_plugin):
        """Test configuring with partial config."""
        original_email = imap_plugin.email_address

        with patch.object(imap_plugin, "is_running", return_value=False):
            await imap_plugin.configure({"check_interval": 600})

            # Email should remain unchanged
            assert imap_plugin.email_address == original_email
            assert imap_plugin.check_interval == 600


@pytest.mark.asyncio
class TestImapPluginHooks:
    """Tests for IMAP plugin hooks."""

    async def test_create_plugin_instance(self):
        """Test create_plugin_instance hook."""
        # This would need to be tested in the actual backend context
        # with proper plugin loading
        pass

    async def test_handle_plugin_config_update(self):
        """Test handle_plugin_config_update hook.
        
        Note: This test is skipped when run from the plugin directory because it requires
        the `test_db` fixture which is only available in the backend test suite.
        
        To test handle_plugin_config_update hooks, run the backend test suite from the
        backend directory:
            cd backend
            pytest tests/unit/test_plugin_hooks.py
        """
        pytest.skip("Requires backend test fixtures (test_db). "
                   "Run from backend directory: "
                   "cd backend && pytest tests/unit/test_plugin_hooks.py")

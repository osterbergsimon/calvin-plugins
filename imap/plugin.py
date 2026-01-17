"""IMAP email backend plugin - downloads images from email attachments."""

import asyncio
import email
import hashlib
import imaplib
import os
import time
from email.header import decode_header
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import BackendPlugin
from app.plugins.utils.config import extract_config_value, to_int, to_str, to_bool
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)

# Loguru automatically includes module/function info in logs


class ImapBackendPlugin(BackendPlugin):
    """IMAP email backend plugin for downloading images from email attachments.

    This plugin downloads images from email attachments to the local images directory,
    where they can be served by the LocalImagePlugin. It does not implement image
    serving/viewing functionality itself.
    """

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "imap",
            "plugin_type": PluginType.BACKEND,
            "name": "Email (IMAP)",
            "description": "Download images from email attachments. Works with Gmail, Outlook, and any IMAP provider. Share photos from Android using Share → Email.",  # noqa: E501
            "version": "1.0.0",
            "supports_multiple_instances": True,  # Multi-instance plugin
            "common_config_schema": {},
            "instance_config_schema": {
                "email_address": {
                    "type": "string",
                    "description": "Email address to check for images",
                    "default": "",
                    "ui": {
                        "component": "input",
                        "placeholder": "your.email@example.com",
                        "validation": {
                            "required": True,
                            "type": "email",
                        },
                    },
                },
                "email_password": {
                    "type": "password",
                    "description": "Email password or app-specific password (for Gmail, use App Password)",  # noqa: E501
                    "default": "",
                    "ui": {
                        "component": "password",
                        "placeholder": "Enter password or App Password",
                        "help_text": "For Gmail, use an App Password instead of your regular password",  # noqa: E501
                        "validation": {
                            "required": True,
                        },
                    },
                },
                "imap_server": {
                    "type": "string",
                    "description": "IMAP server address (e.g., imap.gmail.com, imap-mail.outlook.com)",  # noqa: E501
                    "default": "imap.gmail.com",
                    "ui": {
                        "component": "input",
                        "placeholder": "imap.gmail.com",
                    },
                },
                "imap_port": {
                    "type": "string",
                    "description": "IMAP server port (usually 993 for SSL)",
                    "default": "993",
                    "ui": {
                        "component": "number",
                        "min": 1,
                        "max": 65535,
                        "placeholder": "993",
                    },
                },
                "check_interval": {
                    "type": "string",
                    "description": "How often to check for new emails (seconds, default: 300 = 5 minutes)",  # noqa: E501
                    "default": "300",
                    "ui": {
                        "component": "number",
                        "min": 60,
                        "max": 3600,
                        "placeholder": "300",
                        "help_text": "How often to check for new emails (60-3600 seconds)",
                    },
                },
                "target_directory": {
                    "type": "string",
                    "description": "Directory to save downloaded images (defaults to local images directory)",  # noqa: E501
                    "default": "",
                    "ui": {
                        "component": "input",
                        "placeholder": "./data/images (default)",
                        "help_text": "Leave empty to use the local images directory",
                    },
                },
                "mark_as_read": {
                    "type": "string",
                    "description": "Mark processed emails as read (true/false, default: true)",
                    "default": "true",
                    "ui": {
                        "component": "select",
                        "options": [
                            {"value": "true", "label": "Yes"},
                            {"value": "false", "label": "No"},
                        ],
                    },
                },
            },
            "ui_actions": [
                {
                    "id": "save",
                    "type": "save",
                    "label": "Save Settings",
                    "style": "primary",
                },
                {
                    "id": "test",
                    "type": "test",
                    "label": "Test Connection",
                    "style": "secondary",
                },
                {
                    "id": "fetch",
                    "type": "fetch",
                    "label": "Fetch Now",
                    "style": "secondary",
                },
            ],
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        email_address: str,
        email_password: str,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993,
        target_directory: Path | str | None = None,
        check_interval: int = 300,  # Check every 5 minutes
        mark_as_read: bool = True,
        enabled: bool = True,
    ):
        """
        Initialize IMAP backend plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            email_address: Email address to check
            email_password: Email password or app-specific password
            imap_server: IMAP server address (default: imap.gmail.com)
            imap_port: IMAP server port (default: 993 for SSL)
            target_directory: Directory to save downloaded images (defaults to local images dir)
            check_interval: How often to check for new emails (seconds, default: 300)
            mark_as_read: Whether to mark processed emails as read (default: True)
            enabled: Whether the plugin is enabled
        """
        super().__init__(plugin_id, name, enabled)
        self.email_address = email_address
        self.email_password = email_password
        self.imap_server = imap_server
        self.imap_port = imap_port

        # Determine target directory (defaults to local images directory)
        if target_directory:
            self.target_directory = Path(target_directory).resolve()
        else:
            # Use same directory as local images plugin
            image_dir_str = os.getenv("IMAGE_DIR")
            if image_dir_str:
                self.target_directory = Path(image_dir_str).resolve()
            else:
                self.target_directory = Path("./data/images").resolve()

        self.target_directory.mkdir(parents=True, exist_ok=True)
        self.check_interval = check_interval
        self.mark_as_read = mark_as_read
        self.supported_formats = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        self._processed_emails: set[str] = set()  # Track processed email UIDs

    async def initialize(self) -> None:
        """Initialize the plugin."""
        # No need to scan - LocalImagePlugin will handle that
        pass

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        # No cleanup needed - no background tasks running
        pass

    async def get_schedule_config(self) -> dict[str, Any] | None:
        """Return schedule configuration for scheduled email checking."""
        if not self.enabled:
            return None

        return {
            "interval": self.check_interval,
            "enabled": True,
            "max_concurrent": 1,
        }

    async def run_scheduled_task(self) -> dict[str, Any]:
        """Execute scheduled task - check for new emails and download images."""
        try:
            # Run IMAP operations in thread pool (imaplib is synchronous)
            result = await asyncio.to_thread(self._check_emails_sync)

            if result["success"]:
                images_downloaded = result.get("images_downloaded", 0)
                if images_downloaded > 0:
                    return {
                        "success": True,
                        "message": f"Downloaded {images_downloaded} image(s) from email",
                        "data": {"images_downloaded": images_downloaded},
                    }
                else:
                    return {
                        "success": True,
                        "message": "No new emails with image attachments found",
                        "data": {"images_downloaded": 0},
                    }
            else:
                return {
                    "success": False,
                    "message": result.get("message", "Error checking emails"),
                    "data": {"images_downloaded": 0},
                }
        except Exception as e:
            logger.exception("Error in scheduled IMAP task")
            return {
                "success": False,
                "message": f"Error checking emails: {str(e)}",
                "data": {"images_downloaded": 0},
            }

    def _check_emails_sync(self) -> dict[str, Any]:
        """Synchronous email checking (runs in thread pool).

        Returns:
            Dictionary with success status, message, and images_downloaded count
        """
        images_downloaded = 0
        try:
            # Connect to IMAP server
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_address, self.email_password)
            mail.select("INBOX")

            # Search for unread emails
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                mail.close()
                mail.logout()
                return {
                    "success": False,
                    "message": "Failed to search for emails",
                    "images_downloaded": 0,
                }

            email_ids = messages[0].split()
            if not email_ids:
                mail.close()
                mail.logout()
                return {
                    "success": True,
                    "message": "No unread emails found",
                    "images_downloaded": 0,
                }

            # Process each email
            for email_id in email_ids:
                try:
                    # Fetch email
                    status, msg_data = mail.fetch(email_id, "(RFC822)")
                    if status != "OK":
                        continue

                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)

                    # Check if we've already processed this email
                    email_uid = email_id.decode()
                    if email_uid in self._processed_emails:
                        continue

                    # Extract image attachments
                    email_images_downloaded = self._extract_images(email_message)

                    if email_images_downloaded > 0:
                        # Mark email as processed
                        self._processed_emails.add(email_uid)
                        if self.mark_as_read:
                            mail.store(email_id, "+FLAGS", "\\Seen")
                        images_downloaded += email_images_downloaded

                except Exception:
                    logger.exception("Error processing email {}", email_id)
                    continue

            mail.close()
            mail.logout()
            return {
                "success": True,
                "message": f"Processed {len(email_ids)} email(s), downloaded {images_downloaded} image(s)",
                "images_downloaded": images_downloaded,
            }

        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            if "authentication failed" in error_msg.lower() or "invalid credentials" in error_msg.lower():
                return {
                    "success": False,
                    "message": "Authentication failed. Please check your email address and password.",
                    "images_downloaded": 0,
                }
            elif "connection refused" in error_msg.lower() or "timeout" in error_msg.lower():
                return {
                    "success": False,
                    "message": f"Could not connect to {self.imap_server}. Please check the server address and port.",
                    "images_downloaded": 0,
                }
            else:
                return {
                    "success": False,
                    "message": f"IMAP error: {error_msg}",
                    "images_downloaded": 0,
                }
        except Exception as e:
            logger.exception("Error connecting to IMAP server")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "images_downloaded": 0,
            }

    def _extract_images(self, email_message: email.message.Message) -> int:
        """Extract image attachments from email message.

        Returns:
            Number of images downloaded
        """
        images_downloaded = 0

        for part in email_message.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            content_type = part.get_content_type()

            # Check if this is an image attachment
            if "attachment" in content_disposition or (
                content_type.startswith("image/") and part.get_filename()
            ):
                filename = part.get_filename()
                if not filename:
                    continue

                # Decode filename if needed
                decoded_filename = self._decode_filename(filename)
                if not decoded_filename:
                    continue

                # Check if it's a supported image format
                file_ext = Path(decoded_filename).suffix.lower()
                if file_ext not in self.supported_formats:
                    continue

                try:
                    # Download image
                    image_data = part.get_payload(decode=True)
                    if not image_data:
                        continue

                    # Save image to target directory
                    image_path = self.target_directory / decoded_filename
                    # Avoid overwriting existing files
                    counter = 1
                    while image_path.exists():
                        stem = Path(decoded_filename).stem
                        image_path = self.target_directory / f"{stem}_{counter}{file_ext}"
                        counter += 1

                    with open(image_path, "wb") as f:
                        f.write(image_data)

                    images_downloaded += 1
                    logger.info("Downloaded image from email: {}", image_path)

                except Exception:
                    logger.exception("Error downloading image {}", decoded_filename)
                    continue

        return images_downloaded

    def _decode_filename(self, filename: str) -> str | None:
        """Decode email filename."""
        try:
            decoded_parts = decode_header(filename)
            decoded_string = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        decoded_string += part.decode(encoding)
                    else:
                        decoded_string += part.decode("utf-8", errors="ignore")
                else:
                    decoded_string += part
            return decoded_string
        except Exception:
            return filename

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate plugin configuration."""
        # Check required fields
        email_address = extract_config_value(config, "email_address", default="", converter=to_str)
        email_password = extract_config_value(config, "email_password", default="", converter=to_str)

        if not email_address or not email_address.strip():
            return False
        if not email_password or not email_password.strip():
            return False

        # Validate IMAP port if provided
        if "imap_port" in config:
            imap_port = extract_config_value(config, "imap_port", default=993, converter=to_int)
            if imap_port < 1 or imap_port > 65535:
                return False

        # Validate check_interval if provided
        if "check_interval" in config:
            check_interval = extract_config_value(config, "check_interval", default=300, converter=to_int)
            if check_interval < 60 or check_interval > 3600:
                return False

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """Configure the plugin with new settings."""
        from app.services.backend_scheduler import backend_plugin_scheduler

        await super().configure(config)

        old_check_interval = self.check_interval

        if "email_address" in config:
            self.email_address = extract_config_value(config, "email_address", default="", converter=to_str)

        if "email_password" in config:
            self.email_password = extract_config_value(config, "email_password", default="", converter=to_str)

        if "imap_server" in config:
            self.imap_server = extract_config_value(config, "imap_server", default="imap.gmail.com", converter=to_str)

        if "imap_port" in config:
            self.imap_port = extract_config_value(config, "imap_port", default=993, converter=to_int)

        if "target_directory" in config:
            target_dir = extract_config_value(config, "target_directory", default="", converter=to_str)
            if target_dir and target_dir.strip():
                self.target_directory = Path(target_dir).resolve()
                self.target_directory.mkdir(parents=True, exist_ok=True)

        if "check_interval" in config:
            self.check_interval = extract_config_value(config, "check_interval", default=300, converter=to_int)

        if "mark_as_read" in config:
            mark_as_read = extract_config_value(config, "mark_as_read", default=True, converter=to_bool)
            # Handle string values like "true"/"false" that might come from UI
            if isinstance(mark_as_read, str):
                self.mark_as_read = mark_as_read.lower() in ("true", "1", "yes")
            else:
                self.mark_as_read = bool(mark_as_read)

        # Re-register scheduled tasks if interval changed and plugin is running
        if (
            self.is_running()
            and self.enabled
            and old_check_interval != self.check_interval
            and backend_plugin_scheduler.scheduler.running
        ):
            try:
                # Unregister old tasks
                await backend_plugin_scheduler.unregister_plugin_tasks(self.plugin_id)
                # Register new tasks with updated interval
                await backend_plugin_scheduler.register_plugin_tasks(self)
            except Exception as e:
                logger.warning(
                    f"Error re-registering scheduled tasks for IMAP plugin {self.plugin_id} after config change: {e}",
                    exc_info=True,
                )


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register ImapBackendPlugin type."""
    return [ImapBackendPlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> ImapBackendPlugin | None:
    """Create an ImapBackendPlugin instance."""
    if type_id != "imap":
        return None

    enabled = config.get("enabled", False)  # Default to disabled

    # Extract config values using utility functions
    email_address = extract_config_value(config, "email_address", default="", converter=to_str)
    email_password = extract_config_value(config, "email_password", default="", converter=to_str)
    imap_server = extract_config_value(config, "imap_server", default="imap.gmail.com", converter=to_str)
    imap_port = extract_config_value(config, "imap_port", default=993, converter=to_int)
    check_interval = extract_config_value(config, "check_interval", default=300, converter=to_int)
    
    # Handle target_directory (Path or None)
    target_directory = extract_config_value(config, "target_directory", default="", converter=to_str)
    target_directory = Path(target_directory) if target_directory and target_directory.strip() else None
    
    # Handle mark_as_read (bool, may come as string)
    mark_as_read = extract_config_value(config, "mark_as_read", default=True, converter=to_bool)
    if isinstance(mark_as_read, str):
        mark_as_read = mark_as_read.lower() in ("true", "1", "yes")
    else:
        mark_as_read = bool(mark_as_read)

    return ImapBackendPlugin(
        plugin_id=plugin_id,
        name=name,
        email_address=email_address,
        email_password=email_password,
        imap_server=imap_server,
        imap_port=imap_port,
        target_directory=target_directory,
        check_interval=check_interval,
        mark_as_read=mark_as_read,
        enabled=enabled,
    )


@hookimpl
async def test_plugin_connection(
    type_id: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Test IMAP connection."""
    if type_id != "imap":
        return None

    import imaplib

    email_address = config.get("email_address", "")
    email_password = config.get("email_password", "")
    imap_server = config.get("imap_server", "imap.gmail.com")
    imap_port = int(config.get("imap_port", 993))

    if not email_address or not email_password:
        return {
            "success": False,
            "message": "Email address and password are required",
        }

    try:
        # Test connection
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_address, email_password)
        mail.select("INBOX")
        mail.close()
        mail.logout()

        return {
            "success": True,
            "message": f"Successfully connected to {imap_server}",
        }
    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        if (
            "authentication failed" in error_msg.lower()
            or "invalid credentials" in error_msg.lower()
        ):
            return {
                "success": False,
                "message": "Authentication failed. Please check your email address and password.",
            }
        elif "connection refused" in error_msg.lower() or "timeout" in error_msg.lower():
            return {
                "success": False,
                "message": f"Could not connect to {imap_server}. Please check the server address and port.",  # noqa: E501
            }
        else:
            return {
                "success": False,
                "message": f"Connection error: {error_msg}",
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
        }


@hookimpl
async def fetch_plugin_data(
    type_id: str,
    instance_id: str | None = None,
) -> dict[str, Any] | None:
    """Manually trigger IMAP email check."""
    if type_id != "imap":
        return None

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.db_models import PluginDB
    from app.plugins.base import PluginType
    from app.plugins.manager import plugin_manager
    from app.plugins.protocols import BackendPlugin

    # Find IMAP plugin instance
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PluginDB).where(PluginDB.type_id == "imap"))
        imap_plugins_db = result.scalars().all()

    if not imap_plugins_db:
        return {
            "success": False,
            "message": "IMAP plugin instance not found. Please configure and enable the IMAP plugin first.",  # noqa: E501
            "images_downloaded": 0,
        }

    # Try to find the plugin instance from plugin manager
    imap_plugin = None
    for db_plugin in imap_plugins_db:
        plugin = plugin_manager.get_plugin(db_plugin.id)
        if plugin and isinstance(plugin, BackendPlugin) and plugin.__class__.__name__ == "ImapBackendPlugin":
            imap_plugin = plugin
            break

    # If not found by ID, try to find by class name
    if not imap_plugin:
        plugins = plugin_manager.get_plugins(PluginType.BACKEND, enabled_only=False)
        for plugin in plugins:
            if plugin.__class__.__name__ == "ImapBackendPlugin":
                imap_plugin = plugin
                break

    if not imap_plugin:
        return {
            "success": False,
            "message": "IMAP plugin instance found in database but not loaded. Please restart the application.",  # noqa: E501
            "images_downloaded": 0,
        }

    # Run the scheduled task manually
    result = await imap_plugin.run_scheduled_task()
    return {
        "success": result.get("success", False),
        "message": result.get("message", ""),
        "images_downloaded": result.get("data", {}).get("images_downloaded", 0),
    }


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle IMAP plugin configuration update and instance management."""
    if type_id != "imap":
        return None

    import logging

    logger = logging.getLogger(__name__)

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        email_address = extract_config_value(c, "email_address", default="", converter=to_str)
        email_password = extract_config_value(c, "email_password", default="", converter=to_str)
        imap_server = extract_config_value(c, "imap_server", default="imap.gmail.com", converter=to_str)
        imap_port = extract_config_value(c, "imap_port", default=993, converter=to_int)
        check_interval = extract_config_value(c, "check_interval", default=300, converter=to_int)
        target_directory = extract_config_value(c, "target_directory", default="", converter=to_str)
        
        # Handle mark_as_read (may come as string "true"/"false")
        mark_as_read = extract_config_value(c, "mark_as_read", default=True, converter=to_bool)
        if isinstance(mark_as_read, str):
            mark_as_read = mark_as_read.lower() in ("true", "1", "yes")
        else:
            mark_as_read = bool(mark_as_read)

        return {
            "email_address": email_address.strip() if email_address else "",
            "email_password": email_password.strip() if email_password else "",
            "imap_server": imap_server.strip() if imap_server else "imap.gmail.com",
            "imap_port": imap_port,
            "check_interval": check_interval,
            "target_directory": target_directory.strip() if target_directory else "",
            "mark_as_read": mark_as_read,
        }

    def validate_config(c: dict[str, Any]) -> bool:
        """Validate config before creating/updating instance."""
        # Check required fields
        email_address = c.get("email_address", "")
        email_password = c.get("email_password", "")

        if not email_address or not email_address.strip():
            logger.info("[IMAP] Skipping instance creation - missing email address")
            return False
        if not email_password or not email_password.strip():
            logger.info("[IMAP] Skipping instance creation - missing email password")
            return False

        # Validate IMAP port if provided
        imap_port = c.get("imap_port", 993)
        if imap_port < 1 or imap_port > 65535:
            logger.info("[IMAP] Skipping instance creation - invalid IMAP port")
            return False

        # Validate check_interval if provided
        check_interval = c.get("check_interval", 300)
        if check_interval < 60 or check_interval > 3600:
            logger.info("[IMAP] Skipping instance creation - invalid check interval")
            return False

        return True

    def generate_instance_id(c: dict[str, Any], t_id: str) -> str:
        """Generate instance ID from config values."""
        # Generate unique instance ID based on email address and server
        email_address = c.get("email_address", "")
        imap_server = c.get("imap_server", "imap.gmail.com")
        
        # Create a hash from email and server to generate unique ID
        config_str = f"{email_address}_{imap_server}"
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
        return f"{t_id}-{config_hash}"

    def prepare_instance_config(c: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        """Prepare final config for instance creation."""
        instance_config = c.copy()
        
        # Use instance name from metadata or generate default
        email_address = c.get("email_address", "")
        if not metadata.get("instance_name"):
            instance_config["_instance_name"] = f"IMAP Email ({email_address})"
        else:
            instance_config["_instance_name"] = metadata["instance_name"]
        
        return instance_config

    manager_config = InstanceManagerConfig(
        type_id="imap",
        single_instance=False,  # Multi-instance plugin
        validate_config=validate_config,
        generate_instance_id=generate_instance_id,
        normalize_config=normalize_config,
        prepare_instance_config=prepare_instance_config,
        default_instance_name="IMAP Email",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )

"""IMAP email backend plugin - downloads images from email attachments."""

import asyncio
import email
import imaplib
import os
from email.header import decode_header
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import BackendPlugin

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
        required_fields = ["email_address", "email_password"]
        for field in required_fields:
            if field not in config or not config[field]:
                return False
        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """Configure the plugin with new settings."""
        from app.services.backend_scheduler import backend_plugin_scheduler

        await super().configure(config)

        old_check_interval = self.check_interval

        # Handle schema objects (extract actual values)
        if "email_address" in config:
            email_address_value = config["email_address"]
            if isinstance(email_address_value, dict):
                email_address_value = (
                    email_address_value.get("value")
                    or email_address_value.get("default")
                    or ""
                )
            self.email_address = str(email_address_value) if email_address_value else ""

        if "email_password" in config:
            email_password_value = config["email_password"]
            if isinstance(email_password_value, dict):
                email_password_value = (
                    email_password_value.get("value")
                    or email_password_value.get("default")
                    or ""
                )
            self.email_password = str(email_password_value) if email_password_value else ""

        if "imap_server" in config:
            imap_server_value = config["imap_server"]
            if isinstance(imap_server_value, dict):
                imap_server_value = (
                    imap_server_value.get("value")
                    or imap_server_value.get("default")
                    or "imap.gmail.com"
                )
            self.imap_server = str(imap_server_value) if imap_server_value else "imap.gmail.com"

        if "imap_port" in config:
            imap_port_value = config["imap_port"]
            if isinstance(imap_port_value, dict):
                imap_port_value = imap_port_value.get("value") or imap_port_value.get("default") or 993
            try:
                self.imap_port = int(imap_port_value) if imap_port_value else 993
            except (ValueError, TypeError):
                self.imap_port = 993

        if "target_directory" in config:
            target_dir = config["target_directory"]
            if isinstance(target_dir, dict):
                target_dir = target_dir.get("value") or target_dir.get("default")
            if target_dir and str(target_dir).strip():
                self.target_directory = Path(str(target_dir)).resolve()
                self.target_directory.mkdir(parents=True, exist_ok=True)

        if "check_interval" in config:
            check_interval_value = config["check_interval"]
            if isinstance(check_interval_value, dict):
                check_interval_value = (
                    check_interval_value.get("value")
                    or check_interval_value.get("default")
                    or 300
                )
            try:
                self.check_interval = int(check_interval_value) if check_interval_value else 300
            except (ValueError, TypeError):
                self.check_interval = 300

        if "mark_as_read" in config:
            mark_as_read_value = config["mark_as_read"]
            if isinstance(mark_as_read_value, dict):
                mark_as_read_value = (
                    mark_as_read_value.get("value") or mark_as_read_value.get("default") or True
                )
            self.mark_as_read = (
                str(mark_as_read_value).lower() in ("true", "1", "yes")
                if isinstance(mark_as_read_value, str)
                else bool(mark_as_read_value)
            )

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

    # Extract config values
    email_address = config.get("email_address", "")
    email_password = config.get("email_password", "")
    imap_server = config.get("imap_server", "imap.gmail.com")
    imap_port = config.get("imap_port", 993)
    target_directory = config.get("target_directory")
    check_interval = config.get("check_interval", 300)
    mark_as_read = config.get("mark_as_read", True)

    # Handle schema objects
    if isinstance(email_address, dict):
        email_address = email_address.get("value") or email_address.get("default") or ""
    email_address = str(email_address) if email_address else ""

    if isinstance(email_password, dict):
        email_password = email_password.get("value") or email_password.get("default") or ""
    email_password = str(email_password) if email_password else ""

    if isinstance(imap_server, dict):
        imap_server = imap_server.get("value") or imap_server.get("default") or "imap.gmail.com"
    imap_server = str(imap_server) if imap_server else "imap.gmail.com"

    if isinstance(imap_port, dict):
        imap_port = imap_port.get("value") or imap_port.get("default") or 993
    try:
        imap_port = int(imap_port) if imap_port else 993
    except (ValueError, TypeError):
        imap_port = 993

    if isinstance(target_directory, dict):
        target_directory = target_directory.get("value") or target_directory.get("default")
    target_directory = Path(target_directory) if target_directory else None

    if isinstance(check_interval, dict):
        check_interval = check_interval.get("value") or check_interval.get("default") or 300
    try:
        check_interval = int(check_interval) if check_interval else 300
    except (ValueError, TypeError):
        check_interval = 300

    if isinstance(mark_as_read, dict):
        mark_as_read = mark_as_read.get("value") or mark_as_read.get("default") or True
    mark_as_read = (
        str(mark_as_read).lower() in ("true", "1", "yes")
        if isinstance(mark_as_read, str)
        else bool(mark_as_read)
    )

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

    from sqlalchemy import select

    from app.models.db_models import PluginDB
    from app.plugins.manager import plugin_manager
    from app.plugins.registry import plugin_registry

    logger = logging.getLogger(__name__)

    # Check if we have required config (email and password)
    email_address = config.get("email_address", "")
    email_password = config.get("email_password", "")

    if not email_address or not email_password:
        logger.info("[IMAP] Skipping instance creation - missing email or password")
        return {"instance_created": False, "instance_updated": False}

    # Check if IMAP instance exists
    try:
        # Try async first
        result = await session.execute(select(PluginDB).where(PluginDB.type_id == "imap"))
        imap_instance = result.scalar_one_or_none()
    except TypeError:
        # Fallback to sync if session is not async
        result = session.execute(select(PluginDB).where(PluginDB.type_id == "imap"))
        imap_instance = result.scalar_one_or_none()

    if not imap_instance:
        # Create new IMAP instance
        plugin_instance_id = f"imap-{abs(hash(email_address)) % 10000}"
        logger.info(f"[IMAP] Creating new instance: {plugin_instance_id}")
        try:
            instance_enabled = (
                enabled if enabled is not None else (db_type.enabled if db_type else True)
            )
            plugin = await plugin_registry.register_plugin(
                plugin_id=plugin_instance_id,
                type_id="imap",
                name="IMAP Email",
                config=config,
                enabled=instance_enabled,
            )
            return {
                "instance_created": True,
                "instance_id": plugin_instance_id,
            }
        except Exception as e:
            logger.error(f"[IMAP] Failed to create instance: {e}", exc_info=True)
            return {"instance_created": False, "error": str(e)}
    else:
        # Update existing IMAP instance
        logger.info(f"[IMAP] Updating existing instance: {imap_instance.id}")
        plugin = plugin_manager.get_plugin(imap_instance.id)
        if plugin:
            await plugin.configure(config)
            instance_enabled = (
                enabled
                if enabled is not None
                else (db_type.enabled if db_type else imap_instance.enabled)
            )

            if instance_enabled:
                plugin.enable()
                if not plugin.is_running():
                    try:
                        await plugin.initialize()
                        plugin.start()
                    except Exception as e:
                        logger.error(f"[IMAP] Error starting plugin: {e}", exc_info=True)
            else:
                plugin.disable()
                if plugin.is_running():
                    try:
                        plugin.stop()
                        await plugin.cleanup()
                    except Exception as e:
                        logger.warning(f"[IMAP] Error stopping plugin: {e}", exc_info=True)

            # Update in database
            imap_instance.config = config
            imap_instance.enabled = instance_enabled
            if db_type:
                db_type.enabled = instance_enabled
            try:
                await session.commit()
            except TypeError:
                session.commit()

            return {
                "instance_updated": True,
                "instance_id": imap_instance.id,
            }
        else:
            logger.warning(f"[IMAP] Plugin instance {imap_instance.id} not found in manager")
            return {"instance_updated": False, "error": "Plugin instance not found"}

"""IMAP email backend plugin - downloads images from email attachments.

Plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, `test_connection()` as the classmethod
test verb, and instance-level `fetch()` as the on-demand "check mail now"
verb (the host's POST /plugins/imap/fetch route calls it on each enabled
instance). Scheduled checking runs through `get_schedule_config()` /
`run_scheduled_task()` exactly as before.
"""

import asyncio
import email
import imaplib
import os
from email.header import decode_header
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import BackendPlugin


class ImapBackendPlugin(BackendPlugin):
    """IMAP email backend plugin for downloading images from email attachments.

    This plugin downloads images from email attachments to the local images
    directory, where they can be served by the LocalImagePlugin. It does not
    implement image serving/viewing functionality itself.
    """

    metadata = PluginMetadata(
        type_id="imap",
        name="Email (IMAP)",
        description=(
            "Download images from email attachments. Works with Gmail, Outlook, "
            "and any IMAP provider. Share photos from Android using Share → Email."
        ),
        default_instance_name="IMAP Email",
        instance_label="Email Account",
        # Same account on the same server -> same instance
        instance_identity=["email_address", "imap_server"],
        instance_config_schema={
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
                "description": (
                    "Email password or app-specific password (for Gmail, use App Password)"
                ),
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter password or App Password",
                    "help_text": (
                        "For Gmail, use an App Password instead of your regular password"
                    ),
                    "validation": {
                        "required": True,
                    },
                },
            },
            "imap_server": {
                "type": "string",
                "description": (
                    "IMAP server address (e.g., imap.gmail.com, imap-mail.outlook.com)"
                ),
                "default": "imap.gmail.com",
                "ui": {
                    "component": "input",
                    "placeholder": "imap.gmail.com",
                },
            },
            "imap_port": {
                "type": "integer",
                "description": "IMAP server port (usually 993 for SSL)",
                "default": 993,
                "ui": {
                    "component": "number",
                    "min": 1,
                    "max": 65535,
                    "placeholder": "993",
                },
            },
            "check_interval": {
                "type": "integer",
                "description": (
                    "How often to check for new emails (seconds, default: 300 = 5 minutes)"
                ),
                "default": 300,
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
                "description": (
                    "Directory to save downloaded images (defaults to local images directory)"
                ),
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "./data/images (default)",
                    "help_text": "Leave empty to use the local images directory",
                },
            },
            "mark_as_read": {
                "type": "boolean",
                "description": "Mark processed emails as read (default: yes)",
                "default": True,
                "ui": {
                    "component": "select",
                    "options": [
                        {"value": "true", "label": "Yes"},
                        {"value": "false", "label": "No"},
                    ],
                },
            },
        },
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
            {
                "id": "fetch",
                "type": "fetch",
                "label": "Fetch Now",
                "style": "secondary",
                "scope": "instance",
            },
        ],
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self.supported_formats = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        self._processed_emails: set[str] = set()  # Track processed email UIDs

    # Config accessors — values live in self.config (schema-normalized);
    # these apply the trims/fallbacks the wire format doesn't guarantee.

    @property
    def email_address(self) -> str:
        return str(self.config.get("email_address") or "").strip()

    @property
    def email_password(self) -> str:
        return str(self.config.get("email_password") or "").strip()

    @property
    def imap_server(self) -> str:
        return str(self.config.get("imap_server") or "").strip() or "imap.gmail.com"

    @property
    def imap_port(self) -> int:
        return int(self.config.get("imap_port") or 993)

    @property
    def check_interval(self) -> int:
        return int(self.config.get("check_interval") or 300)

    @property
    def mark_as_read(self) -> bool:
        value = self.config.get("mark_as_read")
        return True if value is None else bool(value)

    @property
    def target_directory(self) -> Path:
        """Directory images are saved to (defaults to the local images dir)."""
        configured = str(self.config.get("target_directory") or "").strip()
        if configured:
            return Path(configured).resolve()
        image_dir = os.getenv("IMAGE_DIR")
        if image_dir:
            return Path(image_dir).resolve()
        return Path("./data/images").resolve()

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration; re-register the scheduled task if the interval changed."""
        old_check_interval = self.check_interval

        await super().configure(config)

        self.target_directory.mkdir(parents=True, exist_ok=True)

        # Re-register scheduled tasks if interval changed and plugin is running
        if self.is_running() and self.enabled and old_check_interval != self.check_interval:
            from app.services.backend_scheduler import backend_plugin_scheduler

            if backend_plugin_scheduler.scheduler.running:
                try:
                    await backend_plugin_scheduler.unregister_plugin_tasks(self.plugin_id)
                    await backend_plugin_scheduler.register_plugin_tasks(self)
                except Exception as e:
                    logger.warning(
                        "Error re-registering scheduled tasks for IMAP plugin {} "
                        "after config change: {}",
                        self.plugin_id,
                        e,
                    )

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require credentials; bound the IMAP port and check interval."""
        normalized = cls.normalize_config(config)
        if not str(normalized.get("email_address") or "").strip():
            return False
        if not str(normalized.get("email_password") or "").strip():
            return False

        imap_port = normalized.get("imap_port")
        if imap_port is not None and not (1 <= int(imap_port) <= 65535):
            return False

        check_interval = normalized.get("check_interval")
        if check_interval is not None and not (60 <= int(check_interval) <= 3600):
            return False

        return True

    # ------------------------------------------------------------------
    # Scheduled checking
    # ------------------------------------------------------------------

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
                return {
                    "success": True,
                    "message": "No new emails with image attachments found",
                    "data": {"images_downloaded": 0},
                }
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

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """On-demand "check mail now" — runs the email check on this instance."""
        result = await self.run_scheduled_task()
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "images_downloaded": result.get("data", {}).get("images_downloaded", 0),
        }

    # ------------------------------------------------------------------
    # IMAP mechanics
    # ------------------------------------------------------------------

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
                "message": (
                    f"Processed {len(email_ids)} email(s), "
                    f"downloaded {images_downloaded} image(s)"
                ),
                "images_downloaded": images_downloaded,
            }

        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            if (
                "authentication failed" in error_msg.lower()
                or "invalid credentials" in error_msg.lower()
            ):
                return {
                    "success": False,
                    "message": (
                        "Authentication failed. Please check your email address and password."
                    ),
                    "images_downloaded": 0,
                }
            elif "connection refused" in error_msg.lower() or "timeout" in error_msg.lower():
                return {
                    "success": False,
                    "message": (
                        f"Could not connect to {self.imap_server}. "
                        "Please check the server address and port."
                    ),
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
        target_directory = self.target_directory
        target_directory.mkdir(parents=True, exist_ok=True)

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
                    image_path = target_directory / decoded_filename
                    # Avoid overwriting existing files
                    counter = 1
                    while image_path.exists():
                        stem = Path(decoded_filename).stem
                        image_path = target_directory / f"{stem}_{counter}{file_ext}"
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

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Test IMAP connection using the provided (possibly unsaved) configuration."""
        normalized = cls.normalize_config(config)
        email_address = str(normalized.get("email_address") or "").strip()
        email_password = str(normalized.get("email_password") or "").strip()
        imap_server = str(normalized.get("imap_server") or "").strip() or "imap.gmail.com"
        imap_port = int(normalized.get("imap_port") or 993)

        if not email_address or not email_password:
            return {
                "success": False,
                "message": "Email address and password are required",
            }

        try:
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
                    "message": (
                        "Authentication failed. Please check your email address and password."
                    ),
                }
            if "connection refused" in error_msg.lower() or "timeout" in error_msg.lower():
                return {
                    "success": False,
                    "message": (
                        f"Could not connect to {imap_server}. "
                        "Please check the server address and port."
                    ),
                }
            return {
                "success": False,
                "message": f"Connection error: {error_msg}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error: {str(e)}",
            }

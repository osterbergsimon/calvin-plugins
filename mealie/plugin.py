"""Mealie meal planning service plugin."""

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_int, to_str, to_bool
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)


class MealieServicePlugin(ServicePlugin):
    """Mealie service plugin for displaying meal plans."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "mealie",
            "plugin_type": PluginType.SERVICE,
            "name": "Mealie Meal Plan",
            "description": "Display weekly meal plan from Mealie recipe manager",
            "version": "1.0.0",
            "supports_multiple_instances": False,  # Single-instance plugin
            "common_config_schema": {
                "display_order": {
                    "type": "integer",
                    "description": "Display order for service instances",
                    "default": 0,
                    "ui": {
                        "component": "number",
                        "help_text": (
                            "Order for display/switching (lower numbers appear first). "
                            "This applies to all instances of this plugin type."
                        ),
                        "validation": {
                            "min": 0,
                        },
                    },
                },
            },
            "instance_config_schema": {
                "mealie_url": {
                    "type": "string",
                    "description": "Mealie instance URL (e.g., http://mealie.local:9000)",
                    "default": "",
                    "ui": {
                        "component": "input",
                        "placeholder": "http://mealie.local:9000",
                        "validation": {
                            "required": True,
                            "type": "url",
                        },
                    },
                },
                "api_token": {
                    "type": "password",
                    "description": "Mealie API token (create at /user/profile/api-tokens)",
                    "default": "",
                    "ui": {
                        "component": "password",
                        "placeholder": "Enter your Mealie API token",
                        "help_text": "Create an API token in Mealie at /user/profile/api-tokens",
                        "validation": {
                            "required": True,
                        },
                    },
                },
                "group_id": {
                    "type": "string",
                    "description": "Group ID (optional, defaults to user's default group)",
                    "default": "",
                    "ui": {
                        "component": "input",
                        "placeholder": "Leave empty for default group",
                    },
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to show meal plan (default: 7)",
                    "default": 7,
                    "ui": {
                        "component": "number",
                        "placeholder": "7",
                        "help_text": "Number of days from today to display meals (e.g., 7 for a week)",  # noqa: E501
                        "validation": {
                            "min": 1,
                            "max": 30,
                        },
                    },
                },
                "meal_plan_card_size": {
                    "type": "string",
                    "description": "Meal plan card size",
                    "default": "medium",
                    "ui": {
                        "component": "select",
                        "options": [
                            {"value": "small", "label": "Small (fit 7+ cards)"},
                            {"value": "medium", "label": "Medium (default)"},
                            {"value": "large", "label": "Large"},
                        ],
                        "help_text": (
                            "Size of meal plan cards. "
                            "Smaller size allows more cards to fit on screen."
                        ),
                    },
                },
                "fullscreen": {
                    "type": "boolean",
                    "description": "Prefer fullscreen mode",
                    "default": False,
                    "ui": {
                        "component": "checkbox",
                        "help_text": "Open this service in fullscreen by default",
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
            ],
            "display_schema": {
                "type": "api",
                "api_endpoint": "/api/web-services/{service_id}/data",
                "method": "GET",
                "component": "mealie/MealPlanViewer.vue",  # Plugin-provided frontend component
                "data_schema": {
                    "items": {
                        "type": "array",
                        "description": "List of meal plan items",
                        "item_schema": {
                            "date": {
                                "type": "string",
                                "format": "date",
                                "description": "Date of the meal plan item",
                            },
                            "meals": {
                                "type": "array",
                                "description": "List of meals for this date",
                                "item_schema": {
                                    "type": {
                                        "type": "string",
                                        "description": "Meal type (breakfast, lunch, dinner, etc.)",
                                    },
                                    "recipe": {
                                        "type": "object",
                                        "description": "Recipe information",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "description": "Recipe name",
                                            },
                                        },
                                    },
                                    "name": {
                                        "type": "string",
                                        "description": "Meal name (fallback if no recipe)",
                                    },
                                },
                            },
                        },
                    },
                    "start_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Start date of the meal plan",
                    },
                    "end_date": {
                        "type": "string",
                        "format": "date",
                        "description": "End date of the meal plan",
                    },
                },
                "render_template": "meal_plan",  # Legacy: kept for backward compatibility
            },
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        mealie_url: str,
        api_token: str,
        group_id: str | None = None,
        days_ahead: int = 7,
        enabled: bool = True,
        display_order: int = 0,
        fullscreen: bool = False,
    ):
        """
        Initialize Mealie service plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            mealie_url: Mealie instance URL
            api_token: Mealie API token
            group_id: Optional group ID (defaults to user's default group)
            days_ahead: Number of days ahead to show meal plan (default: 7)
            enabled: Whether the plugin is enabled
            display_order: Display order for service rotation
            fullscreen: Whether to display in fullscreen mode
        """
        super().__init__(plugin_id, name, enabled)
        self.mealie_url = mealie_url.rstrip("/")
        self.api_token = api_token
        self.group_id = group_id
        self.days_ahead = days_ahead
        self.display_order = display_order
        self.fullscreen = fullscreen
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize the plugin."""
        # Validate URL
        if not self.mealie_url or not (
            self.mealie_url.startswith("http://") or self.mealie_url.startswith("https://")
        ):
            raise ValueError(f"Invalid Mealie URL: {self.mealie_url}")

        # Validate API token
        if not self.api_token or not self.api_token.strip():
            raise ValueError("Mealie API token is required but not set")

        # Create HTTP client with authentication
        headers = {"Authorization": f"Bearer {self.api_token.strip()}"}
        self._client = httpx.AsyncClient(
            base_url=self.mealie_url,
            headers=headers,
            timeout=30.0,
        )

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_content(self) -> dict[str, Any]:
        """
        Get service content for display.

        Returns:
            Dictionary with content information
        """
        # Return a special URL that points to our backend endpoint
        # The frontend will detect "mealie" type and fetch data from our API
        # This avoids CORS issues and handles authentication properly
        # Use generic /data endpoint for forward compatibility
        meal_plan_api_url = f"/api/web-services/{self.plugin_id}/data"

        return {
            "type": "mealie",
            "url": meal_plan_api_url,  # Points to our backend endpoint
            "data": {
                "mealie_url": self.mealie_url,
                "api_token": self.api_token,  # Not sent to frontend, used by backend
                "group_id": self.group_id,
            },
            "config": {
                "allowFullscreen": True,
            },
        }

    def get_config(self) -> dict[str, Any]:
        """
        Get plugin configuration.

        Returns:
            Configuration dictionary
        """
        # Store the meal plan API URL in config so web_service_service can read it
        # This points to our backend endpoint that proxies Mealie API calls
        meal_plan_api_url = f"/api/web-services/{self.plugin_id}/data"
        return {
            "url": meal_plan_api_url,
            "mealie_url": self.mealie_url,
            "api_token": self.api_token,
            "group_id": self.group_id,
            "days_ahead": self.days_ahead,
            "display_order": self.display_order,
            "fullscreen": self.fullscreen,
        }

    async def fetch_service_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch meal plan data from Mealie API (protocol-defined method).

        Args:
            start_date: Optional start date (YYYY-MM-DD), defaults to today
            end_date: Optional end date (YYYY-MM-DD), defaults to today + days_ahead

        Returns:
            Dictionary with meal plan data, including metadata for frontend
        """
        # Reload config from database to ensure we have the latest API token
        # This is important because the plugin instance might have been created
        # with stale config, and the API token might have been updated
        await self._reload_config_from_db()

        data = await self._fetch_meal_plan(start_date=start_date, end_date=end_date)

        # Add mealie_url to response metadata for frontend
        if self.mealie_url:
            if isinstance(data, dict):
                if "_metadata" not in data:
                    data["_metadata"] = {}
                data["_metadata"]["mealie_url"] = self.mealie_url.rstrip("/")
            elif isinstance(data, list):
                data = {"items": data, "_metadata": {"mealie_url": self.mealie_url.rstrip("/")}}

        return data

    async def _fetch_meal_plan(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """
        Fetch meal plan data from Mealie API.

        Args:
            start_date: Optional start date (YYYY-MM-DD), defaults to today
            end_date: Optional end date (YYYY-MM-DD), defaults to today + days_ahead

        Returns:
            Dictionary with meal plan data
        """
        # Log API token status before initializing
        token_status = "present" if self.api_token else "missing"
        token_length = len(self.api_token) if self.api_token else 0
        print(
            f"[Mealie] _fetch_meal_plan called - API token: {token_status} "
            f"(length: {token_length}), URL: {self.mealie_url}"
        )

        if not self._client:
            await self.initialize()

        try:
            # Calculate date range
            if start_date:
                try:
                    today = datetime.fromisoformat(start_date).date()
                except (ValueError, TypeError):
                    today = datetime.now().date()
            else:
                today = datetime.now().date()

            if end_date:
                try:
                    week_end = datetime.fromisoformat(end_date).date()
                except (ValueError, TypeError):
                    week_end = today + timedelta(days=self.days_ahead)
            else:
                week_end = today + timedelta(days=self.days_ahead)

            # Mealie API endpoint for meal plans
            # Based on typical REST API patterns, this might be /api/meal-plans or /api/mealplan
            # We'll try the most common pattern first
            params = {
                "start_date": today.isoformat(),
                "end_date": week_end.isoformat(),
            }
            if self.group_id:
                params["group_id"] = self.group_id

            # Mealie API endpoints - based on Mealie docs, use /api/households/mealplans
            # Try with date range parameters first
            endpoints_to_try = [
                ("/api/households/mealplans", params),
                # Try without group_id if it was specified
                ("/api/households/mealplans", {k: v for k, v in params.items() if k != "group_id"}),
                # Try alternative endpoints
                ("/api/meal-plans", params),
                ("/api/mealplan", params),
            ]

            for endpoint, endpoint_params in endpoints_to_try:
                try:
                    print(f"[Mealie] Trying endpoint: {endpoint} with params: {endpoint_params}")
                    response = await self._client.get(endpoint, params=endpoint_params)
                    print(f"[Mealie] Response from {endpoint}: status={response.status_code}")

                    if response.status_code == 200:
                        data = response.json()
                        # Log response structure for debugging
                        if isinstance(data, dict):
                            item_count = (
                                len(data.get("items", []))
                                if "items" in data
                                else len(data)
                                if isinstance(data, list)
                                else 0
                            )
                            print(
                                f"[Mealie] Successfully fetched meal plan from {endpoint}: "
                                f"{item_count} items"
                            )
                        elif isinstance(data, list):
                            print(
                                f"[Mealie] Successfully fetched meal plan from {endpoint}: "
                                f"{len(data)} items"
                            )
                        return data
                    elif response.status_code == 404:
                        # Try next endpoint
                        print(f"[Mealie] Endpoint {endpoint} returned 404, trying next...")
                        continue
                    else:
                        # Log non-200, non-404 responses
                        try:
                            error_body = response.text[:500]  # First 500 chars
                            print(
                                f"[Mealie] Endpoint {endpoint} returned "
                                f"{response.status_code}: {error_body}"
                            )
                        except Exception:
                            pass
                        response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        print(f"[Mealie] Endpoint {endpoint} not found (404), trying next...")
                        continue
                    # Log other HTTP errors
                    try:
                        error_body = e.response.text[:500]
                        print(
                            f"[Mealie] HTTP error from {endpoint}: "
                            f"{e.response.status_code} - {error_body}"
                        )
                    except Exception:
                        print(f"[Mealie] HTTP error from {endpoint}: {e.response.status_code}")
                    raise
                except Exception as e:
                    print(f"[Mealie] Unexpected error trying {endpoint}: {type(e).__name__}: {e}")
                    raise

            # If all endpoints failed, return empty meal plan
            tried_endpoints = [e[0] for e in endpoints_to_try]
            print(f"[Mealie] ERROR: Could not find meal plan endpoint. Tried: {tried_endpoints}")
            print(f"[Mealie] Date range: {today.isoformat()} to {week_end.isoformat()}")
            print(f"[Mealie] Group ID: {self.group_id or 'not specified'}")
            return {
                "items": [],
                "start_date": today.isoformat(),
                "end_date": week_end.isoformat(),
                "error": "Could not find meal plan endpoint. Please check Mealie API documentation.",  # noqa: E501
            }

        except httpx.HTTPStatusError as e:
            error_detail = f"HTTP error: {e.response.status_code}"
            # Add more detail for 401 errors
            if e.response.status_code == 401:
                error_detail = (
                    "HTTP error: 401 - Authentication failed. Please check your API token."
                )
                # Log response body for debugging (may contain useful error info)
                try:
                    response_body = e.response.text
                    print(f"[Mealie] 401 response body: {response_body[:500]}")  # First 500 chars
                except Exception:
                    pass
            elif e.response.status_code == 403:
                error_detail = (
                    "HTTP error: 403 - Forbidden. "
                    "API token may not have permission to access meal plans."
                )
                try:
                    response_body = e.response.text
                    print(f"[Mealie] 403 response body: {response_body[:500]}")
                except Exception:
                    pass
            elif e.response.status_code == 404:
                error_detail = (
                    "HTTP error: 404 - Meal plan endpoint not found. "
                    "Check Mealie version and API documentation."
                )
            else:
                # Log response body for other errors
                try:
                    response_body = e.response.text
                    print(f"[Mealie] {e.response.status_code} response body: {response_body[:500]}")
                except Exception:
                    pass

            print(f"[Mealie] HTTP error fetching meal plan: {e.response.status_code}")
            print(f"[Mealie] Request URL: {e.request.url}")
            print(f"[Mealie] Request method: {e.request.method}")
            # Log token status (without exposing the actual token)
            token_status = "present" if self.api_token else "missing"
            token_length = len(self.api_token) if self.api_token else 0
            print(f"[Mealie] API token status: {token_status} (length: {token_length})")
            print(f"[Mealie] Mealie URL: {self.mealie_url}")
            return {
                "items": [],
                "error": error_detail,
            }
        except httpx.HTTPError as e:
            print(f"[Mealie] Network/HTTP error fetching meal plan: {type(e).__name__}: {e}")
            print(f"[Mealie] Mealie URL: {self.mealie_url}")
            import traceback

            traceback.print_exc()
            return {
                "items": [],
                "error": f"Network error: {str(e)}",
            }
        except Exception as e:
            print(f"[Mealie] Unexpected error fetching meal plan: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return {
                "items": [],
                "error": f"Unexpected error: {str(e)}",
            }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """
        Validate plugin configuration.

        Args:
            config: Configuration dictionary

        Returns:
            True if configuration is valid
        """
        # Check required fields
        mealie_url = extract_config_value(config, "mealie_url", default="", converter=to_str)
        api_token = extract_config_value(config, "api_token", default="", converter=to_str)

        if not mealie_url or not mealie_url.strip():
            return False
        if not api_token or not api_token.strip():
            return False

        # URL must be valid
        url = mealie_url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return False

        # Days ahead should be valid if provided
        if "days_ahead" in config:
            days_ahead = extract_config_value(config, "days_ahead", default=7, converter=to_int)
            if days_ahead < 1 or days_ahead > 30:
                return False

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with new settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)

        # Close existing client if any
        if self._client:
            await self._client.aclose()

        if "mealie_url" in config:
            mealie_url = extract_config_value(config, "mealie_url", default="", converter=to_str)
            self.mealie_url = mealie_url.rstrip("/") if mealie_url else ""
        if "api_token" in config:
            api_token = extract_config_value(config, "api_token", default="", converter=to_str)
            self.api_token = api_token.strip() if api_token else ""
        if "group_id" in config:
            group_id = extract_config_value(config, "group_id", default="", converter=to_str)
            self.group_id = group_id.strip() if group_id else None
        if "days_ahead" in config:
            self.days_ahead = extract_config_value(config, "days_ahead", default=7, converter=to_int)
        if "display_order" in config:
            self.display_order = extract_config_value(config, "display_order", default=0, converter=to_int)
        if "fullscreen" in config:
            self.fullscreen = extract_config_value(config, "fullscreen", default=False, converter=to_bool)

        # Reinitialize with new config
        await self.initialize()

    async def _reload_config_from_db(self) -> None:
        """
        Reload plugin config from database to ensure we have the latest values,
        especially the API token which might have been updated.
        """
        import traceback

        from app.models.db_models import PluginDB

        try:
            print(f"[Mealie] Reloading config from DB for plugin_id: {self.plugin_id}")
            db_plugin = await PluginDB.objects.get_or_none(id=self.plugin_id)

            if not db_plugin:
                print(f"[Mealie] WARNING: Plugin {self.plugin_id} not found in database")
                return

            if not db_plugin.config:
                print(f"[Mealie] WARNING: Plugin {self.plugin_id} has no config in database")
                return

            config = db_plugin.config
            print(f"[Mealie] Found config in DB with keys: {list(config.keys())}")

            # Check if API token has changed
            new_api_token = config.get("api_token", "")
            if isinstance(new_api_token, dict):
                new_api_token = new_api_token.get("value") or new_api_token.get("default") or ""
            new_api_token = str(new_api_token).strip() if new_api_token else ""

            current_token_length = len(self.api_token) if self.api_token else 0
            new_token_length = len(new_api_token) if new_api_token else 0
            print(
                f"[Mealie] Token comparison - current: {current_token_length} chars, "
                f"new: {new_token_length} chars"
            )

            # Only reconfigure if API token has changed or is missing
            if new_api_token and new_api_token != self.api_token:
                print(
                    f"[Mealie] API token changed, reloading config from database "
                    f"(old length: {len(self.api_token)}, new length: {len(new_api_token)})"
                )
                await self.configure(config)
            elif not self.api_token and new_api_token:
                print(
                    f"[Mealie] API token was missing, reloading config from database "
                    f"(new length: {len(new_api_token)})"
                )
                await self.configure(config)
            else:
                print("[Mealie] API token unchanged, no reload needed")
        except Exception as e:
            print(f"[Mealie] ERROR reloading config from database: {e}")
            print("[Mealie] Traceback:")
            traceback.print_exc()
            # Don't fail the request if we can't reload config
            # The existing config might still work


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register MealieServicePlugin type."""
    return [MealieServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> MealieServicePlugin | None:
    """Create a MealieServicePlugin instance."""
    if type_id != "mealie":
        return None

    enabled = config.get("enabled", False)  # Default to disabled

    # Extract config values using utility functions
    mealie_url = extract_config_value(config, "mealie_url", default="", converter=to_str)
    mealie_url = mealie_url.rstrip("/") if mealie_url else ""
    
    api_token = extract_config_value(config, "api_token", default="", converter=to_str)
    api_token = api_token.strip() if api_token else ""
    
    group_id = extract_config_value(config, "group_id", default="", converter=to_str)
    group_id = group_id.strip() if group_id else None
    
    days_ahead = extract_config_value(config, "days_ahead", default=7, converter=to_int)
    display_order = extract_config_value(config, "display_order", default=0, converter=to_int)
    fullscreen = extract_config_value(config, "fullscreen", default=False, converter=to_bool)

    return MealieServicePlugin(
        plugin_id=plugin_id,
        name=name,
        mealie_url=mealie_url,
        api_token=api_token,
        group_id=group_id,
        days_ahead=days_ahead,
        enabled=enabled,
        display_order=display_order,
        fullscreen=fullscreen,
    )


@hookimpl
async def test_plugin_connection(
    type_id: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Test Mealie API connection and verify API token permissions."""
    if type_id != "mealie":
        return None

    mealie_url = config.get("mealie_url", "").rstrip("/")
    api_token = config.get("api_token", "")
    group_id = config.get("group_id", "")

    if not mealie_url or not api_token:
        return {
            "success": False,
            "message": "Mealie URL and API token are required",
        }

    headers = {"Authorization": f"Bearer {api_token}"}
    test_results = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test 1: Verify API token by checking user info
            print(f"[Mealie Test] Testing connection to {mealie_url}...")
            try:
                response = await client.get(
                    f"{mealie_url}/api/users/self",
                    headers=headers,
                )
                if response.status_code == 200:
                    user_data = response.json()
                    user_id = user_data.get("id", "unknown")
                    username = user_data.get("username", "unknown")
                    test_results.append(f"✓ Authentication successful (user: {username})")
                    print(f"[Mealie Test] User authenticated: {username} (ID: {user_id})")
                elif response.status_code == 401:
                    return {
                        "success": False,
                        "message": "Authentication failed. Please check your API token.",
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Authentication check failed. Status: {response.status_code}",
                    }
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    return {
                        "success": False,
                        "message": "Authentication failed. Please check your API token.",
                    }
                return {
                    "success": False,
                    "message": f"Authentication check failed. Status: {e.response.status_code}",
                }

            # Test 2: Verify access to meal plans endpoint
            print("[Mealie Test] Testing meal plan access...")
            from datetime import datetime, timedelta

            today = datetime.now().date()
            end_date = today + timedelta(days=7)
            meal_plan_params = {
                "start_date": today.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if group_id:
                meal_plan_params["group_id"] = group_id

            # Try the meal plan endpoint
            meal_plan_endpoints = [
                "/api/households/mealplans",
                "/api/meal-plans",
                "/api/mealplan",
            ]

            meal_plan_accessible = False
            for endpoint in meal_plan_endpoints:
                try:
                    response = await client.get(
                        f"{mealie_url}{endpoint}",
                        headers=headers,
                        params=meal_plan_params,
                    )
                    if response.status_code == 200:
                        meal_plan_accessible = True
                        data = response.json()
                        item_count = 0
                        if isinstance(data, dict):
                            item_count = len(data.get("items", [])) if "items" in data else 0
                        elif isinstance(data, list):
                            item_count = len(data)
                        test_results.append(
                            f"✓ Meal plan access successful "
                            f"({endpoint}: {item_count} items found)"
                        )
                        print(
                            f"[Mealie Test] Meal plan endpoint {endpoint} accessible: "
                            f"{item_count} items"
                        )
                        break
                    elif response.status_code == 404:
                        continue  # Try next endpoint
                    elif response.status_code == 403:
                        test_results.append(
                            "⚠ Meal plan endpoint accessible but permission denied (403)"
                        )
                        print(
                            f"[Mealie Test] Meal plan endpoint {endpoint} returned 403 "
                            "(permission denied)"
                        )
                        break
                    else:
                        print(
                            f"[Mealie Test] Meal plan endpoint {endpoint} returned "
                            f"{response.status_code}"
                        )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    elif e.response.status_code == 403:
                        test_results.append(
                            "⚠ Meal plan endpoint accessible but permission denied (403)"
                        )
                        print(f"[Mealie Test] Meal plan endpoint {endpoint} returned 403")
                        break
                    else:
                        print(
                            f"[Mealie Test] Meal plan endpoint {endpoint} error: "
                            f"{e.response.status_code}"
                        )

            if not meal_plan_accessible:
                test_results.append(
                    "⚠ Could not access meal plan endpoint "
                    "(may not have meal plans or wrong endpoint)"
                )

            # Test 3: Verify recipes endpoint (optional, to confirm API is working)
            try:
                response = await client.get(
                    f"{mealie_url}/api/recipes",
                    headers=headers,
                    params={"perPage": 1},  # Just check if accessible
                )
                if response.status_code == 200:
                    test_results.append("✓ Recipes API accessible")
                    print("[Mealie Test] Recipes endpoint accessible")
            except Exception:
                pass  # Not critical for meal plan functionality

            # Build success message
            if meal_plan_accessible:
                message = "Connection successful!\n" + "\n".join(test_results)
                return {
                    "success": True,
                    "message": message,
                }
            else:
                message = (
                    "Connection successful, but meal plan access failed.\n"
                    + "\n".join(test_results)
                    + "\n\nPlease verify:"
                    + "\n- API token has permission to access meal plans"
                    + "\n- Meal plans exist for the date range "
                    + f"({today.isoformat()} to {end_date.isoformat()})"
                    + "\n- Group ID is correct (if specified)"
                )
                return {
                    "success": False,
                    "message": message,
                }

    except httpx.ConnectError:
        return {
            "success": False,
            "message": f"Could not connect to {mealie_url}. Please check the URL.",
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": f"Connection to {mealie_url} timed out. Please check the URL and network.",
        }
    except Exception as e:
        import traceback

        print(f"[Mealie Test] Unexpected error: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "message": f"Error: {str(e)}",
        }


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle Mealie plugin configuration update and instance management."""
    if type_id != "mealie":
        return None

    import logging

    logger = logging.getLogger(__name__)

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        mealie_url = extract_config_value(c, "mealie_url", default="", converter=to_str)
        mealie_url = mealie_url.rstrip("/") if mealie_url else ""
        
        api_token = extract_config_value(c, "api_token", default="", converter=to_str)
        api_token = api_token.strip() if api_token else ""

        # Log token status (without exposing actual token)
        token_status = "present" if api_token else "missing"
        token_length = len(api_token) if api_token else 0
        logger.info(
            f"[Mealie] Config update received - URL: {mealie_url}, "
            f"API token: {token_status} (length: {token_length})"
        )

        # Also check if we can get the token from db_type.common_config_schema as fallback
        if not api_token and db_type and db_type.common_config_schema:
            fallback_token = db_type.common_config_schema.get("api_token", "")
            if fallback_token:
                api_token = str(fallback_token).strip()
                logger.info(
                    f"[Mealie] Retrieved API token from db_type.common_config_schema "
                    f"(length: {len(api_token)})"
                )

        group_id = extract_config_value(c, "group_id", default="", converter=to_str)
        group_id = group_id.strip() if group_id else ""

        return {
            "mealie_url": mealie_url,
            "api_token": api_token,
            "group_id": group_id,
            "days_ahead": extract_config_value(c, "days_ahead", default=7, converter=to_int),
            "display_order": extract_config_value(c, "display_order", default=0, converter=to_int),
            "fullscreen": extract_config_value(c, "fullscreen", default=False, converter=to_bool),
        }

    def validate_config(c: dict[str, Any]) -> bool:
        """Validate config before creating/updating instance."""
        # Check required fields
        mealie_url = c.get("mealie_url", "")
        api_token = c.get("api_token", "")

        if not mealie_url or not mealie_url.strip():
            logger.info("[Mealie] Skipping instance creation - missing URL")
            return False
        if not api_token or not api_token.strip():
            logger.info("[Mealie] Skipping instance creation - missing API token")
            return False

        # URL must be valid
        url = mealie_url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            logger.info("[Mealie] Skipping instance creation - invalid URL")
            return False

        return True

    manager_config = InstanceManagerConfig(
        type_id="mealie",
        single_instance=True,
        instance_id="mealie-instance",
        validate_config=validate_config,
        normalize_config=normalize_config,
        default_instance_name="Mealie Meal Plan",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )





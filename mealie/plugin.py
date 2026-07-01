"""Mealie meal planning service plugin.

Reference plugin for the Calvin plugin contract 1.0: one declarative class,
config declared once in `metadata.instance_config_schema`, a kind-based
`display_schema`, and `fetch()` as the single data verb. There are no
module-level hooks — the host discovers this class and derives everything
else from `metadata`.
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class MealieServicePlugin(ServicePlugin):
    """Mealie service plugin for displaying meal plans."""

    metadata = PluginMetadata(
        type_id="mealie",
        name="Mealie Meal Plan",
        description="Display weekly meal plan from Mealie recipe manager",
        default_instance_name="Mealie Meal Plan",
        instance_label="Server",
        # Same Mealie server -> same instance
        instance_identity=["mealie_url"],
        instance_config_schema={
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
                    "help_text": "Number of days from today to display meals (e.g., 7 for a week)",
                    "validation": {
                        "min": 1,
                        "max": 30,
                    },
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
        ],
        # The payload from fetch() feeds the built-in card-grid renderer:
        # one card per day, one row per meal.
        display_schema={
            "kind": "card-grid",
            "data_path": "$.days",
            "layout": {"columns": "auto-fit-220"},
            "card": {
                "title_path": "$.title",
                "items_path": "$.meals",
                "item": {
                    "label_path": "$.type",
                    "value_path": "$.name",
                    "click_url_path": "$.url",
                },
            },
            "empty_text": "Nothing planned.",
            "poll_interval_ms": 900000,
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._client: httpx.AsyncClient | None = None

    # Config accessors — values live in self.config (schema-normalized);
    # these apply the trims the wire format doesn't guarantee.

    @property
    def mealie_url(self) -> str:
        return str(self.config.get("mealie_url") or "").rstrip("/")

    @property
    def api_token(self) -> str:
        return str(self.config.get("api_token") or "").strip()

    @property
    def group_id(self) -> str | None:
        return str(self.config.get("group_id") or "").strip() or None

    @property
    def days_ahead(self) -> int:
        return int(self.config.get("days_ahead") or 7)

    async def initialize(self) -> None:
        """Validate config and create the authenticated HTTP client."""
        if not self.mealie_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid Mealie URL: {self.mealie_url}")
        if not self.api_token:
            raise ValueError("Mealie API token is required but not set")

        headers = {"Authorization": f"Bearer {self.api_token}"}
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

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration; drop the client so it's rebuilt with new auth."""
        await super().configure(config)
        if self._client:
            await self._client.aclose()
            self._client = None

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require a valid URL and an API token; bound days_ahead."""
        normalized = cls.normalize_config(config)
        url = str(normalized.get("mealie_url") or "").strip()
        token = str(normalized.get("api_token") or "").strip()
        if not url.startswith(("http://", "https://")) or not token:
            return False
        days_ahead = normalized.get("days_ahead")
        if days_ahead is not None and not (1 <= int(days_ahead) <= 30):
            return False
        return True

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch the meal plan and shape it for the card-grid display schema.

        Args:
            start_date: Optional start date (YYYY-MM-DD), defaults to today
            end_date: Optional end date (YYYY-MM-DD), defaults to today + days_ahead

        Returns:
            {"days": [{"title", "date", "meals": [{"type", "name", "url"}]}], ...}
        """
        # Reload config from the database in case the API token was updated
        # after this instance was created.
        await self._reload_config_from_db()

        raw = await self._fetch_meal_plan(start_date=start_date, end_date=end_date)
        return self._shape_for_display(raw)

    def _shape_for_display(self, raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
        """Group raw Mealie meal-plan entries into per-day cards."""
        entries = raw.get("items", []) if isinstance(raw, dict) else raw
        error = raw.get("error") if isinstance(raw, dict) else None

        by_date: dict[str, list[dict[str, Any]]] = {}
        for entry in entries or []:
            date = str(entry.get("date") or "")
            recipe = entry.get("recipe") or {}
            name = recipe.get("name") or entry.get("title") or entry.get("name") or ""
            if not name:
                continue
            slug = recipe.get("slug")
            by_date.setdefault(date, []).append(
                {
                    "type": str(entry.get("entryType") or entry.get("type") or "meal"),
                    "name": name,
                    "url": f"{self.mealie_url}/g/home/r/{slug}" if slug else None,
                }
            )

        days = []
        for date in sorted(by_date):
            days.append(
                {
                    "date": date,
                    "title": self._day_title(date),
                    "meals": by_date[date],
                }
            )

        shaped: dict[str, Any] = {"days": days}
        if error:
            shaped["error"] = error
        if isinstance(raw, dict):
            shaped["start_date"] = raw.get("start_date")
            shaped["end_date"] = raw.get("end_date")
        return shaped

    @staticmethod
    def _day_title(date_string: str) -> str:
        """Human title for a day card: Today / Tomorrow / weekday."""
        try:
            date = datetime.fromisoformat(date_string).date()
        except (ValueError, TypeError):
            return date_string
        today = datetime.now().date()
        if date == today:
            return "Today"
        if date == today + timedelta(days=1):
            return "Tomorrow"
        return date.strftime("%A")

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

            params = {
                "start_date": today.isoformat(),
                "end_date": week_end.isoformat(),
            }
            if self.group_id:
                params["group_id"] = self.group_id

            # Mealie API endpoints - based on Mealie docs, use /api/households/mealplans
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
                    response = await self._client.get(endpoint, params=endpoint_params)
                    if response.status_code == 200:
                        data = response.json()
                        count = (
                            len(data.get("items", []))
                            if isinstance(data, dict)
                            else len(data)
                            if isinstance(data, list)
                            else 0
                        )
                        logger.info(
                            f"[Mealie] Fetched meal plan from {endpoint}: {count} items"
                        )
                        return data if isinstance(data, dict) else {"items": data}
                    if response.status_code == 404:
                        continue
                    logger.warning(
                        f"[Mealie] Endpoint {endpoint} returned {response.status_code}: "
                        f"{response.text[:500]}"
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    raise

            tried_endpoints = [e[0] for e in endpoints_to_try]
            logger.error(f"[Mealie] Could not find meal plan endpoint. Tried: {tried_endpoints}")
            return {
                "items": [],
                "start_date": today.isoformat(),
                "end_date": week_end.isoformat(),
                "error": "Could not find a meal plan endpoint on this Mealie server.",
            }

        except httpx.HTTPStatusError as e:
            error_detail = f"HTTP error: {e.response.status_code}"
            if e.response.status_code == 401:
                error_detail = "Authentication failed — check the API token."
            elif e.response.status_code == 403:
                error_detail = "The API token doesn't have permission to read meal plans."
            elif e.response.status_code == 404:
                error_detail = "Meal plan endpoint not found — check the Mealie version."
            logger.error(
                f"[Mealie] HTTP error fetching meal plan: {e.response.status_code} "
                f"({e.request.method} {e.request.url})"
            )
            return {"items": [], "error": error_detail}
        except httpx.HTTPError as e:
            logger.exception(f"[Mealie] Network error fetching meal plan: {e}")
            return {"items": [], "error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.exception(f"[Mealie] Unexpected error fetching meal plan: {e}")
            return {"items": [], "error": f"Unexpected error: {str(e)}"}

    async def _reload_config_from_db(self) -> None:
        """
        Reload plugin config from database to ensure we have the latest values,
        especially the API token which might have been updated.
        """
        from app.models.db_models import PluginDB

        try:
            db_plugin = await PluginDB.objects.get_or_none(id=self.plugin_id)
            if not db_plugin or not db_plugin.config:
                return

            new_api_token = str(db_plugin.config.get("api_token") or "").strip()
            if new_api_token and new_api_token != self.api_token:
                logger.info("[Mealie] API token changed, reloading config from database")
                await self.configure(db_plugin.config)
        except Exception:
            logger.exception("[Mealie] Error reloading config from database")
            # Don't fail the request — the existing config might still work.

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Test Mealie API connection and verify API token permissions."""
        normalized = cls.normalize_config(config)
        mealie_url = str(normalized.get("mealie_url") or "").rstrip("/")
        api_token = str(normalized.get("api_token") or "").strip()
        group_id = str(normalized.get("group_id") or "").strip()

        if not mealie_url or not api_token:
            return {
                "success": False,
                "message": "Mealie URL and API token are required",
            }

        headers = {"Authorization": f"Bearer {api_token}"}
        test_results = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.info(f"[Mealie Test] Testing connection to {mealie_url}...")
                try:
                    response = await client.get(
                        f"{mealie_url}/api/users/self",
                        headers=headers,
                    )
                    if response.status_code == 200:
                        user_data = response.json()
                        username = user_data.get("username", "unknown")
                        test_results.append(f"Authentication successful (user: {username})")
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

                today = datetime.now().date()
                end_date = today + timedelta(days=7)
                meal_plan_params = {
                    "start_date": today.isoformat(),
                    "end_date": end_date.isoformat(),
                }
                if group_id:
                    meal_plan_params["group_id"] = group_id

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
                                f"Meal plan access successful ({endpoint}: {item_count} items found)"
                            )
                            break
                        if response.status_code == 404:
                            continue
                        if response.status_code == 403:
                            test_results.append(
                                "Meal plan endpoint accessible but permission denied (403)"
                            )
                            break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            continue
                        if e.response.status_code == 403:
                            test_results.append(
                                "Meal plan endpoint accessible but permission denied (403)"
                            )
                            break

                if not meal_plan_accessible:
                    test_results.append(
                        "Could not access meal plan endpoint (may not have meal plans or wrong endpoint)"
                    )

                try:
                    response = await client.get(
                        f"{mealie_url}/api/recipes",
                        headers=headers,
                        params={"perPage": 1},
                    )
                    if response.status_code == 200:
                        test_results.append("Recipes API accessible")
                except Exception:
                    pass

                if meal_plan_accessible:
                    return {
                        "success": True,
                        "message": "Connection successful!\n" + "\n".join(test_results),
                    }

                message = (
                    "Connection successful, but meal plan access failed.\n"
                    + "\n".join(test_results)
                    + "\n\nPlease verify:"
                    + "\n- API token has permission to access meal plans"
                    + "\n- Meal plans exist for the date range "
                    + f"({today.isoformat()} to {end_date.isoformat()})"
                    + "\n- Group ID is correct (if specified)"
                )
                return {"success": False, "message": message}

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
            logger.exception(f"[Mealie Test] Unexpected error: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}

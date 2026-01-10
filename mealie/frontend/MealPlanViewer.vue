<template>
  <div class="meal-plan-viewer">
    <div v-if="query.isLoading.value" class="loading-state">
      <div class="spinner" />
      <p>Loading meal plan...</p>
    </div>
    <div v-else-if="query.isError.value" class="error-state">
      <h3>⚠️ Error Loading Meal Plan</h3>
      <p>
        {{
          query.error.value?.response?.data?.detail ||
          query.error.value?.message ||
          "Failed to load meal plan"
        }}
      </p>
      <button class="btn-retry" @click="query.refetch()">Retry</button>
    </div>
    <div
      v-else-if="query.data.value"
      class="meal-plan-content"
      :class="[`card-size-${cardSize}`, { 'portrait-mode': isPortrait }]"
    >
      <div class="meal-plan-header">
        <h3>Meal Plan</h3>
        <span class="meal-plan-dates" v-if="dateRange">
          {{ dateRange }}
        </span>
      </div>
      <div
        v-if="mealPlanItems.length > 0"
        class="meal-plan-items"
        :style="gridStyle"
      >
        <div
          v-for="item in mealPlanItems"
          :key="item.id || item.date"
          class="meal-plan-item"
        >
          <div
            class="meal-plan-date"
            :class="{ today: isToday(item.date) }"
            v-if="item.date"
          >
            {{ formatDate(item.date) }}
          </div>
          <div
            class="meal-plan-meals"
            v-if="item.meals && item.meals.length > 0"
          >
            <div
              v-for="meal in item.meals"
              :key="meal.id || `${item.date}-${meal.type}`"
              class="meal-item"
              :class="{ clickable: getRecipeUrl(meal) }"
              @click="openRecipe(meal)"
            >
              <span class="meal-type">{{ formatMealType(meal.type) }}</span>
              <span class="meal-name">{{
                meal.recipeName ||
                meal.recipe?.name ||
                meal.title ||
                "No recipe"
              }}</span>
            </div>
          </div>
          <div v-else class="no-meals-day">
            <p>No meals planned</p>
          </div>
        </div>
      </div>
      <div v-else class="no-meals">
        <p>No meals planned for this week</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import axios from "axios";
import { useConfigStore } from "../../../stores/config";
import {
  logDebug,
  logWarn,
  logInfo,
  logError,
  isDebugEnabled,
} from "../../../utils/logger";

const props = defineProps({
  serviceId: {
    type: String,
    required: true,
  },
  apiEndpoint: {
    type: String,
    required: true,
  },
  debug: {
    type: Boolean,
    default: false,
  },
});

const configStore = useConfigStore();

// Enable debug mode if:
// 1. Explicitly passed as prop
// 2. Global console log level is set to 'debug'
// 3. In development mode
const DEBUG = props.debug || isDebugEnabled() || import.meta.env.DEV;

const cardSize = computed(() => configStore.mealPlanCardSize || "medium");
const isPortrait = computed(() => configStore.orientation === "portrait");

// Fetch meal plan data with Vue Query
const query = useQuery({
  queryKey: ["mealplan", props.serviceId],
  queryFn: async () => {
    const today = new Date();
    const endDate = new Date(today);
    endDate.setDate(endDate.getDate() + 7);

    const startDateStr = today.toISOString().split("T")[0];
    const endDateStr = endDate.toISOString().split("T")[0];

    if (DEBUG) {
      logDebug("[MealPlanViewer]", "Fetching meal plan data:", {
        endpoint: props.apiEndpoint,
        startDate: startDateStr,
        endDate: endDateStr,
      });
    }

    const response = await axios.get(props.apiEndpoint, {
      params: {
        start_date: startDateStr,
        end_date: endDateStr,
      },
    });

    if (DEBUG) {
      logDebug("[MealPlanViewer]", "API response status:", response.status);
      logDebug(
        "[MealPlanViewer]",
        "Full Mealie API response data:",
        JSON.parse(JSON.stringify(response.data)),
      );
      logDebug("[MealPlanViewer]", "API response summary:", {
        status: response.status,
        dataType: typeof response.data,
        isArray: Array.isArray(response.data),
        hasItems: !!response.data?.items,
        itemCount:
          response.data?.items?.length ||
          (Array.isArray(response.data) ? response.data.length : 0),
        keys: response.data ? Object.keys(response.data) : [],
        sampleItem:
          response.data?.items?.[0] ||
          (Array.isArray(response.data) ? response.data[0] : null),
      });
    }

    return response.data;
  },
  staleTime: 5 * 60 * 1000, // 5 minutes
  gcTime: 10 * 60 * 1000, // 10 minutes
  refetchInterval: 30 * 60 * 1000, // Auto-refetch every 30 minutes
  retry: 1,
});

const mealPlanItems = computed(() => {
  if (!query.data.value) {
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "No data in query.data.value");
    }
    return [];
  }

  const serviceData = query.data.value;
  if (DEBUG) {
    logDebug("[MealPlanViewer]", "Processing service data:", {
      hasItems: !!serviceData.items,
      isArray: Array.isArray(serviceData),
      hasDate: !!serviceData.date,
      keys: Object.keys(serviceData),
      fullData: JSON.parse(JSON.stringify(serviceData)),
    });
  }

  // Get raw items from response
  let rawItems = [];

  // Handle paginated response: { items: [...], total: N }
  if (serviceData.items && Array.isArray(serviceData.items)) {
    rawItems = serviceData.items;
    if (DEBUG) {
      logDebug(
        "[MealPlanViewer]",
        `Found ${rawItems.length} items in serviceData.items`,
      );
    }
  }
  // Handle direct array response: [...]
  else if (Array.isArray(serviceData)) {
    rawItems = serviceData;
    if (DEBUG) {
      logDebug(
        "[MealPlanViewer]",
        `Service data is array with ${rawItems.length} items`,
      );
    }
  }
  // Handle single item: { date: "...", meals: [...] }
  else if (serviceData.date && serviceData.meals) {
    if (DEBUG) {
      logDebug(
        "[MealPlanViewer]",
        "Single item format with date:",
        serviceData.date,
      );
    }
    // Filter out if it's a past day
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const itemDate = new Date(serviceData.date);
    itemDate.setHours(0, 0, 0, 0);
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "Date comparison:", {
        itemDate: itemDate.toISOString(),
        today: today.toISOString(),
        isPast: itemDate < today,
        isTodayOrFuture: itemDate >= today,
      });
    }
    if (itemDate >= today) {
      return [serviceData];
    }
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "Filtered out past day:", serviceData.date);
    }
    return [];
  }

  if (rawItems.length === 0) {
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "No raw items found after parsing");
    }
    return [];
  }

  if (DEBUG) {
    logDebug(`[MealPlanViewer] Processing ${rawItems.length} raw items`);
  }

  // Mealie API returns individual meal entries, not grouped by day
  // Each item has: date, entryType, title, recipe, etc.
  // We need to group by date and create a structure like:
  // [{ date: "2025-11-10", meals: [{ type: "breakfast", recipe: {...} }] }]

  // Group meals by date
  const mealsByDate = {};
  rawItems.forEach((item) => {
    const date = item.date;
    if (!date) {
      if (DEBUG) {
        logDebug("[MealPlanViewer]", "Item missing date:", item);
      }
      return;
    }

    // Normalize date string to YYYY-MM-DD format for consistent grouping
    // Parse as local date to avoid timezone issues
    let normalizedDate = date;
    try {
      // If date is in ISO format or has time component, extract just the date part
      const dateObj = new Date(date);
      if (!isNaN(dateObj.getTime())) {
        // Format as YYYY-MM-DD in local timezone
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, "0");
        const day = String(dateObj.getDate()).padStart(2, "0");
        normalizedDate = `${year}-${month}-${day}`;
      }
    } catch (e) {
      // If parsing fails, use original date string
      if (DEBUG) {
        logWarn("[MealPlanViewer]", "Failed to parse date:", date, e);
      }
    }

    if (!mealsByDate[normalizedDate]) {
      mealsByDate[normalizedDate] = {
        date: normalizedDate,
        meals: [],
      };
    }

    // Add meal entry - preserve all recipe data for URL construction
    mealsByDate[normalizedDate].meals.push({
      id: item.id,
      type: item.entryType || item.type || "meal",
      title: item.title,
      text: item.text,
      recipe: item.recipe, // Full recipe object (may contain slug, id, etc.)
      recipeId: item.recipeId, // Recipe ID from meal plan entry
      recipeName: item.recipe?.name || item.title || "No recipe",
    });
  });

  if (DEBUG) {
    logDebug(
      "[MealPlanViewer]",
      `Grouped into ${Object.keys(mealsByDate).length} dates:`,
      Object.keys(mealsByDate),
    );
    logDebug(
      "[MealPlanViewer]",
      "Meals by date:",
      JSON.parse(JSON.stringify(mealsByDate)),
    );
  }

  // Convert to array and sort by date (using Date objects for proper comparison)
  const groupedItems = Object.values(mealsByDate).sort((a, b) => {
    const dateA = new Date(a.date);
    dateA.setHours(0, 0, 0, 0);
    const dateB = new Date(b.date);
    dateB.setHours(0, 0, 0, 0);
    return dateA.getTime() - dateB.getTime();
  });

  if (DEBUG) {
    logDebug(
      "[MealPlanViewer]",
      "Grouped items after sorting:",
      groupedItems.map((i) => ({
        date: i.date,
        mealCount: i.meals.length,
      })),
    );
  }

  // Fill in missing days in the week range
  const startDate = getStartDate();
  const endDate = getEndDate();
  const allDays = [];

  // Get today's date at midnight for comparison (local time)
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (DEBUG) {
    logDebug(
      "[MealPlanViewer]",
      "Today's date for filtering:",
      today.toISOString().split("T")[0],
    );
  }

  if (startDate && endDate) {
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "Using date range:", { startDate, endDate });
    }
    const current = new Date(startDate);
    const end = new Date(endDate);

    while (current <= end) {
      // Create date object for comparison (set to midnight local time)
      const currentDate = new Date(current);
      currentDate.setHours(0, 0, 0, 0);

      // Only filter out past days (not today or future)
      // Use Date object comparison
      if (currentDate < today) {
        current.setDate(current.getDate() + 1);
        continue;
      }

      // Format date as YYYY-MM-DD in local timezone (not UTC)
      const year = current.getFullYear();
      const month = String(current.getMonth() + 1).padStart(2, "0");
      const day = String(current.getDate()).padStart(2, "0");
      const dateStr = `${year}-${month}-${day}`;

      const existingDay = groupedItems.find((item) => {
        // Compare dates using Date objects to avoid string comparison issues
        const itemDate = new Date(item.date);
        itemDate.setHours(0, 0, 0, 0);
        return itemDate.getTime() === currentDate.getTime();
      });

      if (existingDay) {
        allDays.push(existingDay);
      } else {
        // Add empty day
        allDays.push({
          date: dateStr,
          meals: [],
        });
      }

      current.setDate(current.getDate() + 1);
    }
  } else {
    // If we can't determine the range, filter grouped items to exclude past days
    if (DEBUG) {
      logDebug("[MealPlanViewer]", "No date range, filtering grouped items");
    }
    const filtered = groupedItems.filter((item) => {
      if (!item.date) return false;
      // Use Date object comparison
      const itemDate = new Date(item.date);
      itemDate.setHours(0, 0, 0, 0);
      return itemDate >= today;
    });
    if (DEBUG) {
      logDebug(
        "[MealPlanViewer]",
        `Filtered ${groupedItems.length} items to ${filtered.length} items`,
      );
      if (filtered.length < groupedItems.length) {
        const filteredOut = groupedItems.filter((item) => {
          if (!item.date) return true;
          const itemDate = new Date(item.date);
          itemDate.setHours(0, 0, 0, 0);
          return itemDate < today;
        });
        logDebug(
          "[MealPlanViewer]",
          "Filtered out dates:",
          filteredOut.map((i) => i.date),
        );
      }
    }
    return filtered;
  }

  // Filter out any past days that might have been included (use Date object comparison)
  const finalDays = allDays.filter((item) => {
    if (!item.date) return false;
    const itemDate = new Date(item.date);
    itemDate.setHours(0, 0, 0, 0);
    return itemDate >= today;
  });

  if (DEBUG) {
    logDebug(
      "[MealPlanViewer]",
      `Final result: ${finalDays.length} days (from ${allDays.length} total days)`,
    );
    logDebug(
      "[MealPlanViewer]",
      "Final meal plan items:",
      JSON.parse(JSON.stringify(finalDays)),
    );
  }
  return finalDays;
});

const getStartDate = () => {
  if (!query.data.value) return null;

  const serviceData = query.data.value;
  // Try to get from response metadata
  if (serviceData.start_date) {
    return serviceData.start_date;
  }

  // Calculate from items
  const items =
    serviceData.items || (Array.isArray(serviceData) ? serviceData : []);
  if (items.length > 0) {
    const dates = items
      .map((item) => item.date)
      .filter(Boolean)
      .sort();
    if (dates.length > 0) {
      return dates[0];
    }
  }

  // Default to today
  return new Date().toISOString().split("T")[0];
};

const getEndDate = () => {
  if (!query.data.value) return null;

  const serviceData = query.data.value;
  // Try to get from response metadata
  if (serviceData.end_date) {
    return serviceData.end_date;
  }

  // Calculate from items
  const items =
    serviceData.items || (Array.isArray(serviceData) ? serviceData : []);
  if (items.length > 0) {
    const dates = items
      .map((item) => item.date)
      .filter(Boolean)
      .sort();
    if (dates.length > 0) {
      return dates[dates.length - 1];
    }
  }

  // Default to 7 days from today
  const date = new Date();
  date.setDate(date.getDate() + 7);
  return date.toISOString().split("T")[0];
};

const dateRange = computed(() => {
  if (!query.data.value) return "";

  const serviceData = query.data.value;
  // Try to get date range from response metadata
  if (serviceData.start_date && serviceData.end_date) {
    return formatDateRange(serviceData.start_date, serviceData.end_date);
  }

  // Calculate from items if available
  const items = mealPlanItems.value;
  if (items.length > 0) {
    const dates = items
      .map((item) => item.date)
      .filter(Boolean)
      .sort();
    if (dates.length > 0) {
      return formatDateRange(dates[0], dates[dates.length - 1]);
    }
  }

  return "";
});

const getMealieUrl = () => {
  // Get mealie_url from response metadata
  if (query.data.value && query.data.value._metadata) {
    return query.data.value._metadata.mealie_url;
  }
  return null;
};

const getRecipeUrl = (meal) => {
  if (!meal) return null;

  const mealieUrl = getMealieUrl();
  if (!mealieUrl) return null;

  // Mealie recipe URLs are: {mealie_url}/g/home/r/{slug}
  let slug = null;

  if (meal.recipe) {
    // Check for slug (most common)
    if (meal.recipe.slug) {
      slug = meal.recipe.slug;
    }
    // Fallback to recipe ID if slug not available
    else if (meal.recipe.id) {
      slug = meal.recipe.id;
    }
  }

  // Fallback to recipeId from meal entry
  if (!slug && meal.recipeId) {
    slug = meal.recipeId;
  }

  if (!slug) return null;

  // Use /g/home/r/{slug} format (home is the default group view)
  return `${mealieUrl}/g/home/r/${slug}`;
};

const openRecipe = (meal) => {
  const url = getRecipeUrl(meal);
  if (url) {
    window.open(url, "_blank");
  }
};

const formatMealType = (type) => {
  if (!type) return "Meal";
  // Capitalize first letter
  return type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
};

const formatDate = (dateString) => {
  if (!dateString) return "";
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
};

const formatDateRange = (startDate, endDate) => {
  if (!startDate || !endDate) return "";
  const start = new Date(startDate);
  const end = new Date(endDate);
  return `${start.toLocaleDateString("en-US", { month: "short", day: "numeric" })} - ${end.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
};

const isToday = (dateString) => {
  if (!dateString) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(dateString);
  date.setHours(0, 0, 0, 0);
  return date.getTime() === today.getTime();
};

// Calculate grid columns for portrait mode based on number of days
const gridStyle = computed(() => {
  if (!isPortrait.value) {
    return { gridTemplateColumns: "1fr" };
  }

  const numDays = mealPlanItems.value.length;
  if (numDays <= 0) {
    return { gridTemplateColumns: "1fr" };
  }

  // For portrait mode on 24" monitor (1080px wide), use 2-3 columns
  // Calculate optimal columns: aim for roughly square-ish layout
  let columns = 2;
  if (numDays <= 4) {
    columns = 2; // 2x2 grid
  } else if (numDays <= 6) {
    columns = 2; // 2x3 grid
  } else if (numDays <= 9) {
    columns = 3; // 3x3 grid
  } else if (numDays <= 12) {
    columns = 3; // 3x4 grid
  } else {
    columns = 3; // 3 columns for more days
  }

  return {
    gridTemplateColumns: `repeat(${columns}, 1fr)`,
  };
});
</script>

<style scoped>
.meal-plan-viewer {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding: 2rem;
  height: 100%;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid var(--border-color);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error-state h3 {
  margin: 0;
  color: var(--accent-error);
}

.error-state p {
  color: var(--text-secondary);
  text-align: center;
}

.btn-retry {
  padding: 0.75rem 1.5rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-retry:hover {
  background: var(--bg-tertiary);
}

.meal-plan-content {
  width: 100%;
  height: 100%;
  padding: 1.5rem;
  overflow: hidden;
  max-height: 100%;
  background: var(--bg-primary);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

.meal-plan-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 2px solid var(--border-color);
  flex-shrink: 0;
  gap: 1rem;
}

.meal-plan-header h3 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  flex-shrink: 0;
}

.meal-plan-dates {
  font-size: 0.9rem;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.meal-plan-items {
  display: grid;
  gap: 1rem;
  width: 100%;
  min-width: 0; /* Prevent grid overflow */
  grid-template-columns: 1fr; /* Single column for landscape - full width cards */
  flex: 1;
  overflow: hidden;
  align-content: start;
}

/* Portrait mode: multi-column layout */
.meal-plan-content.portrait-mode {
  padding: 0.75rem;
}

.meal-plan-content.portrait-mode .meal-plan-header {
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
}

.meal-plan-content.portrait-mode .meal-plan-header h3 {
  font-size: 1.1rem;
}

.meal-plan-content.portrait-mode .meal-plan-dates {
  font-size: 0.8rem;
}

.meal-plan-content.portrait-mode .meal-plan-items {
  gap: 0.5rem;
  /* Grid columns set dynamically via inline style */
}

.meal-plan-content.portrait-mode .meal-plan-item {
  padding: 0.5rem;
  min-height: 0;
  border-radius: 8px;
  gap: 0.5rem;
}

.meal-plan-content.portrait-mode .meal-plan-date {
  font-size: 0.75rem;
  margin-bottom: 0.5rem;
  padding-bottom: 0.35rem;
}

.meal-plan-content.portrait-mode .meal-plan-meals {
  gap: 0.35rem;
}

.meal-plan-content.portrait-mode .meal-item {
  padding: 0.5rem 0.75rem;
  gap: 0.75rem;
}

.meal-plan-content.portrait-mode .meal-type {
  min-width: 60px;
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
}

.meal-plan-content.portrait-mode .meal-name {
  font-size: 0.85rem;
  line-height: 1.4;
}

.meal-plan-content.portrait-mode .no-meals-day,
.meal-plan-content.portrait-mode .no-meals {
  padding: 0.5rem;
  font-size: 0.8rem;
}

.meal-plan-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  transition: all 0.3s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  min-width: 0; /* Prevent flex item overflow */
  width: 100%;
  overflow: hidden;
}

.meal-plan-item:hover {
  background: var(--bg-tertiary);
  border-color: var(--accent-primary);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.meal-plan-date {
  font-weight: 700;
  font-size: 0.85rem;
  color: var(--text-primary);
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border-color);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meal-plan-date.today {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
}

.meal-plan-meals {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 0; /* Prevent flex overflow */
}

.meal-item {
  display: flex;
  gap: 1rem;
  align-items: center;
  padding: 0.75rem 1rem;
  background: var(--bg-primary);
  border-radius: 8px;
  transition: all 0.2s ease;
  border: 1px solid transparent;
  min-width: 0; /* Prevent flex item overflow */
  width: 100%;
}

.meal-item.clickable {
  cursor: pointer;
}

.meal-item.clickable:hover {
  background: var(--bg-tertiary);
  border-color: var(--accent-primary);
  transform: translateX(6px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.meal-item.clickable .meal-name {
  color: var(--accent-primary);
  font-weight: 500;
  transition: all 0.2s ease;
}

.meal-item.clickable:hover .meal-name {
  color: var(--accent-primary);
  font-weight: 600;
}

.meal-type {
  font-weight: 700;
  color: var(--accent-primary);
  min-width: 80px;
  text-transform: capitalize;
  font-size: 0.85rem;
  letter-spacing: 0.05em;
  padding: 0.35rem 0.75rem;
  background: var(--bg-tertiary);
  border-radius: 4px;
  text-align: center;
  flex-shrink: 0;
  white-space: nowrap;
}

.meal-name {
  color: var(--text-primary);
  flex: 1;
  font-size: 0.95rem;
  line-height: 1.5;
  min-width: 0; /* Allow text to shrink */
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.no-meals-day,
.no-meals {
  text-align: center;
  color: var(--text-secondary);
  padding: 1rem;
  font-style: italic;
}

/* Smaller screens */
@media (max-width: 768px) {
  .meal-plan-items {
    grid-template-columns: 1fr !important;
    gap: 0.75rem;
  }
}
</style>





<template>
  <span v-if="hasData" class="weather-statusbar">
    {{ weatherEmoji }} {{ weatherTemp }}{{ weatherUnit }}
  </span>
</template>

<script setup>
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import axios from "axios";

defineOptions({ name: "WeatherStatusbar" });

const props = defineProps({
  serviceId: {
    type: String,
    required: true,
  },
});

const weatherQuery = useQuery({
  queryKey: computed(() => ["weather_statusbar", props.serviceId]),
  queryFn: () => axios.get(`/api/plugins/${props.serviceId}/data`).then((r) => r.data),
  refetchInterval: 600000,
  staleTime: 540000,
  retry: 1,
  enabled: computed(() => !!props.serviceId),
});

const OWM_EMOJI = {
  "01": "☀️",
  "02": "⛅",
  "03": "☁️",
  "04": "☁️",
  "09": "🌧️",
  10: "🌦️",
  11: "⛈️",
  13: "❄️",
  50: "🌫️",
};

const weatherEmoji = computed(() => {
  const icon = weatherQuery.data.value?.current?.icon;
  if (!icon) return "";
  return OWM_EMOJI[icon.slice(0, 2)] ?? "🌡️";
});

const weatherTemp = computed(() => {
  const temp = weatherQuery.data.value?.current?.temperature;
  if (temp === undefined || temp === null) return null;
  return Math.round(temp);
});

const weatherUnit = computed(() => {
  const units = weatherQuery.data.value?.units || "metric";
  if (units === "imperial") return "°F";
  if (units === "kelvin") return "K";
  return "°C";
});

const hasData = computed(
  () =>
    !weatherQuery.isLoading.value &&
    !weatherQuery.isError.value &&
    weatherTemp.value !== null,
);
</script>

<style scoped>
.weather-statusbar {
  white-space: nowrap;
  font-size: 0.875rem;
  color: var(--text-secondary);
  padding: 0 0.5rem;
}
</style>

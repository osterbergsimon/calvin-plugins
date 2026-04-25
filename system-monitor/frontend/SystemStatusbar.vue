<template>
  <span v-if="hasData" class="sysmon-statusbar">
    <span class="sysmon-item">CPU {{ cpuPct }}%</span>
    <span class="sysmon-sep">·</span>
    <span class="sysmon-item">RAM {{ ramPct }}%</span>
    <template v-if="temp != null">
      <span class="sysmon-sep">·</span>
      <span class="sysmon-item" :class="tempClass">{{ temp }}°{{ tempUnit }}</span>
    </template>
  </span>
</template>

<script setup>
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import axios from "axios";

defineOptions({ name: "SystemStatusbar" });

const props = defineProps({
  serviceId: {
    type: String,
    required: true,
  },
});

const query = useQuery({
  queryKey: computed(() => ["system_monitor_statusbar", props.serviceId]),
    queryFn: () =>
      axios.get(`/api/plugins/${props.serviceId}/data`).then((r) => r.data),
  refetchInterval: 30000,
  staleTime: 25000,
  retry: 1,
});

const data = computed(() => query.data.value || {});

const cpuPct = computed(() => Math.round(data.value.cpu_percent ?? 0));
const ramPct = computed(() => Math.round(data.value.memory?.percent ?? 0));
const temp = computed(() => data.value.temperature ?? null);
const tempUnit = computed(() => data.value.temp_unit ?? "C");

const tempClass = computed(() => {
  const t = temp.value;
  if (t == null) return "";
  const celsius = tempUnit.value === "F" ? ((t - 32) * 5) / 9 : t;
  if (celsius >= 75) return "temp-hot";
  if (celsius >= 60) return "temp-warm";
  return "";
});

const hasData = computed(
  () => !query.isLoading.value && !query.isError.value && query.data.value,
);
</script>

<style scoped>
.sysmon-statusbar {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  white-space: nowrap;
  font-size: 0.875rem;
  color: var(--text-secondary);
  padding: 0 0.5rem;
}

.sysmon-sep {
  opacity: 0.4;
}

.temp-warm {
  color: var(--color-warning, #e0a84b);
}

.temp-hot {
  color: var(--color-danger, #e05c5c);
}
</style>

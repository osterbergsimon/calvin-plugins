<template>
  <div class="system-monitor">
    <div v-if="query.isLoading.value && !query.data.value" class="sm-loading">
      <div class="spinner" />
    </div>
    <div v-else-if="query.isError.value && !query.data.value" class="sm-error">
      <p>Failed to load system metrics</p>
      <button @click="query.refetch()">Retry</button>
    </div>
    <div v-else-if="query.data.value" class="sm-content">
      <div class="sm-row">
        <MetricBar label="CPU" :value="data.cpu_percent" unit="%" color="var(--color-accent)" />
        <MetricBar label="RAM" :value="data.memory?.percent" unit="%" color="var(--color-secondary, #7c6af7)" />
      </div>
      <div class="sm-row">
        <MetricBar label="Disk" :value="data.disk?.percent" unit="%" color="var(--color-warning, #e0a84b)" />
        <div v-if="data.temperature != null" class="sm-metric sm-temp">
          <span class="sm-label">Temp</span>
          <span class="sm-value" :class="tempClass">
            {{ data.temperature }}°{{ data.temp_unit || 'C' }}
          </span>
        </div>
      </div>
      <div v-if="data.network" class="sm-network">
        <span class="sm-net-item">↑ {{ data.network.sent_kbps }} KB/s</span>
        <span class="sm-net-item">↓ {{ data.network.recv_kbps }} KB/s</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h } from "vue";
import { useQuery } from "@tanstack/vue-query";
import axios from "axios";

const props = defineProps({
  serviceId: { type: String, required: true },
  apiEndpoint: { type: String, required: true },
});

// Poll every 5 seconds for live metrics
const query = useQuery({
  queryKey: ["system_monitor", props.serviceId],
  queryFn: () => axios.get(props.apiEndpoint).then((r) => r.data),
  refetchInterval: 5000,
  staleTime: 4000,
});

const data = computed(() => query.data.value || {});

const tempClass = computed(() => {
  const t = data.value.temperature;
  const unit = data.value.temp_unit;
  if (t == null) return "";
  const celsius = unit === "F" ? ((t - 32) * 5) / 9 : t;
  if (celsius >= 75) return "temp-hot";
  if (celsius >= 60) return "temp-warm";
  return "temp-ok";
});

// Inline MetricBar component so the plugin is self-contained
const MetricBar = defineComponent({
  props: {
    label: String,
    value: Number,
    unit: { type: String, default: "%" },
    color: { type: String, default: "var(--color-accent)" },
  },
  setup(p) {
    return () => {
      const pct = Math.min(100, Math.max(0, p.value ?? 0));
      return h("div", { class: "sm-metric sm-bar-metric" }, [
        h("span", { class: "sm-label" }, p.label),
        h("div", { class: "sm-bar-track" }, [
          h("div", {
            class: "sm-bar-fill",
            style: { width: pct + "%", background: p.color },
          }),
        ]),
        h("span", { class: "sm-value" }, `${Math.round(pct)}${p.unit}`),
      ]);
    };
  },
});
</script>

<style scoped>
.system-monitor {
  padding: 0.75rem 1rem;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--color-text, #e0e0e0);
}

.sm-loading,
.sm-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  opacity: 0.6;
}

.sm-content {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.sm-row {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.sm-metric {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.sm-bar-metric {
  flex: 1;
  gap: 0.4rem;
}

.sm-label {
  min-width: 2.8rem;
  font-size: 0.75rem;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sm-bar-track {
  flex: 1;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.sm-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.sm-value {
  min-width: 3rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 0.8rem;
}

.sm-temp {
  justify-content: flex-end;
}

.temp-ok  { color: var(--color-success, #5cb85c); }
.temp-warm { color: var(--color-warning, #e0a84b); }
.temp-hot  { color: var(--color-danger, #e05c5c); }

.sm-network {
  display: flex;
  gap: 1rem;
  opacity: 0.65;
  font-size: 0.75rem;
  justify-content: flex-end;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255,255,255,0.2);
  border-top-color: var(--color-accent, #fff);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>

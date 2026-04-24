<template>
  <div class="now-playing">
    <div v-if="query.isLoading.value && !query.data.value" class="np-idle">
      <div class="spinner" />
    </div>

    <div v-else-if="state === 'idle' || state === 'no_devices'" class="np-idle">
      <div class="np-idle-icon">📺</div>
      <span class="np-idle-text">{{ deviceName || 'Chromecast' }} — nothing casting</span>
    </div>

    <div v-else-if="state === 'error'" class="np-idle">
      <span class="np-idle-text">{{ data.error }}</span>
    </div>

    <div v-else class="np-active">
      <img v-if="data.album_art_url" class="np-art" :src="data.album_art_url" alt="" />
      <div v-else class="np-art-placeholder">{{ appIcon }}</div>

      <div class="np-overlay">
        <div class="np-app">{{ data.app_name }}</div>
        <div class="np-title" :title="data.title">{{ data.title || '—' }}</div>
        <div v-if="data.artist" class="np-artist">{{ data.artist }}</div>
        <div v-if="data.duration" class="np-progress">
          <div class="np-bar-track">
            <div class="np-bar-fill" :style="{ width: progressPct + '%' }" />
          </div>
          <span class="np-time">{{ formatTime(data.current_time) }} / {{ formatTime(data.duration) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import axios from "axios";

const props = defineProps({
  serviceId: { type: String, required: true },
  apiEndpoint: { type: String, required: true },
});

const query = useQuery({
  queryKey: ["chromecast", props.serviceId],
  queryFn: () => axios.get(props.apiEndpoint).then((r) => r.data),
  refetchInterval: 10000,
  staleTime: 8000,
});

const data = computed(() => query.data.value || {});
const state = computed(() => data.value.state || "idle");
const deviceName = computed(() => data.value.device_name || "");

const progressPct = computed(() => {
  const { current_time, duration } = data.value;
  if (!duration || !current_time) return 0;
  return Math.min(100, (current_time / duration) * 100);
});

const appIcon = computed(() => {
  const app = (data.value.app_name || "").toLowerCase();
  if (app.includes("youtube")) return "▶";
  if (app.includes("spotify")) return "♫";
  if (app.includes("netflix")) return "N";
  if (app.includes("plex")) return "▶";
  return "📺";
});

function formatTime(secs) {
  if (!secs) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
</script>

<style scoped>
.now-playing {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: #fff;
  font-size: 0.85rem;
}

/* ── idle / error ── */
.np-idle {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  opacity: 0.5;
  padding: 0.75rem 1rem;
}
.np-idle-icon { font-size: 1.5rem; }
.np-idle-text  { font-size: 0.8rem; }

/* ── active ── */
.np-active {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.np-art {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.np-art-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 3rem;
  background: rgba(255, 255, 255, 0.06);
}

/* gradient overlay + content pinned to bottom */
.np-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 2rem 0.9rem 0.75rem;
  background: linear-gradient(to bottom, transparent, rgba(0, 0, 0, 0.82));
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.np-app {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  opacity: 0.6;
}

.np-title {
  font-size: 1rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}

.np-artist {
  font-size: 0.8rem;
  opacity: 0.8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.np-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.35rem;
}

.np-bar-track {
  flex: 1;
  height: 3px;
  background: rgba(255, 255, 255, 0.25);
  border-radius: 2px;
  overflow: hidden;
}

.np-bar-fill {
  height: 100%;
  background: #fff;
  border-radius: 2px;
  transition: width 1s linear;
}

.np-time {
  font-size: 0.65rem;
  opacity: 0.55;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ── spinner ── */
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.15);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

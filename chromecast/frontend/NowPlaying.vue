<template>
  <div class="now-playing">
    <div v-if="query.isLoading.value && !query.data.value" class="np-idle">
      <div class="spinner" />
    </div>

    <!-- Nothing casting -->
    <div v-else-if="state === 'idle' || state === 'no_devices'" class="np-idle">
      <div class="np-idle-icon">📺</div>
      <span class="np-idle-text">{{ deviceName || 'Chromecast' }} — nothing casting</span>
    </div>

    <!-- Error -->
    <div v-else-if="state === 'error'" class="np-idle">
      <span class="np-idle-text">{{ data.error }}</span>
    </div>

    <!-- Active media -->
    <div v-else class="np-active">
      <img
        v-if="data.album_art_url"
        class="np-art"
        :src="data.album_art_url"
        alt="Album art"
      />
      <div v-else class="np-art-placeholder">
        <span>{{ appIcon }}</span>
      </div>
      <div class="np-info">
        <div class="np-app">{{ data.app_name }}</div>
        <div class="np-title" :title="data.title">{{ data.title || '—' }}</div>
        <div v-if="data.artist" class="np-artist">{{ data.artist }}</div>
        <div v-if="data.album" class="np-album">{{ data.album }}</div>
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
  padding: 0.75rem 1rem;
  color: var(--color-text, #e0e0e0);
  font-size: 0.85rem;
}

.np-idle {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  opacity: 0.5;
  width: 100%;
  justify-content: center;
}

.np-idle-icon { font-size: 1.5rem; }
.np-idle-text { font-size: 0.8rem; }

.np-active {
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  overflow: hidden;
}

.np-art {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 6px;
  flex-shrink: 0;
}

.np-art-placeholder {
  width: 72px;
  height: 72px;
  border-radius: 6px;
  background: rgba(255,255,255,0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  flex-shrink: 0;
}

.np-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.np-app {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  opacity: 0.5;
}

.np-title {
  font-size: 1rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.np-artist, .np-album {
  font-size: 0.8rem;
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.np-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.25rem;
}

.np-bar-track {
  flex: 1;
  height: 3px;
  background: rgba(255,255,255,0.15);
  border-radius: 2px;
  overflow: hidden;
}

.np-bar-fill {
  height: 100%;
  background: var(--color-accent, #fff);
  border-radius: 2px;
  transition: width 1s linear;
}

.np-time {
  font-size: 0.7rem;
  opacity: 0.5;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.15);
  border-top-color: var(--color-accent, #fff);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>

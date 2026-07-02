/**
 * <calvin-chromecast-now-playing> — the Chromecast plugin's display artifact.
 *
 * Hand-written, dependency-free ES module (no build step). Calvin's
 * WebComponentHost imports it from /api/plugins/{plugin_id}/static/dist.js,
 * requires `customElements.get("calvin-chromecast-now-playing")` after the
 * import, mounts the element, and pushes each poll of
 * /api/plugins/{plugin_id}/data onto the element's `data` property — so the
 * component re-renders inside `set data(value)` and never fetches anything
 * itself.
 *
 * Expected `data` payload (produced by plugin.py `fetch()`):
 *
 *   {
 *     state: "no_devices" | "device_not_found" | "idle" | "error"
 *            | "<player state, lowercased>",   // "playing" | "paused" | "buffering"
 *     device_name?: string,        // friendly name of the cast device
 *     app_name?: string,           // e.g. "Spotify"
 *     app_id?: string,
 *     title?: string,              // media title (active states only)
 *     artist?: string,
 *     album?: string,
 *     album_art_url?: string,      // cover artwork
 *     duration?: number,           // seconds
 *     current_time?: number,       // seconds
 *     error?: string,              // state === "error"
 *     available_devices?: string[] // state === "device_not_found"
 *   }
 *
 * Theming: the component uses shadow DOM, so Calvin's `.calvin-plugin-*`
 * classes can't reach it — instead the styles below consume the shell's CSS
 * custom properties (--ink, --ink-2, --ink-3, --bg-2, --line, --font-ui,
 * --font-data, --plugin-*), which DO inherit across the shadow boundary, so
 * the widget follows the active theme automatically.
 */

// Everything browser-only lives behind this guard so the module can be
// imported (parsed and executed) outside a browser — e.g. a Node syntax
// check — without throwing on missing DOM globals.
if (typeof customElements !== "undefined" && typeof HTMLElement !== "undefined") {
  const STYLES = `
    :host {
      display: block;
      width: 100%;
      height: 100%;
      font-family: var(--font-ui, system-ui, sans-serif);
      font-size: 0.85rem;
      color: var(--ink, #e0e0e0);
    }

    .np {
      position: relative;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }

    /* -- quiet states: loading / idle / error ------------------------------ */
    .np-quiet {
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      color: var(--ink-3, #9a9a9a);
      text-align: center;
    }
    .np-quiet-icon { font-size: 1.5rem; line-height: 1; }
    .np-quiet-text { font-size: 0.8rem; }

    /* -- active: artwork + gradient overlay ------------------------------- */
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
      color: var(--ink-2, #c0c0c0);
      background: var(--bg-2, rgba(255, 255, 255, 0.06));
    }

    /* content pinned to the bottom over a legibility gradient; the gradient
       is over artwork, so it stays black-based in every theme */
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
      color: #fff;
    }

    .np-app {
      font-size: 0.65rem;
      font-weight: 600;
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
      background: var(--line, rgba(255, 255, 255, 0.25));
      border-radius: 2px;
      overflow: hidden;
    }

    .np-bar-fill {
      height: 100%;
      background: currentColor;
      border-radius: 2px;
    }

    .np-time {
      font-family: var(--font-data, inherit);
      font-variant-numeric: tabular-nums;
      font-size: 0.65rem;
      opacity: 0.55;
      white-space: nowrap;
    }
  `;

  const esc = value =>
    String(value ?? "").replace(
      /[&<>"']/g,
      ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
    );

  const formatTime = secs => {
    if (!secs || !Number.isFinite(secs)) return "0:00";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const appIcon = appName => {
    const app = String(appName || "").toLowerCase();
    if (app.includes("youtube")) return "▶";
    if (app.includes("spotify")) return "♫";
    if (app.includes("netflix")) return "N";
    if (app.includes("plex")) return "▶";
    return "📺";
  };

  class ChromecastNowPlaying extends HTMLElement {
    #data = null;

    constructor() {
      super();
      this.attachShadow({ mode: "open" });
    }

    connectedCallback() {
      this.#render();
    }

    /** The host assigns each polled payload here; re-render on every set. */
    set data(value) {
      this.#data = value;
      this.#render();
    }

    get data() {
      return this.#data;
    }

    #render() {
      if (!this.shadowRoot) return;
      this.shadowRoot.innerHTML = `<style>${STYLES}</style><div class="np">${this.#body()}</div>`;
    }

    #body() {
      const d = this.#data;
      if (!d) {
        return `<div class="np-quiet"><span class="np-quiet-text">Loading…</span></div>`;
      }

      const state = d.state || "idle";

      if (state === "error") {
        return `<div class="np-quiet"><span class="np-quiet-text">${esc(d.error || "Chromecast error")}</span></div>`;
      }

      if (state === "device_not_found") {
        const names = (d.available_devices || []).join(", ");
        return `<div class="np-quiet"><span class="np-quiet-text">Device not found${
          names ? ` — found: ${esc(names)}` : ""
        }</span></div>`;
      }

      if (state === "idle" || state === "no_devices") {
        return `
          <div class="np-quiet">
            <span class="np-quiet-icon">📺</span>
            <span class="np-quiet-text">${esc(d.device_name || "Chromecast")} — nothing casting</span>
          </div>`;
      }

      // Active states: playing / paused / buffering
      const art = d.album_art_url
        ? `<img class="np-art" src="${esc(d.album_art_url)}" alt="" />`
        : `<div class="np-art-placeholder">${esc(appIcon(d.app_name))}</div>`;

      const app = esc(d.app_name || "") + (state === "paused" ? " · paused" : "");

      const progress = d.duration
        ? `
          <div class="np-progress">
            <div class="np-bar-track">
              <div class="np-bar-fill" style="width: ${Math.min(
                100,
                ((d.current_time || 0) / d.duration) * 100
              )}%"></div>
            </div>
            <span class="np-time">${formatTime(d.current_time)} / ${formatTime(d.duration)}</span>
          </div>`
        : "";

      return `
        ${art}
        <div class="np-overlay">
          <div class="np-app">${app}</div>
          <div class="np-title" title="${esc(d.title || "")}">${esc(d.title) || "—"}</div>
          ${d.artist ? `<div class="np-artist">${esc(d.artist)}</div>` : ""}
          ${progress}
        </div>`;
    }
  }

  if (!customElements.get("calvin-chromecast-now-playing")) {
    customElements.define("calvin-chromecast-now-playing", ChromecastNowPlaying);
  }
}

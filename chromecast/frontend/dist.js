class CalvinChromecastNowPlaying extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = {};
  }
  set data(value) {
    this._data = value || {};
    this.render();
  }
  get data() {
    return this._data;
  }
  connectedCallback() {
    this.render();
  }
  get appIcon() {
    const app = String(this._data.app_name || "").toLowerCase();
    if (app.includes("youtube")) return "YT";
    if (app.includes("spotify")) return "S";
    if (app.includes("netflix")) return "N";
    if (app.includes("plex")) return "P";
    return "TV";
  }
  get progressPct() {
    const current = Number(this._data.current_time || 0);
    const duration = Number(this._data.duration || 0);
    if (!duration || !current) return 0;
    return Math.min(100, current / duration * 100);
  }
  formatTime(value) {
    const secs = Number(value || 0);
    const mins = Math.floor(secs / 60);
    const rest = Math.floor(secs % 60);
    return `${mins}:${String(rest).padStart(2, "0")}`;
  }
  escape(value) {
    return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  renderIdle(message, icon = "TV") {
    return `
      <div class="np-idle">
        <div class="np-idle-icon">${this.escape(icon)}</div>
        <span class="np-idle-text">${this.escape(message)}</span>
      </div>
    `;
  }
  renderActive() {
    const data = this._data;
    const art = data.album_art_url ? `<img class="np-art" src="${this.escape(data.album_art_url)}" alt="">` : `<div class="np-art-placeholder">${this.escape(this.appIcon)}</div>`;
    const artist = data.artist ? `<div class="np-artist">${this.escape(data.artist)}</div>` : "";
    const progress = data.duration ? `
        <div class="np-progress">
          <div class="np-bar-track">
            <div class="np-bar-fill" style="width: ${this.progressPct}%"></div>
          </div>
          <span class="np-time">${this.formatTime(data.current_time)} / ${this.formatTime(data.duration)}</span>
        </div>
      ` : "";
    return `
      <div class="np-active">
        ${art}
        <div class="np-overlay">
          <div class="np-app">${this.escape(data.app_name || "")}</div>
          <div class="np-title" title="${this.escape(data.title || "")}">${this.escape(data.title || "-")}</div>
          ${artist}
          ${progress}
        </div>
      </div>
    `;
  }
  renderBody() {
    const state = this._data.state || "idle";
    const deviceName = this._data.device_name || "Chromecast";
    if (state === "error") {
      return this.renderIdle(this._data.error || "Unable to read cast status");
    }
    if (state === "no_devices") {
      return this.renderIdle("No Chromecasts found");
    }
    if (state === "device_not_found") {
      const available = Array.isArray(this._data.available_devices) ? this._data.available_devices.join(", ") : "No matching device discovered";
      return this.renderIdle(`${deviceName} not found. ${available}`);
    }
    if (state === "idle") {
      return this.renderIdle(`${deviceName} - nothing casting`);
    }
    return this.renderActive();
  }
  render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          height: 100%;
          color: #fff;
          font-size: 0.85rem;
        }

        .now-playing {
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          background: rgba(255, 255, 255, 0.04);
        }

        .np-idle {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          opacity: 0.62;
          padding: 0.75rem 1rem;
          color: var(--text-secondary, #d8d8d8);
        }

        .np-idle-icon {
          font-size: 1.5rem;
        }

        .np-idle-text {
          font-size: 0.8rem;
        }

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
      </style>
      <div class="now-playing">${this.renderBody()}</div>
    `;
  }
}
if (!customElements.get("calvin-chromecast-now-playing")) {
  customElements.define("calvin-chromecast-now-playing", CalvinChromecastNowPlaying);
}

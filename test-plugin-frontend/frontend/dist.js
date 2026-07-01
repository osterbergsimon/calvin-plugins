// Minimal hand-written web-component fixture for the Calvin escape hatch.
// The host imports this module from /api/plugins/{plugin_id}/static/dist.js,
// mounts <calvin-test-frontend>, and assigns the plugin's fetch() payload to
// the element's `data` property.
class CalvinTestFrontend extends HTMLElement {
  set data(value) {
    // Render the payload as plain text — just enough to prove the wiring.
    this.textContent = value && value.message ? value.message : "no data";
  }
}

if (!customElements.get("calvin-test-frontend")) {
  customElements.define("calvin-test-frontend", CalvinTestFrontend);
}

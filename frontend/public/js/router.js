import { overlayRoot, state, currentRoute, hooks } from "./shared.js";
import { renderCheck, renderReview } from "./check.js";
import { renderDocuments } from "./documents.js";
import { renderApiSpecs } from "./api-specs.js";
import { renderGuides } from "./guides.js";
import { renderScreenshots } from "./screenshots.js";
import { renderWatch, stopWatchPoll } from "./watch.js";
import { renderHistory } from "./history.js";
import { renderSettings } from "./settings.js";
import { renderUsers } from "./users.js";
import { renderHealth } from "./health.js";
import { renderInsights } from "./insights.js";

const renderers = {
  check: renderCheck,
  review: renderReview,
  documents: renderDocuments,
  watch: renderWatch,
  api: renderApiSpecs,
  guides: renderGuides,
  screenshots: renderScreenshots,
  history: renderHistory,
  insights: renderInsights,
  settings: renderSettings,
  users: renderUsers,
  health: renderHealth,
};

export function renderApp() {
  overlayRoot.innerHTML = "";
  document.body.classList.remove("has-modal");
  document.querySelector("#app").inert = false;
  state.route = currentRoute();
  if (state.route !== "screenshots") {
    state.pasteCleanup?.();
    state.pasteCleanup = null;
  }
  if (state.route !== "watch") stopWatchPoll();
  renderers[state.route]?.();
}

export function rerender() {
  hooks.renderApp();
}

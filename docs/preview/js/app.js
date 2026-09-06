import {
  overlayRoot, state, api, showError, hooks,
  isPreview, previewFixtures, THEME_KEY, applyTheme,
  currentLocale, loadLocale,
} from "./shared.js";
import { renderReview, selectIssue, visibleIssues, demoReport } from "./check.js";
import { renderLogin, loadInitialData } from "./auth.js";
import { renderApp } from "./router.js";
import { bindShell } from "./shell.js";

hooks.bindShell = bindShell;
hooks.renderApp = renderApp;

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && overlayRoot.innerHTML) {
    overlayRoot.querySelector(".overlay-backdrop")?.click();
    return;
  }
  if (state.route !== "review" || overlayRoot.innerHTML || /input|textarea|select/i.test(document.activeElement.tagName)) return;
  const issues = visibleIssues();
  if (event.key.toLowerCase() === "j") {
    selectIssue(state.activeIssue + 1, { focus: true });
  } else if (event.key.toLowerCase() === "k") {
    selectIssue(state.activeIssue - 1, { focus: true });
  } else if (event.key.toLowerCase() === "h" && issues[state.activeIssue]) {
    state.hiddenIssues.add(issues[state.activeIssue].id);
    renderReview();
  }
});

window.addEventListener("hashchange", () => {
  if (state.user) {
    state.accountOpen = false;
    renderApp();
  }
});

export async function init() {
  await loadLocale(currentLocale());

  if (isPreview) {
    state.user = { username: "preview", role: "admin", source: "local" };
    state.features = { documents: true, api: true, watch: true, screenshots: true };
    state.config = { oidc: false, docs: false, version: "0.1.0" };
    state.currentReport = demoReport();
    state.guides = previewFixtures.guides;
    state.guide = previewFixtures.guide;
    state.selectedGuide = "preview";
    document.title = "Peter View. Превью";
    if (!window.location.hash) {
      const query = /(?:^|\/)preview(?:\/|$)/.test(window.location.pathname)
        ? window.location.search
        : "?preview=1";
      history.replaceState(null, "", `${window.location.pathname}${query}#/check`);
    }
    const { refreshWatchBadge } = await import("./watch.js");
    refreshWatchBadge(previewFixtures.watchGroups);
    applyTheme(localStorage.getItem(THEME_KEY) || "light");
    state.themeMotionReady = true;
    renderApp();
    return;
  }
  try {
    state.user = await api("/api/auth/me");
    await loadInitialData();
    if (!window.location.hash) history.replaceState(null, "", "#/check");
    renderApp();
  } catch (error) {
    if (error.status !== 401) showError(error);
    try { state.config = await api("/api/config"); } catch { /* offline */ }
    applyTheme(localStorage.getItem(THEME_KEY) || "light");
    state.themeMotionReady = true;
    renderLogin();
  }
}

init();

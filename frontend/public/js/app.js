import {
  app, overlayRoot, state, api, icon, escapeHTML, initials, toast, showError,
  modal, setBusy, t, hooks, isPreview, previewFixtures, THEME_KEY, applyTheme,
  currentRoute, refreshHealthSignal, getTheme, themeToggleLabel, flipTheme,
  setLocale, currentLocale, loadLocale,
} from "./shared.js";
import { renderCheck, renderReview, exportReport, selectIssue, visibleIssues, normalizedIssues, demoReport } from "./check.js";
import { renderDocuments } from "./documents.js";
import { renderApiSpecs } from "./api-specs.js";
import { renderGuides } from "./guides.js";
import { renderScreenshots } from "./screenshots.js";
import { renderWatch, refreshWatchBadge, stopWatchPoll } from "./watch.js";
import { renderHistory } from "./history.js";
import { renderSettings } from "./settings.js";
import { renderUsers } from "./users.js";
import { renderHealth } from "./health.js";
import { renderInsights } from "./insights.js";
export function renderLogin(error = "") {
  app.innerHTML = `
    <main class="login-page">
      <div class="login-atmosphere" aria-hidden="true"></div>
      <form id="login-form" class="login-form">
        <div class="login-logo"><img src="logo.png" width="40" height="40" alt=""><strong>Peter View</strong></div>
        <h1>${t("login.title")}</h1>
        ${error ? `<div class="login-error" role="alert">${escapeHTML(error)}</div>` : ""}
        <label class="field"><span>${t("login.username")}</span><input name="username" autocomplete="username" required spellcheck="false"></label>
        <label class="field"><span>${t("login.password")}</span><span class="password-field"><input name="password" type="password" autocomplete="current-password" required><button class="icon-button password-toggle" type="button" aria-label="${t("login.showPassword")}">${icon("icon-eye")}</button></span></label>
        <button class="button primary login-submit" type="submit">${t("login.submit")}</button>
        ${state.config?.oidc ? `<a class="button secondary" href="/api/auth/oidc/start">${t("login.oidc")}</a>` : ""}
      </form>
    </main>`;
  const form = document.querySelector("#login-form");
  const password = form.elements.password;
  form.elements.username.focus();
  form.querySelector(".password-toggle").addEventListener("click", (event) => {
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    event.currentTarget.setAttribute("aria-label", visible ? "Показать пароль" : "Скрыть пароль");
    event.currentTarget.innerHTML = icon(visible ? "icon-eye" : "icon-eye-off");
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("[type=submit]");
    setBusy(button, true, "Вход…");
    try {
      state.user = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: form.elements.username.value.trim(),
          password: form.elements.password.value,
        }),
      });
      await loadInitialData();
      renderApp();
    } catch (loginError) {
      renderLogin(loginError.message);
      document.querySelector("#login-form input")?.focus();
    }
  });
}

export async function loadInitialData() {
  try {
    const data = await api("/api/styleguides");
    state.guides = data.styleguides || [];
    state.selectedGuide = data.selected || "";
  } catch {
    state.guides = [];
  }
  try {
    const cfg = await api("/api/config");
    state.features = { ...state.features, ...(cfg.features || {}) };
    state.config = cfg;
  } catch {
    state.features = { documents: false, api: false, watch: false, screenshots: false };
  }
  applyTheme(localStorage.getItem(THEME_KEY) || "light");
  state.themeMotionReady = true;
  refreshWatchBadge();
}





export function bindShell() {
  state.accountCleanup?.();
  state.accountCleanup = null;
  document.querySelector(".mobile-menu")?.addEventListener("click", () => document.querySelector(".sidebar").classList.add("open"));
  document.querySelector(".sidebar-close")?.addEventListener("click", () => document.querySelector(".sidebar").classList.remove("open"));
  document.querySelector(".account-button")?.addEventListener("click", () => {
    state.accountOpen = !state.accountOpen;
    renderApp();
  });
  document.querySelector('[data-account-action="logout"]')?.addEventListener("click", logout);
  document.querySelector('[data-account-action="password"]')?.addEventListener("click", showPasswordDialog);
  document.querySelector('[data-account-action="lang"]')?.addEventListener("click", async () => {
    await setLocale(currentLocale() === "ru" ? "en" : "ru");
    renderApp();
  });
  document.querySelector('[data-account-action="theme"]')?.addEventListener("click", (event) => {
    event.stopPropagation();
    state.themeFlipFocus = true;
    flipTheme();
    renderApp();
  });
  document.querySelector(".export-report")?.addEventListener("click", exportReport);
  refreshHealthSignal();
  if (state.accountOpen) {
    const closeAccount = () => {
      state.accountOpen = false;
      renderApp();
    };
    const onPointerDown = (event) => {
      if (!event.target.closest(".account-menu, .account-button")) closeAccount();
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") closeAccount();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    state.accountCleanup = () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
    window.requestAnimationFrame(() => {
      const focusSel = state.themeFlipFocus ? '[data-account-action="theme"]' : '.account-menu [role="menuitem"]';
      state.themeFlipFocus = false;
      document.querySelector(focusSel)?.focus();
    });
  }
}



export async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  } finally {
    state.user = null;
    state.accountOpen = false;
    renderLogin();
  }
}

export function showPasswordDialog() {
  state.accountOpen = false;
  modal({
    title: "Смена пароля",
    body: `<form class="dialog-body password-form">
      <label class="field"><span>Текущий пароль</span><input name="current_password" type="password" autocomplete="current-password" required></label>
      <label class="field"><span>Новый пароль</span><input name="new_password" type="password" autocomplete="new-password" minlength="8" required></label>
      <div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить пароль</button></div>
    </form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector("[type=submit]");
        setBusy(button, true);
        try {
          await api("/api/auth/change-password", {
            method: "POST",
            body: JSON.stringify({
              current_password: form.elements.current_password.value,
              new_password: form.elements.new_password.value,
            }),
          });
          close();
          toast("Пароль изменён");
        } catch (error) {
          showError(error);
          setBusy(button, false);
        }
      });
    },
  });
}

export function renderApp() {
  overlayRoot.innerHTML = "";
  document.body.classList.remove("has-modal");
  app.inert = false;
  state.route = currentRoute();
  if (state.route !== "screenshots") {
    state.pasteCleanup?.();
    state.pasteCleanup = null;
  }
  if (state.route !== "watch") stopWatchPoll();
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
  renderers[state.route]?.();
}

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
    const all = normalizedIssues();
    const actualIndex = all.findIndex((item) => item.id === issues[state.activeIssue].id);
    state.hiddenIssues.add(actualIndex);
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

hooks.bindShell = bindShell;
hooks.renderApp = renderApp;

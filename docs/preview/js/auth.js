import {
  app, state, api, icon, escapeHTML, setBusy, toast, showError, modal, t,
  hooks, THEME_KEY, applyTheme,
} from "./shared.js";
import { refreshWatchBadge } from "./watch.js";

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
      hooks.renderApp();
    } catch (loginError) {
      renderLogin(loginError.message);
      document.querySelector("#login-form input")?.focus();
    }
  });
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
  hooks.renderApp();
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

import { state, setLocale, currentLocale, flipTheme, refreshHealthSignal, hooks } from "./shared.js";
import { exportReport } from "./check.js";
import { logout, showPasswordDialog } from "./auth.js";

export function bindShell() {
  state.accountCleanup?.();
  state.accountCleanup = null;
  document.querySelector(".mobile-menu")?.addEventListener("click", () => document.querySelector(".sidebar").classList.add("open"));
  document.querySelector(".sidebar-close")?.addEventListener("click", () => document.querySelector(".sidebar").classList.remove("open"));
  document.querySelector(".account-button")?.addEventListener("click", () => {
    state.accountOpen = !state.accountOpen;
    hooks.renderApp();
  });
  document.querySelector('[data-account-action="logout"]')?.addEventListener("click", logout);
  document.querySelector('[data-account-action="password"]')?.addEventListener("click", showPasswordDialog);
  document.querySelector('[data-account-action="lang"]')?.addEventListener("click", async () => {
    await setLocale(currentLocale() === "ru" ? "en" : "ru");
    hooks.renderApp();
  });
  document.querySelector('[data-account-action="theme"]')?.addEventListener("click", (event) => {
    event.stopPropagation();
    state.themeFlipFocus = true;
    flipTheme();
    hooks.renderApp();
  });
  document.querySelector(".export-report")?.addEventListener("click", exportReport);
  refreshHealthSignal();
  if (state.accountOpen) {
    const closeAccount = () => {
      state.accountOpen = false;
      hooks.renderApp();
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

import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderHistory() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let data = { items: [], total: 0 };
  try { data = await api("/api/checks/history?limit=50&offset=0"); } catch (error) { showError(error); }
  if (state.route !== "history") return;
  const items = data.items || [];
  renderShell(`
    <div class="page">
      <section class="panel fill-panel">
        ${items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Источник</th><th>Дата</th><th>Находки</th><th>Style Guide</th><th></th></tr></thead><tbody>${items.map((item) => `<tr><td><strong>${escapeHTML(item.source || item.filename || "Текст")}</strong><small>${item.errors !== undefined ? `${item.errors || 0} ошибок · ${item.warnings || 0} замечаний · ${item.suggestions || 0} советов` : escapeHTML(item.type || "")}</small></td><td>${formatDate(item.created_at || item.timestamp || item.ts)}</td><td class="number">${item.issue_count ?? item.total ?? 0}</td><td>${escapeHTML(item.styleguide_name || "")}</td><td><button class="icon-button row-action" type="button" data-history-id="${escapeHTML(item.id)}" aria-label="Открыть результат">${icon("icon-arrow")}</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-state">${icon("icon-clock")}<div><h3>История пуста</h3><p>Завершённые проверки появятся здесь.</p><button class="button primary" type="button" data-go="check">Начать вычитку</button></div></div>`}
      </section>
    </div>`);
  document.querySelector("[data-go=check]")?.addEventListener("click", () => go("check"));
  document.querySelectorAll("[data-history-id]").forEach((button) => button.addEventListener("click", async () => {
    try {
      state.currentReport = await api(`/api/checks/history/${encodeURIComponent(button.dataset.historyId)}`);
      go("review");
    } catch (error) { showError(error); }
  }));
}







import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderHealth() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let data = {};
  try { data = await api("/api/health/full"); } catch (error) { showError(error); }
  if (state.route !== "health") return;
  state.health = data;
  state.healthAt = Date.now();
  const disk = data.disk || {};
  renderShell(`
    <div class="page">
      <div class="page-actions"><button class="button secondary refresh-health" type="button">${icon("icon-refresh")}Обновить</button></div>
      <div class="stat-strip">
        <div class="stat"><strong>${formatBytes(disk.used || 0)}</strong><span>занято на диске</span></div>
        <div class="stat"><strong>${formatBytes(disk.free || 0)}</strong><span>свободно</span></div>
        <div class="stat"><strong>${new Intl.NumberFormat("ru-RU").format(data.tokens?.total?.tokens ?? data.tokens?.total ?? data.tokens ?? 0)}</strong><span>токенов</span></div>
        <div class="stat"><strong>${new Intl.NumberFormat("ru-RU").format(data.repo?.doc_count ?? data.repo?.documents ?? 0)}</strong><span>документов</span></div>
      </div>
      <div class="health-grid">
        ${healthRow("LLM", data.llm)}
        ${healthRow("Эмбеддинги", data.embedding)}
        ${healthRow("Репозиторий", data.repo || { ok: false })}
        ${healthRow("Резервная копия", data.backup ? { ...data.backup, detail: data.backup.detail || formatDate(data.backup.created_at || data.backup.timestamp) } : { ok: false })}
      </div>
      ${data.audit?.length ? `<section class="panel"><h3>Журнал</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th></tr></thead><tbody>${data.audit.slice(0, 30).map((row) => `<tr><td>${escapeHTML(formatDate(row.ts))}</td><td>${escapeHTML(row.user || "")}</td><td>${escapeHTML(row.action)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
    </div>`);
  document.querySelector(".refresh-health").addEventListener("click", renderHealth);
}

export function healthRow(label, status = {}) {
  const ok = status.ok !== false && !status.error;
  return `<div class="health-row"><span class="health-icon">${icon(ok ? "icon-check" : "icon-close")}</span><div><strong>${escapeHTML(label)}</strong><small>${ok ? escapeHTML(status.detail || "Работает") : escapeHTML(status.error || "Недоступно")}</small></div><span class="badge ${ok ? "" : "error"}">${ok ? "Готов" : "Ошибка"}</span></div>`;
}



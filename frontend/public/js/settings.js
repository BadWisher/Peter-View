import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderSettings() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let settings = {};
  try { settings = await api("/api/settings"); } catch (error) { showError(error); }
  if (state.route !== "settings") return;
  renderShell(`
    <div class="page">
      <div class="page-actions"><button class="button secondary test-settings" type="button">${icon("icon-activity")}Проверить подключение</button></div>
      <form id="settings-form">
        <div class="settings-form">
          <section class="settings-section settings-api"><h3>Peter View API</h3>
            <div class="settings-api-list">
              <div class="settings-api-item"><span>Документация</span><code>/api/docs</code><a class="button secondary" href="/api/docs" target="_blank" rel="noopener">Открыть</a></div>
              <div class="settings-api-item"><span>ReDoc</span><code>/api/redoc</code><a class="button secondary" href="/api/redoc" target="_blank" rel="noopener">Открыть</a></div>
              <div class="settings-api-item"><span>Схема</span><code>/api/openapi.json</code><a class="button secondary" href="/api/openapi.json" target="_blank" rel="noopener">Открыть</a></div>
            </div>
          </section>
          <section class="settings-section"><h3>Модель</h3>
            <label class="field"><span>Адрес API</span><input name="llm_base_url" type="url" inputmode="url" value="${escapeHTML(settings.llm_base_url || "")}" placeholder="https://api.example.ru/v1…" autocomplete="off"></label>
            <div class="field-row"><label class="field"><span>Модель</span><input name="llm_model" value="${escapeHTML(settings.llm_model || "")}" autocomplete="off" spellcheck="false"></label><label class="field"><span>API-ключ</span><input name="llm_api_key" type="password" placeholder="${settings.llm_api_key_set ? "Ключ задан" : "Введите ключ…"}" autocomplete="new-password" spellcheck="false"></label></div>
            <div class="field-row"><label class="field"><span>Температура</span><input name="llm_temperature" type="number" min="0" max="2" step="0.1" value="${escapeHTML(settings.llm_temperature ?? 0)}" inputmode="decimal"></label><label class="field"><span>Параллельность</span><input name="llm_concurrency" type="number" min="1" max="20" value="${escapeHTML(settings.llm_concurrency ?? 3)}" inputmode="numeric"></label></div>
          </section>
          <section class="settings-section"><h3>Эмбеддинги</h3><label class="field"><span>Адрес API</span><input name="embedding_base_url" type="url" inputmode="url" value="${escapeHTML(settings.embedding_base_url || "")}" placeholder="https://api.example.ru/v1…" autocomplete="off"></label><div class="field-row"><label class="field"><span>Модель</span><input name="embedding_model" value="${escapeHTML(settings.embedding_model || "")}" autocomplete="off" spellcheck="false"></label><label class="field"><span>API-ключ</span><input name="embedding_api_key" type="password" placeholder="${settings.embedding_api_key_set ? "Ключ задан" : "Введите ключ…"}" autocomplete="new-password" spellcheck="false"></label></div></section>
          <section class="settings-section"><h3>Выполнение</h3><div class="field-row"><label class="field"><span>Тайм-аут, секунд</span><input name="llm_timeout" type="number" min="5" max="600" value="${escapeHTML(settings.llm_timeout ?? 120)}" inputmode="numeric"></label><label class="field"><span>Усилие рассуждения</span><select name="llm_reasoning_effort"><option value="low" ${settings.llm_reasoning_effort === "low" ? "selected" : ""}>Низкое</option><option value="medium" ${!settings.llm_reasoning_effort || settings.llm_reasoning_effort === "medium" ? "selected" : ""}>Среднее</option><option value="high" ${settings.llm_reasoning_effort === "high" ? "selected" : ""}>Высокое</option></select></label></div><label class="guide-choice"><input name="llm_json_mode" type="checkbox" ${settings.llm_json_mode ? "checked" : ""}><span><strong>JSON-режим</strong><small>Структурированный ответ модели</small></span></label></section>
          <div class="inline-actions"><button class="button primary" type="submit">Сохранить настройки</button></div>
        </div>
      </form>
    </div>`);
  const form = document.querySelector("#settings-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    new FormData(form).forEach((value, key) => {
      if (value !== "") payload[key] = ["llm_temperature", "llm_concurrency", "llm_timeout"].includes(key) ? Number(value) : value;
    });
    payload.llm_json_mode = form.elements.llm_json_mode.checked;
    const button = form.querySelector("[type=submit]");
    setBusy(button, true);
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
      toast("Настройки сохранены");
      renderApp();
      return;
    } catch (error) { showError(error); }
    setBusy(button, false);
  });
  document.querySelector(".test-settings").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, "Проверка…");
    try {
      const result = await api("/api/settings/test", { method: "POST", body: "{}" });
      const failed = Object.entries(result).filter(([, item]) => !item.ok);
      if (failed.length) toast("Есть проблемы", failed.map(([name]) => name).join(", "), "error");
      else toast("Подключения работают");
    } catch (error) { showError(error); }
    setBusy(button, false);
  });
}


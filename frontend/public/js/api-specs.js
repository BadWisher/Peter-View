import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderApiSpecs() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  try {
    const data = await api("/api/api-specs");
    state.specs = data.specs || [];
    if (!state.activeSpec && state.specs.length) state.activeSpec = state.specs[0].id;
  } catch (error) {
    showError(error);
  }
  if (state.route !== "api") return;
  drawApiSpecs();
}

export function drawApiSpecs() {
  const active = state.specs.find((spec) => spec.id === state.activeSpec);
  renderShell(`
    <div class="page">
      <div class="page-actions api-page-actions">${state.specs.length ? `<label class="field compact-field"><span class="visually-hidden">Связка API</span><select id="spec-switch">${state.specs.map((spec) => `<option value="${escapeHTML(spec.id)}" ${spec.id === state.activeSpec ? "selected" : ""}>${escapeHTML(spec.name)}</option>`).join("")}</select></label>` : ""}<div class="inline-actions"><button class="button primary create-spec" type="button">${icon("icon-plus")}Добавить связку</button></div></div>
      ${state.specs.length ? `<section class="panel api-workbench">
        <div class="spec-main">
          <div class="panel-head api-head"><div><h3>${escapeHTML(active?.name || "Спецификация")}</h3><p>${escapeHTML(active?.ru?.name || "RU")} / ${escapeHTML(active?.en?.name || "EN")}</p></div><div class="api-actions"><button class="button secondary spec-review" type="button">Проверить изменения</button><button class="button primary spec-translate" type="button">Перевести</button><details class="action-menu"><summary class="button secondary">${icon("icon-download")}Скачать</summary><div><button class="spec-download" data-target="ru" type="button">Русский YAML</button><button class="spec-download" data-target="en" type="button">English YAML</button></div></details><button class="icon-button edit-spec" type="button" aria-label="Настроить связку">${icon("icon-edit")}</button><button class="icon-button delete-spec" type="button" aria-label="Удалить связку">${icon("icon-trash")}</button></div></div>
          <div class="spec-tabs">${[["segments","Поля"],["consistency","Единообразие"],["diff","Изменения"]].map(([id,label]) => `<button class="${state.specTab === id ? "active" : ""}" type="button" data-spec-tab="${id}">${label}</button>`).join("")}</div>
          <div class="spec-content" id="spec-content"><div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div></div>
        </div>
      </section>` : `<section class="panel empty-state">${icon("icon-code")}<div><h3>Связок пока нет</h3><p>Выберите документы RU и EN из репозитория.</p><button class="button primary create-spec" type="button">Добавить связку</button></div></section>`}
    </div>`);
  bindApiSpecs();
  if (active) loadSpecContent();
}

export function bindApiSpecs() {
  document.querySelectorAll(".create-spec").forEach((button) => button.addEventListener("click", showCreateSpec));
  document.querySelector("#spec-switch")?.addEventListener("change", (event) => {
    if (state.activeSpec !== event.target.value) {
      state.apiEdits = { ru: {}, en: {} };
      state.specQuery = "";
      state.specPage = 0;
    }
    state.activeSpec = event.target.value;
    drawApiSpecs();
  });
  document.querySelectorAll("[data-spec-tab]").forEach((button) => button.addEventListener("click", () => {
    state.specTab = button.dataset.specTab;
    drawApiSpecs();
  }));
  document.querySelector(".spec-review")?.addEventListener("click", () => runSpecJob("ai-review"));
  document.querySelector(".spec-translate")?.addEventListener("click", () => runSpecJob("translate"));
  document.querySelectorAll(".spec-download").forEach((button) => button.addEventListener("click", () => downloadEditedSpec(button.dataset.target)));
  document.querySelector(".edit-spec")?.addEventListener("click", () => showEditSpec(state.specs.find((spec) => spec.id === state.activeSpec)));
  document.querySelector(".delete-spec")?.addEventListener("click", deleteActiveSpec);
}

export async function loadSpecContent() {
  const target = document.querySelector("#spec-content");
  if (!target) return;
  try {
    if (state.specTab === "segments") {
      const page = Math.max(0, Number(state.specPage) || 0);
      const data = await api(`/api/api-specs/${encodeURIComponent(state.activeSpec)}/segments?page=${page}&size=50&q=${encodeURIComponent(state.specQuery)}`);
      const items = data.segments || data.items || [];
      const total = data.total ?? items.length;
      const pages = Math.max(1, Math.ceil(total / (data.size || 50)));
      if (page > 0 && !items.length && total > 0) {
        state.specPage = 0;
        return loadSpecContent();
      }
      const from = total ? page * (data.size || 50) + 1 : 0;
      const to = Math.min(total, from + items.length - 1);
      const pager = pages > 1 ? `<footer class="spec-pager"><span>${from}–${to} из ${total}</span><div class="spec-pager-buttons"><button class="icon-button spec-prev" type="button" aria-label="Предыдущие поля" ${page === 0 ? "disabled" : ""}><span class="flip-x">${icon("icon-arrow")}</span></button><button class="icon-button spec-next" type="button" aria-label="Следующие поля" ${page + 1 >= pages ? "disabled" : ""}>${icon("icon-arrow")}</button></div></footer>` : "";
      target.innerHTML = `<div class="toolbar spec-segment-toolbar"><label class="search-field">${icon("icon-search")}<span class="visually-hidden">Поиск полей API</span><input id="spec-search" type="search" value="${escapeHTML(state.specQuery)}" placeholder="Путь или текст…" autocomplete="off"></label><span class="field-hint">${total} полей · RU v${data.ru_version || "?"} · EN v${data.en_version || "?"}</span></div><div class="spec-table"><div class="segment-row header"><div>Поле</div><div>Русский</div><div>English</div></div>${items.map((item) => {
        const path = item.path_str || item.path || "";
        const context = item.context || item.kind || "";
        const loc = [item.ru_line && `RU ${item.ru_line}`, item.en_line && `EN ${item.en_line}`].filter(Boolean).join(" · ");
        const ruText = Object.hasOwn(state.apiEdits.ru, path) ? state.apiEdits.ru[path] : item.ru_text || item.ru || "";
        const enText = Object.hasOwn(state.apiEdits.en, path) ? state.apiEdits.en[path] : item.en_text || item.en || "";
        return `<div class="segment-row"><div class="segment-path-cell"><span class="segment-context">${escapeHTML(context)}${loc ? ` · ${escapeHTML(loc)}` : ""}</span><button class="segment-path" type="button" title="Копировать путь" data-path="${escapeHTML(path)}">${escapeHTML(path)}</button></div><div><label class="segment-editor-label"><span class="visually-hidden">Русский текст: ${escapeHTML(path)}</span><textarea class="segment-editor ${Object.hasOwn(state.apiEdits.ru, path) ? "changed" : ""}" data-target="ru" data-path="${escapeHTML(path)}" rows="2">${escapeHTML(ruText)}</textarea></label></div><div><label class="segment-editor-label"><span class="visually-hidden">Английский текст: ${escapeHTML(path)}</span><textarea class="segment-editor ${Object.hasOwn(state.apiEdits.en, path) ? "changed" : ""}" data-target="en" data-path="${escapeHTML(path)}" rows="2">${escapeHTML(enText)}</textarea></label></div></div>`;
      }).join("") || emptyInline("Поля не найдены")}</div>${pager}`;
      target.querySelectorAll(".segment-editor").forEach((field) => field.addEventListener("input", () => {
        state.apiEdits[field.dataset.target][field.dataset.path] = field.value;
        field.classList.add("changed");
      }));
      let searchTimer;
      target.querySelector("#spec-search")?.addEventListener("input", (event) => {
        window.clearTimeout(searchTimer);
        state.specQuery = event.target.value.trim();
        state.specPage = 0;
        searchTimer = window.setTimeout(loadSpecContent, 300);
      });
      target.querySelector(".spec-prev")?.addEventListener("click", () => {
        state.specPage = Math.max(0, page - 1);
        loadSpecContent();
      });
      target.querySelector(".spec-next")?.addEventListener("click", () => {
        state.specPage = page + 1;
        loadSpecContent();
      });
      target.querySelectorAll(".segment-path").forEach((button) => button.addEventListener("click", () => copyText(button.dataset.path)));
    } else if (state.specTab === "consistency") {
      const data = await api(`/api/api-specs/${encodeURIComponent(state.activeSpec)}/consistency?lang=ru`);
      target.innerHTML = `<div class="spec-pane">${renderConsistency(data)}</div>`;
      target.querySelectorAll("[data-find]").forEach((button) => button.addEventListener("click", () => {
        state.specQuery = button.dataset.find;
        state.specTab = "segments";
        drawApiSpecs();
      }));
    } else {
      const data = await api(`/api/api-specs/${encodeURIComponent(state.activeSpec)}/diff`);
      const changes = data.changes || [];
      target.innerHTML = `<div class="spec-pane">${changes.length ? `<div class="spec-table">${changes.map((change) => `<div class="segment-row"><div class="segment-path-cell"><button class="segment-path" type="button" title="Копировать путь" data-path="${escapeHTML(change.path_str || "")}">${escapeHTML(change.path_str || "")}</button></div><div class="diff-old">${escapeHTML(change.old_text || "Добавлено")}</div><div class="diff-new">${escapeHTML(change.new_text || "Удалено")}${change.en_text ? `<small>EN: ${escapeHTML(change.en_text)}</small>` : ""}</div></div>`).join("")}</div>` : emptyInline(data.has_previous ? "Изменений нет" : "Нужна предыдущая версия RU")}</div>`;
      target.querySelectorAll(".segment-path").forEach((button) => button.addEventListener("click", () => copyText(button.dataset.path)));
    }
  } catch (error) {
    target.innerHTML = emptyInline(error.message);
  }
}

export async function downloadEditedSpec(targetLanguage) {
  const edits = { ...(state.apiEdits[targetLanguage] || {}) };
  document.querySelectorAll(`.segment-editor[data-target="${targetLanguage}"]`).forEach((field) => {
    edits[field.dataset.path] = field.value;
  });
  try {
    const blob = await api(`/api/api-specs/${encodeURIComponent(state.activeSpec)}/download`, {
      method: "POST",
      body: JSON.stringify({ target: targetLanguage, edits }),
    });
    downloadBlob(blob, `${targetLanguage}-edited.yaml`);
    toast("Файл подготовлен", `${targetLanguage.toUpperCase()} с текущими правками`);
  } catch (error) {
    showError(error);
  }
}


export function consVariantRows(group) {
  const rows = (group.variants || []).map((variant) => {
    const text = variant.text || "";
    const count = variant.count ?? "";
    const action = text
      ? `<button class="button ghost cons-find" type="button" data-find="${escapeHTML(text)}">${count} в полях</button>`
      : `<span class="field-hint">${count}</span>`;
    return `<div class="cons-variant"><p>${text ? escapeHTML(text) : "Пусто"}</p>${action}</div>`;
  }).join("");
  const hidden = (group.variants_total || 0) - (group.variants || []).length;
  const more = hidden > 0 ? `<p class="field-hint">Ещё ${hidden} вариантов</p>` : "";
  return rows + more;
}

export function renderConsistency(data = {}) {
  const parts = [];
  if (data.by_text?.length) {
    parts.push(`<h4 class="cons-title">Одно и то же, написано по-разному</h4>`);
    for (const group of data.by_text) {
      parts.push(`<article class="cons-group"><div class="cons-head"><strong>${escapeHTML(group.reason || "Разное написание")}</strong><span>${group.count || 0} полей</span></div>${consVariantRows(group)}</article>`);
    }
  }
  if (data.by_name?.length) {
    parts.push(`<h4 class="cons-title">Поле с одним именем описано по-разному</h4>`);
    for (const group of data.by_name) {
      parts.push(`<article class="cons-group"><div class="cons-head"><code>${escapeHTML(group.name || "")}</code>${group.near ? `<span class="badge warning">Почти дубли</span>` : ""}<span>${group.variants_total || group.variants?.length || 0} вариантов</span></div>${consVariantRows(group)}</article>`);
    }
  }
  return parts.length ? `<div class="cons-list">${parts.join("")}</div>` : emptyInline("Расхождений нет");
}

export async function showCreateSpec() {
  try {
    const data = await api("/api/api-spec-documents");
    const options = (data.documents || []).map((doc) => `<option value="${escapeHTML(doc.id)}">${escapeHTML(doc.name || doc.filename)}</option>`).join("");
    modal({
      title: "Новая связка",
      body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" required autocomplete="off"></label><div class="field-row"><label class="field"><span>Документ RU</span><select name="ru_doc_id" required>${options}</select></label><label class="field"><span>Документ EN</span><select name="en_doc_id" required>${options}</select></label></div><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Создать</button></div></form>`,
      onReady(dialog, close) {
        const form = dialog.querySelector("form");
        form.querySelector(".cancel").addEventListener("click", close);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          try {
            await api("/api/api-specs", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
            close();
            toast("Связка создана");
            renderApiSpecs();
          } catch (error) { showError(error); }
        });
      },
    });
  } catch (error) { showError(error); }
}

export async function showEditSpec(spec) {
  if (!spec) return;
  try {
    const data = await api("/api/api-spec-documents");
    const options = (selectedId) => (data.documents || []).map((doc) => `<option value="${escapeHTML(doc.id)}" ${doc.id === selectedId ? "selected" : ""}>${escapeHTML(doc.name || doc.filename)}</option>`).join("");
    modal({
      title: "Настроить связку",
      body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" value="${escapeHTML(spec.name || "")}" required autocomplete="off"></label><div class="field-row"><label class="field"><span>Документ RU</span><select name="ru_doc_id" required>${options(spec.ru?.id)}</select></label><label class="field"><span>Документ EN</span><select name="en_doc_id" required>${options(spec.en?.id)}</select></label></div><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить</button></div></form>`,
      onReady(dialog, close) {
        const form = dialog.querySelector("form");
        form.querySelector(".cancel").addEventListener("click", close);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          try {
            await api(`/api/api-specs/${encodeURIComponent(spec.id)}`, { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
            close();
            toast("Связка обновлена");
            renderApiSpecs();
          } catch (error) { showError(error); }
        });
      },
    });
  } catch (error) { showError(error); }
}

export function deleteActiveSpec() {
  const spec = state.specs.find((item) => item.id === state.activeSpec);
  if (!spec) return;
  confirmAction({
    title: "Удалить связку?",
    description: `Документы «${spec.name}» останутся в репозитории.`,
    async onConfirm() {
      await api(`/api/api-specs/${encodeURIComponent(spec.id)}`, { method: "DELETE" });
      state.activeSpec = null;
      toast("Связка удалена");
      renderApiSpecs();
    },
  });
}

export async function runSpecJob(action) {
  try {
    const result = await api(`/api/api-specs/${encodeURIComponent(state.activeSpec)}/${action}`, { method: "POST", body: "{}" });
    toast("Задача запущена", action === "translate" ? "Переводим изменённые поля" : "Проверяем изменения");
    watchSpecJob(result.job_id, action);
  } catch (error) { showError(error); }
}

export async function watchSpecJob(jobId, action) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    if (state.route !== "api") return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "error") throw new Error(job.error || "Задача завершилась с ошибкой");
      if (job.status !== "done") continue;
      const report = await api(`/api/jobs/${encodeURIComponent(jobId)}/report`);
      if (action === "translate") applySpecTranslations(report);
      else showSpecReview(report);
      return;
    } catch (error) {
      showError(error);
      return;
    }
  }
  toast("Задача выполняется слишком долго", "Повторите запуск позже.", "error");
}

export function applySpecTranslations(report) {
  const translations = report.translations || [];
  translations.forEach((translation) => {
    state.apiEdits.en[translation.path_str] = translation.en_text || "";
    const field = [...document.querySelectorAll('.segment-editor[data-target="en"]')]
      .find((item) => item.dataset.path === translation.path_str);
    if (field) {
      field.value = translation.en_text || "";
      field.classList.add("changed");
    }
  });
  toast(translations.length ? "Перевод готов" : "Изменений нет", translations.length ? `${translations.length} полей обновлено. Проверьте их и скачайте EN.` : report.message || "");
}

export function showSpecReview(report) {
  const issues = report.issues || [];
  modal({
    title: "AI-проверка изменений",
    description: issues.length ? `${issues.length} замечаний` : report.message || "Замечаний нет",
    body: issues.length
      ? `<div class="dialog-body spec-review-results">${issues.map((issue) => `<article><span class="badge ${escapeHTML(issue.severity || "warning")}">${escapeHTML(issue.severity || "замечание")}</span><strong>${escapeHTML(issue.path_str || issue.path || "Поле")}</strong><p>${escapeHTML(issue.message || issue.description || issue.suggestion || "")}</p></article>`).join("")}<div class="dialog-actions"><button class="button primary close-review" type="button">Готово</button></div></div>`
      : `<div class="dialog-body"><div class="empty-state">${icon("icon-check")}<div><h3>Замечаний нет</h3><p>${escapeHTML(report.message || "Изменения прошли проверку.")}</p></div></div><div class="dialog-actions"><button class="button primary close-review" type="button">Готово</button></div></div>`,
    onReady(dialog, close) {
      dialog.querySelector(".close-review").addEventListener("click", close);
    },
  });
}


import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderGuides() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  try {
    const data = await api("/api/styleguides");
    state.guides = data.styleguides || [];
    state.selectedGuide = data.selected || "";
    const id = state.guide?.id || state.selectedGuide || state.guides[0]?.id;
    state.guide = id ? await api(`/api/styleguides/${encodeURIComponent(id)}`) : null;
  } catch (error) { showError(error); }
  if (state.route !== "guides") return;
  drawGuides();
}

export function drawGuides() {
  const guide = state.guide || (state.guides[0] ? {
    ...state.guides[0],
    rules: [],
    lexicon: { forbidden: [], allowed: [] },
  } : null);
  const rules = guide?.rules || [];
  const lexicon = guide?.lexicon || { forbidden: [], allowed: [] };
  const admin = state.user?.role === "admin";
  renderShell(`
    <div class="page">
      <div class="page-actions">${admin && guide ? `<label class="button secondary update-guide">${icon("icon-upload")}Обновить из docx<input class="visually-hidden" type="file" accept=".docx,.txt,.md"></label>` : ""}${admin ? `<button class="button primary import-guide" type="button">${icon("icon-upload")}Импортировать</button>` : ""}</div>
      ${state.guideExtract?.running ? `<div class="guide-extract-banner" role="status" aria-live="polite"><span class="progress-spinner" aria-hidden="true"></span><div><strong>${escapeHTML(state.guideExtract.filename || "Документ")}</strong><p class="extract-stage">${escapeHTML(state.guideExtract.stage || "Отправка документа")}</p></div></div>` : ""}
      <div class="guide-layout">
        <aside class="guide-list">
          ${state.guides.map((item) => `<button class="guide-item ${guide?.id === item.id ? "active" : ""}" type="button" data-guide-id="${escapeHTML(item.id)}"><strong>${escapeHTML(item.name)}</strong>${item.selected ? `<span class="badge">Активен</span>` : ""}<small>${item.rule_count || 0} правил · ${item.lexicon_count || 0} терминов</small></button>`).join("")}
        </aside>
        ${guide ? `<section class="panel rule-list">
          <div class="panel-head"><div><h3>${escapeHTML(guide.name)}</h3><p>${rules.length} правил</p></div><div class="inline-actions">${admin ? `<button class="button secondary edit-lexicon" type="button">${icon("icon-edit")}Словарь</button><button class="button secondary add-rule" type="button">${icon("icon-plus")}Правило</button>` : ""}${guide.selected ? "" : `<button class="button secondary select-guide" type="button">Использовать</button>`}${admin && !guide.builtin ? `<button class="icon-button delete-guide" type="button" aria-label="Удалить Style Guide">${icon("icon-trash")}</button>` : ""}</div></div>
          <div class="toolbar" style="padding:12px 14px;margin:0;border-bottom:1px solid var(--line)"><label class="search-field">${icon("icon-search")}<span class="visually-hidden">Поиск правил</span><input id="rule-search" type="search" placeholder="Правило или группа…" autocomplete="off"></label><div class="segmented" role="group" aria-label="Содержимое"><button type="button" data-guide-tab="rules" aria-pressed="true">Правила</button><button type="button" data-guide-tab="lexicon" aria-pressed="false">Словарь</button></div></div>
          <div id="guide-content">${renderRules(rules)}</div>
          <template id="lexicon-template"><div class="panel-body lexicon-grid">${renderLexicon("Запрещено", lexicon.forbidden || [])}${renderLexicon("Разрешено", lexicon.allowed || [])}</div></template>
        </section>` : `<section class="panel empty-state">${icon("icon-book")}<div><h3>Нет Style Guide</h3><p>Импортируйте DOCX с правилами.</p></div></section>`}
      </div>
    </div>`);
  bindGuides();
}

export function renderRules(rules) {
  const severityLabel = { blocker: "Обязательно", suggestion: "Рекомендация", minor: "Мелочь" };
  const canEdit = state.user?.role === "admin";
  return `<div class="rule-rows">${rules.map((rule, index) => `<div class="rule-row" data-rule-text="${escapeHTML(`${rule.title || ""} ${rule.group || ""} ${rule.description || ""}`.toLocaleLowerCase("ru"))}"><div class="rule-main"><div class="rule-heading"><strong>${escapeHTML(rule.title || rule.rule_id || "Правило")}</strong>${rule.group ? `<span>${escapeHTML(rule.group)}</span>` : ""}</div><p>${escapeHTML(rule.description || rule.rule || rule.recommendation || "")}</p></div><div class="rule-meta"><span class="badge ${rule.severity === "blocker" ? "error" : rule.severity === "minor" ? "suggestion" : "warning"}">${severityLabel[rule.severity] || "Правило"}</span><code>${escapeHTML(rule.rule_id || "")}</code></div>${canEdit ? `<button class="icon-button edit-rule" data-rule-index="${index}" type="button" aria-label="Редактировать правило">${icon("icon-edit")}</button>` : ""}</div>`).join("") || emptyInline("Правил нет")}</div>`;
}

export function renderLexicon(title, items) {
  return `<section class="lexicon-column"><h4>${title}</h4><div class="term-list">${items.map((item) => `<span class="term">${escapeHTML(item.term || item)}</span>`).join("") || `<span class="field-hint">Список пуст</span>`}</div></section>`;
}

export function bindGuides() {
  document.querySelectorAll("[data-guide-id]").forEach((button) => button.addEventListener("click", async () => {
    try {
      state.guide = await api(`/api/styleguides/${encodeURIComponent(button.dataset.guideId)}`);
      drawGuides();
    } catch (error) { showError(error); }
  }));
  document.querySelector(".select-guide")?.addEventListener("click", async () => {
    try {
      await api(`/api/styleguides/${encodeURIComponent(state.guide.id)}/select`, { method: "POST", body: "{}" });
      toast("Style Guide выбран");
      renderGuides();
    } catch (error) { showError(error); }
  });
  document.querySelector(".delete-guide")?.addEventListener("click", () => confirmAction({
    title: "Удалить Style Guide?",
    description: "Встроенный Style Guide удалить нельзя.",
    async onConfirm() {
      await api(`/api/styleguides/${encodeURIComponent(state.guide.id)}`, { method: "DELETE" });
      state.guide = null;
      toast("Style Guide удалён");
      renderGuides();
    },
  }));
  document.querySelector(".import-guide")?.addEventListener("click", showImportGuide);
  document.querySelector(".update-guide input")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) startGuideExtract(file, "update");
  });
  document.querySelector(".add-rule")?.addEventListener("click", () => showRuleEditor());
  document.querySelector(".edit-lexicon")?.addEventListener("click", showLexiconEditor);
  bindRuleButtons();
  document.querySelector("#rule-search")?.addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase("ru");
    document.querySelectorAll("[data-rule-text]").forEach((row) => {
      row.hidden = !row.dataset.ruleText.includes(query);
    });
  });
  document.querySelectorAll("[data-guide-tab]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("[data-guide-tab]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    document.querySelector("#guide-content").innerHTML = button.dataset.guideTab === "rules"
      ? renderRules(state.guide.rules || [])
      : document.querySelector("#lexicon-template").innerHTML;
    bindRuleButtons();
  }));
}

export function bindRuleButtons() {
  document.querySelectorAll(".edit-rule").forEach((button) => button.addEventListener("click", () => showRuleEditor(Number(button.dataset.ruleIndex))));
}

export function showLexiconEditor() {
  const lexicon = state.guide.lexicon || { forbidden: [], allowed: [] };
  const terms = (items) => (items || []).map((item) => item.term || item).join("\n");
  modal({
    title: "Словарь Style Guide",
    description: "Укажите по одному выражению в строке.",
    body: `<form class="dialog-body"><label class="field"><span>Запрещённые выражения</span><textarea name="forbidden" rows="7">${escapeHTML(terms(lexicon.forbidden))}</textarea></label><label class="field"><span>Разрешённые выражения</span><textarea name="allowed" rows="7">${escapeHTML(terms(lexicon.allowed))}</textarea></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить словарь</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const parse = (value, original) => value.split("\n").map((term) => term.trim()).filter(Boolean).map((term) => {
          const existing = (original || []).find((item) => (item.term || item) === term);
          return typeof existing === "object" ? { ...existing, term } : { term };
        });
        const next = { forbidden: parse(form.elements.forbidden.value, lexicon.forbidden), allowed: parse(form.elements.allowed.value, lexicon.allowed) };
        try {
          if (isPreview) state.guide = { ...state.guide, lexicon: next };
          else state.guide = await api(`/api/styleguides/${encodeURIComponent(state.guide.id)}`, { method: "PUT", body: JSON.stringify({ lexicon: next }) });
          close();
          toast("Словарь сохранён");
          drawGuides();
        } catch (error) { showError(error); }
      });
    },
  });
}

export function showRuleEditor(index = null) {
  const current = index === null ? {} : state.guide.rules[index] || {};
  modal({
    title: index === null ? "Новое правило" : "Редактировать правило",
    body: `<form class="dialog-body">
      <div class="field-row"><label class="field"><span>Идентификатор</span><input name="rule_id" value="${escapeHTML(current.rule_id || "")}" required autocomplete="off"></label><label class="field"><span>Важность</span><select name="severity"><option value="blocker" ${current.severity === "blocker" ? "selected" : ""}>Blocker</option><option value="suggestion" ${current.severity === "suggestion" ? "selected" : ""}>Suggestion</option><option value="minor" ${current.severity === "minor" ? "selected" : ""}>Minor</option></select></label></div>
      <label class="field"><span>Название</span><input name="title" value="${escapeHTML(current.title || "")}" required autocomplete="off"></label>
      <label class="field"><span>Группа</span><input name="group" value="${escapeHTML(current.group || "")}" autocomplete="off"></label>
      <label class="field"><span>Описание</span><textarea name="description" rows="4" required>${escapeHTML(current.description || "")}</textarea></label>
      <label class="field"><span>Рекомендация</span><textarea name="recommendation" rows="3">${escapeHTML(current.recommendation || current.suggestion || "")}</textarea></label>
      <div class="dialog-actions">${index === null ? "" : `<button class="button danger remove-rule" type="button">Удалить</button>`}<button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить</button></div>
    </form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.querySelector(".remove-rule")?.addEventListener("click", async () => {
        const rules = state.guide.rules.filter((_, ruleIndex) => ruleIndex !== index);
        await saveGuideRules(rules, close, "Правило удалено");
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const next = { ...current, ...Object.fromEntries(new FormData(form)) };
        const rules = [...(state.guide.rules || [])];
        if (index === null) rules.push(next);
        else rules[index] = next;
        await saveGuideRules(rules, close, "Правило сохранено");
      });
    },
  });
}

export async function saveGuideRules(rules, close, message) {
  try {
    if (isPreview) state.guide = { ...state.guide, rules };
    else state.guide = await api(`/api/styleguides/${encodeURIComponent(state.guide.id)}`, { method: "PUT", body: JSON.stringify({ rules }) });
    close();
    toast(message);
    drawGuides();
  } catch (error) {
    showError(error);
  }
}

export function showImportGuide() {
  modal({
    title: "Импорт Style Guide",
    description: "Правила будут извлечены из документа.",
    body: `<form class="dialog-body"><label class="field"><span>Файл</span><input name="file" type="file" accept=".docx,.txt,.md" required></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Извлечь правила</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = form.elements.file.files[0];
        close();
        startGuideExtract(file, "import");
      });
    },
  });
}

export function showGuideExtractProgress(filename, mode) {
  modal({
    title: mode === "update" ? "Обновление Style Guide" : "Извлечение правил",
    description: filename,
    body: `<div class="dialog-body extract-progress"><span class="progress-spinner" aria-hidden="true"></span><p class="extract-stage">Отправка документа</p></div>`,
    onReady() {},
  });
}

export function setGuideExtractStage(stage) {
  if (state.guideExtract) state.guideExtract.stage = stage;
  document.querySelectorAll(".extract-stage").forEach((element) => {
    element.textContent = stage;
  });
}

export async function startGuideExtract(file, mode) {
  if (!file) return;
  state.guideExtract = { running: true, filename: file.name, stage: "Отправка документа", mode };
  if (state.route === "guides") drawGuides();
  showGuideExtractProgress(file.name, mode);
  setGuideExtractStage("Отправка документа");
  try {
    const data = new FormData();
    data.append("file", file);
    const job = await api("/api/styleguides/extract", { method: "POST", body: data });
    setGuideExtractStage("В очереди");
    await watchGuideExtraction(job.job_id, file.name, mode);
  } catch (error) {
    state.guideExtract = null;
    overlayRoot.innerHTML = "";
    document.body.classList.remove("has-modal");
    app.inert = false;
    if (state.route === "guides") drawGuides();
    showError(error);
  }
}

export async function watchGuideExtraction(jobId, filename, mode = "import") {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    try {
      const job = await api(`/api/styleguides/extract/${encodeURIComponent(jobId)}`);
      if (job.stage) setGuideExtractStage(job.stage);
      if (job.status === "done") {
        state.guideExtract = null;
        overlayRoot.querySelector(".dialog-close")?.click();
        if (state.route === "guides") drawGuides();
        const extracted = {
          rules: job.rules || [],
          lexicon: job.lexicon || { forbidden: [], allowed: [] },
          filename: job.source_filename || filename,
          warning: job.warning || "",
        };
        if (mode === "update") showUpdatedGuide(extracted);
        else showExtractedGuide(extracted);
        return;
      }
      if (job.status === "error") throw new Error(job.error || "Не удалось извлечь правила");
    } catch (error) {
      state.guideExtract = null;
      overlayRoot.querySelector(".dialog-close")?.click();
      if (state.route === "guides") drawGuides();
      showError(error);
      return;
    }
  }
  state.guideExtract = null;
  overlayRoot.querySelector(".dialog-close")?.click();
  if (state.route === "guides") drawGuides();
  toast("Извлечение выполняется слишком долго", "Повторите импорт позже.", "error");
}

export function guideNameFromFile(filename) {
  return String(filename || "").replace(/\.[^.]+$/, "").trim();
}

export function normGuideKey(value) {
  return String(value || "").toLowerCase().replace(/ё/g, "е").replace(/[^\wа-яa-z]+/gi, " ").trim();
}

export function ruleBody(rule) {
  return String(rule?.rule || rule?.description || "").trim();
}

export function examplesKey(value) {
  return (Array.isArray(value) ? value : []).map((item) => String(item).toLowerCase().replace(/\s+/g, " ").trim()).filter(Boolean).sort().join("|");
}

export function mergeTerms(existing, incoming) {
  const byKey = new Map();
  let added = 0;
  let updated = 0;
  for (const item of existing || []) {
    const term = String(item.term || item || "").trim();
    const key = normGuideKey(term);
    if (!key) continue;
    byKey.set(key, typeof item === "object" ? { ...item, term } : { term });
  }
  for (const item of incoming || []) {
    const term = String(item.term || item || "").trim();
    const key = normGuideKey(term);
    if (!key) continue;
    const prev = byKey.get(key);
    if (!prev) {
      byKey.set(key, typeof item === "object" ? { ...item, term } : { term });
      added += 1;
      continue;
    }
    const next = { ...prev, ...(typeof item === "object" ? item : {}), term, rule_id: prev.rule_id || item.rule_id };
    const changed = (prev.replacement || "") !== (next.replacement || "")
      || (prev.comment || "") !== (next.comment || "")
      || (prev.en || "") !== (next.en || "");
    if (changed) updated += 1;
    byKey.set(key, next);
  }
  return { items: [...byKey.values()], added, updated };
}

export function mergeGuideFromDocument(current, incomingRules, incomingLexicon, incomingName) {
  const rules = [...(current?.rules || [])];
  const indexByTitle = new Map();
  rules.forEach((rule, index) => {
    const key = normGuideKey(rule.title);
    if (key && !indexByTitle.has(key)) indexByTitle.set(key, index);
  });
  let rulesUpdated = 0;
  let rulesAdded = 0;
  for (const incoming of incomingRules || []) {
    const key = normGuideKey(incoming.title);
    const text = ruleBody(incoming);
    const fresh = {
      title: incoming.title || text.slice(0, 60),
      rule: text,
      description: text,
      group: incoming.group || "",
      severity: incoming.severity || "suggestion",
      good_examples: incoming.good_examples || [],
      bad_examples: incoming.bad_examples || [],
    };
    if (!key || indexByTitle.get(key) == null) {
      rules.push(fresh);
      if (key) indexByTitle.set(key, rules.length - 1);
      rulesAdded += 1;
      continue;
    }
    const index = indexByTitle.get(key);
    const existing = rules[index];
    const nextText = text || ruleBody(existing);
    const nextGood = examplesKey(incoming.good_examples) ? incoming.good_examples : existing.good_examples;
    const nextBad = examplesKey(incoming.bad_examples) ? incoming.bad_examples : existing.bad_examples;
    const nextGroup = incoming.group || existing.group;
    const nextSeverity = incoming.severity || existing.severity;
    const changed = normGuideKey(ruleBody(existing)) !== normGuideKey(nextText)
      || examplesKey(existing.good_examples) !== examplesKey(nextGood)
      || examplesKey(existing.bad_examples) !== examplesKey(nextBad)
      || String(existing.group || "") !== String(nextGroup || "")
      || String(existing.severity || "") !== String(nextSeverity || "");
    if (!changed) continue;
    rules[index] = {
      ...existing,
      title: incoming.title || existing.title,
      rule: nextText,
      description: nextText,
      group: nextGroup,
      severity: nextSeverity,
      good_examples: nextGood,
      bad_examples: nextBad,
    };
    rulesUpdated += 1;
  }
  const currentLexicon = current?.lexicon || { forbidden: [], allowed: [] };
  const incoming = incomingLexicon || { forbidden: [], allowed: [] };
  const forbidden = mergeTerms(currentLexicon.forbidden, incoming.forbidden);
  const allowed = mergeTerms(currentLexicon.allowed, incoming.allowed);
  return {
    name: String(incomingName || "").trim() || current?.name || "",
    rules: rules.map((rule) => {
      const text = ruleBody(rule);
      return { ...rule, rule: text || rule.rule, description: text || rule.description };
    }),
    lexicon: { forbidden: forbidden.items, allowed: allowed.items },
    stats: {
      rulesUpdated,
      rulesAdded,
      lexiconUpdated: forbidden.updated + allowed.updated,
      lexiconAdded: forbidden.added + allowed.added,
      lexiconTotal: forbidden.items.length + allowed.items.length,
    },
  };
}

export function showUpdatedGuide({ rules = [], lexicon = { forbidden: [], allowed: [] }, filename = "", warning = "" } = {}) {
  const draft = mergeGuideFromDocument(state.guide, rules, lexicon, guideNameFromFile(filename) || state.guide?.name);
  const summary = `${draft.stats.rulesUpdated} обновлено, ${draft.stats.rulesAdded} добавлено. Словарь: ${draft.stats.lexiconAdded} новых выражений${warning ? `. ${warning}` : ""}`;
  modal({
    title: "Документ разобран",
    description: summary,
    body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" value="${escapeHTML(draft.name)}" required autocomplete="off"></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Применить</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector("[type=submit]");
        const payload = {
          name: form.elements.name.value.trim(),
          rules: draft.rules,
          lexicon: draft.lexicon,
        };
        setBusy(button, true, "Сохранение…");
        try {
          state.guide = await api(`/api/styleguides/${encodeURIComponent(state.guide.id)}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          close();
          toast("Style Guide обновлён", `${payload.rules.length} правил, ${payload.lexicon.forbidden.length + payload.lexicon.allowed.length} выражений`);
          if (state.route === "guides") renderGuides();
        } catch (error) {
          showError(error);
          setBusy(button, false);
        }
      });
    },
  });
}

export function showExtractedGuide({ rules = [], lexicon = { forbidden: [], allowed: [] }, filename = "", warning = "" } = {}) {
  const terms = (lexicon.forbidden || []).length + (lexicon.allowed || []).length;
  modal({
    title: "Правила извлечены",
    description: `${rules.length} правил, ${terms} выражений${warning ? `. ${warning}` : ""}`,
    body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" value="${escapeHTML(guideNameFromFile(filename))}" required autocomplete="off"></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить Style Guide</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector("[type=submit]");
        setBusy(button, true, "Сохранение…");
        try {
          await api("/api/styleguides", {
            method: "POST",
            body: JSON.stringify({ name: form.elements.name.value.trim(), rules, lexicon }),
          });
          close();
          toast("Style Guide сохранён");
          if (state.route === "guides") renderGuides();
        } catch (error) {
          showError(error);
          setBusy(button, false);
        }
      });
    },
  });
}


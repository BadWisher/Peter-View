import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export function renderCheck() {
  if (state.currentJob) {
    renderProgress();
    return;
  }
  const guideOptions = state.guides.map((guide) => `<option value="${escapeHTML(guide.id)}" ${guide.id === state.selectedGuide ? "selected" : ""}>${escapeHTML(guide.name)}</option>`).join("");
  renderShell(`
    <div class="page">
      ${state.currentReport ? `<div class="page-actions"><button class="button secondary open-last-report" type="button">${icon("icon-clock")}Последний результат</button></div>` : ""}
      <div class="check-layout">
        <section class="panel elevated source-picker">
          <div class="source-tabs"><div class="segmented" role="group" aria-label="Источник">
            <button type="button" data-source-mode="file" aria-pressed="${state.sourceMode === "file"}">Файл</button>
            <button type="button" data-source-mode="url" aria-pressed="${state.sourceMode === "url"}">Ссылка</button>
            <button type="button" data-source-mode="text" aria-pressed="${state.sourceMode === "text"}">Текст</button>
          </div></div>
          <div class="source-content">${sourceInput()}</div>
        </section>
        <aside class="check-options">
          <section class="panel">
            <div class="panel-body">
              <fieldset class="check-scope"><legend>Проверить</legend>
                ${checkChoice("language", "Язык и ясность")}
                ${checkChoice("styleguide", "Style Guide")}
                ${checkChoice("consistency", "Термины и согласованность")}
              </fieldset>
              <div class="guide-field ${state.checks.styleguide ? "" : "disabled"}">
                <label class="field"><span>Style Guide</span><select id="guide-select" ${state.checks.styleguide ? "" : "disabled"}>${guideOptions || `<option value="">Основной</option>`}</select></label>
              </div>
              <details class="prompt-disclosure" ${state.checkPrompt ? "open" : ""}><summary>Дополнительная инструкция</summary><label class="field"><span class="visually-hidden">Дополнительная инструкция</span><textarea id="check-prompt" rows="4" maxlength="4000" placeholder="Аудитория: администраторы. Технические термины не упрощайте.">${escapeHTML(state.checkPrompt)}</textarea></label></details>
              <button class="button primary start-check" type="button">Начать вычитку</button>
            </div>
          </section>
        </aside>
      </div>
    </div>`);
  bindCheck();
}

export function checkChoice(id, label) {
  return `<label class="check-choice"><input type="checkbox" data-check="${id}" ${state.checks[id] ? "checked" : ""}><span>${label}</span></label>`;
}

export function sourceInput() {
  if (state.sourceMode === "file") {
    if (state.sourceFile) {
      return `<div class="selected-file">${icon("icon-file")}<div><strong>${escapeHTML(state.sourceFile.name)}</strong><small>${formatBytes(state.sourceFile.size)}</small></div><button class="icon-button clear-file" type="button" aria-label="Убрать файл">${icon("icon-close")}</button></div>`;
    }
    return `<label class="drop-zone"><input class="visually-hidden" id="source-file" type="file" accept=".docx,.txt,.html,.htm,.md"><span>${icon("icon-upload")}<strong>Перетащите или выберите файл</strong><span>DOCX, TXT, HTML, MD · до 50 МБ</span></span></label>`;
  }
  if (state.sourceMode === "url") {
    return `<label class="field"><span>Адрес страницы</span><input id="source-url" type="url" inputmode="url" value="${escapeHTML(state.sourceUrl)}" placeholder="https://docs.example.ru/setup/" autocomplete="off"></label>`;
  }
  return `<label class="field"><span>Текст</span><textarea id="source-text" rows="8" placeholder="Вставьте текст…" maxlength="500000">${escapeHTML(state.sourceText)}</textarea><small class="field-hint"><span id="text-count">${new Intl.NumberFormat("ru-RU").format(state.sourceText.length)}</span> из 500 000 знаков</small></label>`;
}

export function bindCheck() {
  document.querySelectorAll("[data-source-mode]").forEach((button) => button.addEventListener("click", () => {
    state.sourceMode = button.dataset.sourceMode;
    renderCheck();
  }));
  document.querySelector("#source-file")?.addEventListener("change", (event) => {
    setSourceFile(event.target.files[0]);
  });
  document.querySelector(".clear-file")?.addEventListener("click", () => {
    state.sourceFile = null;
    renderCheck();
  });
  document.querySelector("#source-text")?.addEventListener("input", (event) => {
    state.sourceText = event.target.value;
    document.querySelector("#text-count").textContent = new Intl.NumberFormat("ru-RU").format(event.target.value.length);
  });
  document.querySelector("#source-url")?.addEventListener("input", (event) => {
    state.sourceUrl = event.target.value;
  });
  document.querySelector("#check-prompt")?.addEventListener("input", (event) => {
    state.checkPrompt = event.target.value;
  });
  document.querySelectorAll("[data-check]").forEach((input) => input.addEventListener("change", () => {
    state.checks[input.dataset.check] = input.checked;
    renderCheck();
  }));
  document.querySelector("#guide-select")?.addEventListener("change", (event) => {
    state.selectedGuide = event.target.value;
  });
  document.querySelector(".start-check").addEventListener("click", startCheck);
  document.querySelector(".open-last-report")?.addEventListener("click", () => go("review"));
  bindDropTarget(document.querySelector(".source-picker"), setSourceFile);
}

export function setSourceFile(file) {
  if (!file) return;
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!["docx", "txt", "html", "htm", "md"].includes(extension)) {
    toast("Формат не поддерживается", "Выберите DOCX, TXT, HTML или MD.", "error");
    return;
  }
  if (file.size > 50 * 1024 * 1024) {
    toast("Файл больше 50 МБ", "Выберите файл меньшего размера.", "error");
    return;
  }
  state.sourceFile = file;
  state.sourceMode = "file";
  renderCheck();
}


export async function startCheck(event) {
  const form = new FormData();
  if (!Object.values(state.checks).some(Boolean)) {
    toast("Выберите хотя бы одну проверку", "", "error");
    return;
  }
  if (state.sourceMode === "file") {
    if (!state.sourceFile) {
      toast("Выберите файл", "Поддерживаются DOCX, TXT, HTML и MD.", "error");
      return;
    }
    form.append("file", state.sourceFile);
  } else if (state.sourceMode === "url") {
    const value = state.sourceUrl.trim();
    if (!/^https?:\/\/\S+$/i.test(value)) {
      toast("Укажите адрес", "Адрес должен начинаться с http:// или https://.", "error");
      return;
    }
    form.append("url", value);
  } else {
    const value = state.sourceText.trim();
    if (!value) {
      toast("Добавьте текст", "", "error");
      return;
    }
    form.append("text", value);
  }
  if (state.selectedGuide) form.append("styleguide_id", state.selectedGuide);
  form.append("check_language", String(state.checks.language));
  form.append("check_styleguide", String(state.checks.styleguide));
  form.append("check_consistency", String(state.checks.consistency));
  if (state.checkPrompt.trim()) form.append("prompt", state.checkPrompt.trim());
  if (isPreview) {
    startPreviewCheck();
    return;
  }
  setBusy(event.currentTarget, true, "Запуск…");
  try {
    const job = await api("/api/jobs", { method: "POST", body: form });
    stopJobWatch();
    state.currentJob = { id: job.job_id, status: "running", stage: "Запуск", workers: {}, found: 0 };
    renderProgress();
    watchJob(job.job_id);
  } catch (error) {
    showError(error);
    setBusy(event.currentTarget, false);
  }
}

export function startPreviewCheck() {
  stopJobWatch();
  const timers = [];
  state.currentJob = { id: "preview-job", status: "running", stage: "Извлечение сигналов", workers: {}, found: 0, previewTimers: timers };
  renderProgress();
  const passes = [
    { id: 1, name: "Язык", scope: "фрагмент 1 из 3", text: "Проверяю формулировки и тяжёлые конструкции в этом фрагменте.\n" },
    { id: 4, name: "Style Guide", scope: "фрагмент 1 из 3", text: "Сверяю правило UITerms_Click и кавычки в названиях кнопок.\n" },
    { id: 2, name: "Структура", scope: "фрагмент 2 из 3", text: "Смотрю заголовки, списки и порядок блоков.\n" },
    { id: 5, name: "Терминология", scope: "весь документ", text: "Собираю повторы терминов по всему тексту.\n" },
    { id: 7, name: "Согласованность", scope: "весь документ", text: "Ищу расхождения регистра и синонимов.\n" },
  ];
  passes.forEach((pass, index) => {
    timers.push(window.setTimeout(() => {
      if (!state.currentJob || state.currentJob.id !== "preview-job") return;
      state.currentJob.workers[pass.id] = {
        id: pass.id,
        name: pass.name,
        scope: pass.scope,
        status: "running",
        text: "",
        pending: "",
        found: null,
      };
      syncProgressWorkers();
      let cursor = 0;
      const timer = window.setInterval(() => {
        if (!state.currentJob?.workers[pass.id]) {
          window.clearInterval(timer);
          return;
        }
        const chunk = pass.text.slice(cursor, cursor + 4);
        cursor += 4;
        if (!chunk) {
          window.clearInterval(timer);
          const worker = state.currentJob.workers[pass.id];
          worker.status = "done";
          worker.found = index === 1 ? 0 : index + 1;
          state.currentJob.found = Object.values(state.currentJob.workers).reduce((sum, item) => sum + (Number(item.found) || 0), 0);
          if (index === passes.length - 1) state.currentJob.stage = "Объединяем находки";
          syncProgressWorkers();
          return;
        }
        workerPending(pass.id, chunk);
      }, 50);
      timers.push(timer);
    }, 220 * index));
  });
  timers.push(window.setTimeout(() => {
    if (state.currentJob?.id !== "preview-job") return;
    stopJobWatch();
    state.currentReport = demoReport();
    state.activeIssue = 0;
    state.currentJob = null;
    go("review");
  }, 6000));
}

export const streamBlocks = new Map();
export const streamDirty = new Set();

export function safeStreamData(event, fallback = {}) {
  try {
    return JSON.parse(event.data);
  } catch {
    return fallback;
  }
}

export function workerBlockKey(id) {
  return String(id);
}

export function workerPending(id, text) {
  if (!text) return;
  const worker = state.currentJob?.workers[workerBlockKey(id)] || state.currentJob?.workers[id];
  if (!worker) return;
  const block = ensureWorkerStream(worker);
  if (!block) return;
  block.pending += text;
  streamDirty.add(block);
  if (state.currentJob && !state.currentJob.raf) {
    state.currentJob.raf = requestAnimationFrame(flushWorkerDeltas);
  }
}

export function stopJobWatch() {
  const job = state.currentJob;
  streamDirty.clear();
  if (!job) {
    streamBlocks.clear();
    return;
  }
  try { job.stream?.close(); } catch {}
  window.clearInterval(job.poll);
  if (job.raf) cancelAnimationFrame(job.raf);
  (job.previewTimers || []).forEach((id) => {
    window.clearTimeout(id);
    window.clearInterval(id);
  });
  job.stream = null;
  job.poll = 0;
  job.raf = 0;
  job.previewTimers = [];
  streamBlocks.clear();
}

export function formatWorkerScope(scope) {
  if (!scope) return "";
  if (scope === "документ") return "весь документ";
  return scope;
}

export function displayWorkerName(name) {
  if (name === "Стайл-гайд" || name === "Соответствие гайду") return "Style Guide";
  return name || "Проверка";
}

export function workerStatusLabel(worker) {
  if (worker.status === "error" || worker.status === "fail") return "ошибка";
  if (worker.status === "done") {
    const found = typeof worker.found === "number" ? worker.found : null;
    if (found === null) return "готово";
    return found > 0 ? `нашёл ${found}` : "чисто";
  }
  return "пишет…";
}

export function workerDotClass(name) {
  return {
    "Язык": "w3",
    "Грамотность": "w1",
    "Структура": "w2",
    "Форматирование": "w2",
    "Стиль и тон": "w3",
    "Стайл-гайд": "w4",
    "Style Guide": "w4",
    "Соответствие гайду": "w4",
    "Терминология": "w5",
    "Согласованность": "w7",
    "Верификатор": "wc",
    "Критик": "wc",
    "Лексикон": "w8",
    "Детерминированные сигналы": "w8",
  }[name] || "";
}

export function passSelector(id) {
  return `[data-pass-id="${CSS.escape(String(id))}"]`;
}

export function renderWorkerCard(worker) {
  const status = worker.status === "fail" ? "error" : (worker.status || "running");
  const output = escapeHTML(`${worker.text || ""}${worker.pending || ""}`);
  return `<article class="worker ${escapeHTML(status)}" data-pass-id="${escapeHTML(workerBlockKey(worker.id))}">
    <div class="worker-head">
      <span class="engine-mark ${workerDotClass(worker.name)}" aria-hidden="true"></span>
      <strong>${escapeHTML(displayWorkerName(worker.name))}</strong>
      <small>${escapeHTML(formatWorkerScope(worker.scope))}</small>
      <span class="ws-status ${status === "running" ? "ws-run" : status === "error" ? "ws-fail" : "ws-done"}">${escapeHTML(workerStatusLabel(worker))}</span>
    </div>
    <pre class="ws-body">${output}</pre>
  </article>`;
}

export function renderProgress() {
  state.route = "check";
  const job = state.currentJob || {};
  const workers = Object.values(job.workers || {});
  const selected = [
    state.checks.language && "Язык и ясность",
    state.checks.styleguide && "Style Guide",
    state.checks.consistency && "Термины и согласованность",
  ].filter(Boolean);
  renderShell(`
    <div class="progress-view">
      <section class="progress-title">
        <span class="progress-spinner" aria-hidden="true"></span>
        <h2>Проверяем документ</h2>
        <p class="progress-stage" aria-live="polite">${escapeHTML(job.stage || "Подготовка")}</p>
        <div class="progress-scopes">${selected.map((label) => `<span>${escapeHTML(label)}</span>`).join("")}</div>
      </section>
      <div class="convergence-progress">
        <div class="workers" id="worker-stream">${workers.length ? workers.map(renderWorkerCard).join("") : `<p class="worker-empty">Ждём ответ воркеров…</p>`}</div>
        <div class="merge-result"><strong class="progress-found-count">${Number(job.found) || 0}</strong><span>находок пока</span></div>
      </div>
      <div class="progress-actions"><button class="button secondary cancel-job" type="button">Вернуться</button></div>
    </div>`);
  document.querySelector(".cancel-job")?.addEventListener("click", () => {
    stopJobWatch();
    state.currentJob = null;
    renderCheck();
  });
  bindStreamBlocks();
}

export function patchProgressStage() {
  const stage = document.querySelector(".progress-stage");
  if (stage) stage.textContent = state.currentJob?.stage || "Подготовка";
  const found = document.querySelector(".progress-found-count");
  if (found) found.textContent = String(Number(state.currentJob?.found) || 0);
}

export function bindStreamBlocks() {
  streamBlocks.clear();
  streamDirty.clear();
  const job = state.currentJob;
  const box = document.querySelector("#worker-stream");
  if (!job || !box) return;
  Object.values(job.workers || {}).forEach((worker) => {
    worker.id = workerBlockKey(worker.id);
    const card = box.querySelector(passSelector(worker.id));
    if (!card) return;
    if (worker.pending) {
      worker.text = `${worker.text || ""}${worker.pending}`;
      worker.pending = "";
    }
    streamBlocks.set(worker.id, {
      worker,
      body: card.querySelector(".ws-body"),
      statusEl: card.querySelector(".ws-status"),
      pending: "",
    });
  });
}

export function ensureWorkerCard(worker) {
  const box = document.querySelector("#worker-stream");
  if (!box) return null;
  box.querySelector(".worker-empty")?.remove();
  worker.id = workerBlockKey(worker.id);
  let card = box.querySelector(passSelector(worker.id));
  if (!card) {
    box.insertAdjacentHTML("beforeend", renderWorkerCard({ ...worker, text: worker.text || "", pending: "" }));
    card = box.querySelector(passSelector(worker.id));
  }
  return card;
}

export function ensureWorkerStream(worker) {
  worker.id = workerBlockKey(worker.id);
  let block = streamBlocks.get(worker.id);
  if (block?.body) return block;
  const card = ensureWorkerCard(worker);
  if (!card) return null;
  block = {
    worker,
    body: card.querySelector(".ws-body"),
    statusEl: card.querySelector(".ws-status"),
    pending: worker.pending || "",
  };
  streamBlocks.set(worker.id, block);
  return block;
}

export function syncProgressWorkers() {
  const job = state.currentJob || {};
  Object.values(job.workers || {}).forEach((worker) => {
    const card = ensureWorkerCard(worker);
    if (!card) return;
    ensureWorkerStream(worker);
    const status = worker.status === "fail" ? "error" : (worker.status || "running");
    card.className = `worker ${status}`;
    const nameEl = card.querySelector("strong");
    if (nameEl) nameEl.textContent = displayWorkerName(worker.name);
    const scopeEl = card.querySelector("small");
    if (scopeEl) scopeEl.textContent = formatWorkerScope(worker.scope);
    const statusEl = card.querySelector(".ws-status");
    if (statusEl) {
      statusEl.className = `ws-status ${status === "running" ? "ws-run" : status === "error" ? "ws-fail" : "ws-done"}`;
      statusEl.textContent = workerStatusLabel(worker);
    }
  });
  patchProgressStage();
  const box = document.querySelector("#worker-stream");
  if (box && box.scrollHeight - box.scrollTop - box.clientHeight < 48) box.scrollTop = box.scrollHeight;
}

export function flushWorkerDeltas() {
  const job = state.currentJob;
  if (job) job.raf = 0;
  const box = document.querySelector("#worker-stream");
  const stick = box && box.scrollHeight - box.scrollTop - box.clientHeight < 48;
  for (const block of streamDirty) {
    if (!block.pending || !block.body) continue;
    block.body.appendChild(document.createTextNode(block.pending));
    block.worker.text = `${block.worker.text || ""}${block.pending}`;
    block.pending = "";
  }
  streamDirty.clear();
  if (box && stick) box.scrollTop = box.scrollHeight;
}

export async function finishJob(jobId) {
  if (!state.currentJob || state.currentJob.id !== jobId) return;
  stopJobWatch();
  try {
    state.currentReport = await api(`/api/jobs/${encodeURIComponent(jobId)}/report`);
    state.activeIssue = 0;
    state.hiddenIssues = new Set();
    state.currentJob = null;
    go("review");
  } catch (error) {
    showError(error);
    renderCheck();
  }
}

export function watchJob(jobId) {
  stopJobWatch();
  const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/stream`, { withCredentials: true });
  state.currentJob.stream = source;
  state.currentJob.streamOpened = false;
  state.currentJob.poll = window.setInterval(async () => {
    if (!state.currentJob || state.currentJob.id !== jobId) return;
    try {
      const status = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      state.currentJob.stage = status.stage || state.currentJob.stage;
      patchProgressStage();
      if (status.status === "done") {
        await finishJob(jobId);
      } else if (status.status === "error") {
        stopJobWatch();
        toast("Проверка не завершена", status.error || "Повторите попытку.", "error");
        state.currentJob = null;
        renderCheck();
      }
    } catch {}
  }, 1200);
  source.addEventListener("open", () => {
    if (state.currentJob?.stream === source) state.currentJob.streamOpened = true;
  });
  source.addEventListener("start", (event) => {
    const data = safeStreamData(event, {});
    const id = workerBlockKey(data.id);
    if (!state.currentJob || !id) return;
    if (!state.currentJob.workers[id]) {
      state.currentJob.workers[id] = {
        id,
        name: data.worker || "Проверка",
        scope: data.scope || "",
        status: "running",
        text: "",
        pending: "",
        found: null,
      };
    }
    ensureWorkerStream(state.currentJob.workers[id]);
    syncProgressWorkers();
  });
  source.addEventListener("delta", (event) => {
    const data = safeStreamData(event, {});
    workerPending(data.id, data.text || "");
  });
  source.addEventListener("end", (event) => {
    const data = safeStreamData(event, {});
    const worker = state.currentJob?.workers[workerBlockKey(data.id)];
    if (worker) {
      if (streamDirty.size) flushWorkerDeltas();
      worker.status = data.status === "fail" || data.status === "error" ? "error" : "done";
      worker.found = data.found;
      if (!String(worker.text || "").trim()) {
        worker.text = data.error || (worker.found > 0 ? `(нашёл замечаний: ${worker.found})` : "(замечаний нет)");
        const body = streamBlocks.get(worker.id)?.body;
        if (body && !body.textContent.trim()) body.textContent = worker.text;
      }
    }
    if (state.currentJob) {
      state.currentJob.found = Object.values(state.currentJob.workers).reduce((sum, item) => sum + (Number(item.found) || 0), 0);
    }
    syncProgressWorkers();
  });
  source.addEventListener("finished", async (event) => {
    const data = safeStreamData(event, {});
    try { source.close(); } catch {}
    if (data.status === "error") {
      stopJobWatch();
      toast("Проверка не завершена", data.error || "Повторите попытку.", "error");
      state.currentJob = null;
      renderCheck();
      return;
    }
    await finishJob(jobId);
  });
  source.onerror = () => {
    if (!state.currentJob?.streamOpened) return;
    try { source.close(); } catch {}
    if (state.currentJob?.stream === source) state.currentJob.stream = null;
    if (state.currentJob?.id === jobId) {
      toast("Потеряна связь с сервером", "Ход проверки виден не полностью. Результат придёт после завершения.", "error");
    }
  };
}

export function normalizedIssues() {
  const issues = state.currentReport?.issues || [];
  return issues.map((issue, index) => ({
    id: issue.id ?? index,
    severity: issue.severity || "warning",
    line: (issue.line ?? issue.line_number ?? issue.block_index ?? index) + (issue.block_index !== undefined ? 1 : 0),
    message: issue.message || issue.description || issue.title || "Замечание",
    fragment: issue.fragment || issue.match || issue.span_text || issue.text || "",
    recommendation: issue.recommendation || issue.replacement || issue.suggestion || issue.replace || "",
    rule: issue.rule || issue.rule_id || issue.type || "Проверка",
    engine: issue.engine || issue.source || "LLM",
    context: issue.context || issue.line_text || issue.text || issue.fragment || "",
    raw: issue,
  }));
}

export function reportText(report = state.currentReport) {
  if (!report) return "";
  if (report.text || report.content) return report.text || report.content;
  if (Array.isArray(report.blocks)) return report.blocks.map((block) => block.text || block.plain || "").join("\n\n");
  return "";
}

export function visibleIssues() {
  return normalizedIssues().filter((issue, index) => {
    if (state.hiddenIssues.has(index)) return false;
    return state.issueFilter === "all" || issue.severity === state.issueFilter;
  });
}

export function demoReport() {
  return {
    source: "Настройка сетевой защиты.docx",
    document: "Настройка сетевой защиты.docx",
    blocks: [
      { index: 0, type: "heading", level: 1, text: "Подключение защищённого соединения" },
      { index: 1, type: "paragraph", text: "Перед началом работы убедитесь, что устройство подключено к корпоративной сети." },
      { index: 2, type: "paragraph", text: "Для настройки соединения Вам необходимо произвести установку сертификата безопасности.", formatting: [{ start: 38, end: 58, bold: false, italic: true, underline: false }] },
      { index: 3, type: "list_item", list_kind: "bullet", list_depth: 0, list_index: 1, text: "Откройте раздел «Сетевые параметры»." },
      { index: 4, type: "list_item", list_kind: "bullet", list_depth: 0, list_index: 2, text: "Нажмите кнопку «Добавить подключение» вместо «кликните на»." },
      { index: 5, type: "paragraph", text: "Система автоматически проверит конфигурацию. Проверка может занять порядка 2-3 минут.", formatting: [{ start: 0, end: 7, bold: true, italic: false, underline: false }] },
    ],
    issues: [
      { severity: "error", block_index: 2, line: 2, message: "Отглагольное существительное", fragment: "произвести установку", recommendation: "установить", rule: "Ясность действия", engine: "Vale" },
      { severity: "warning", block_index: 4, line: 4, message: "Неточный глагол интерфейса", fragment: "кликните на", recommendation: "нажмите", rule: "Элементы интерфейса", engine: "Vale" },
      { severity: "suggestion", block_index: 5, line: 5, message: "Приблизительная оценка", fragment: "порядка 2-3 минут", recommendation: "2–3 минуты", rule: "Числа и интервалы", engine: "LanguageTool" },
    ],
  };
}

export function renderReview() {
  if (!state.currentReport) state.currentReport = demoReport();
  const issues = normalizedIssues();
  const shown = visibleIssues();
  if (state.activeIssue >= shown.length) state.activeIssue = Math.max(0, shown.length - 1);
  const counts = {
    error: issues.filter((item) => item.severity === "error").length,
    warning: issues.filter((item) => item.severity === "warning").length,
    suggestion: issues.filter((item) => item.severity === "suggestion").length,
  };
  renderShell(`
    <div class="review-view">
      ${state.currentReport.partial ? `<div class="partial-status" role="status">${icon("icon-activity")}<span>${escapeHTML(state.currentReport.partial_message || "Часть проверок не выполнена.")}</span></div>` : ""}
      <section class="review-toolbar">
        <div class="review-toolbar-title"><strong>Очередь решений</strong><small>${shown.length} показано</small></div>
        <div class="chip-row" role="group" aria-label="Важность">
          ${filterChip("all", "Все", issues.length)}
          ${filterChip("error", "Ошибки", counts.error)}
          ${filterChip("warning", "Замечания", counts.warning)}
          ${filterChip("suggestion", "Советы", counts.suggestion)}
        </div>
        <button class="button secondary new-check" type="button">${icon("icon-plus")}<span>Новая проверка</span></button>
      </section>
      <section class="review-workspace">
        <article class="document-pane" aria-label="Текст документа">
          <div class="pane-bar"><span>${escapeHTML(state.currentReport.document || state.currentReport.source || state.currentReport.filename || "Текст")}</span><span>${issues.length} находок</span></div>
          <div class="document-scroll">
            <div class="document-content">${renderDocument(state.currentReport, shown)}</div>
            <aside class="document-map" aria-label="Карта находок">${Array.from({ length: 22 }, () => "<span></span>").join("")}${shown.slice(0, 12).map((issue, index) => `<button class="map-point ${issue.severity}" style="--y:${Math.min(88, 8 + index * 7)}%" type="button" aria-label="${escapeHTML(issue.message)}" data-issue-index="${index}"></button>`).join("")}</aside>
          </div>
        </article>
        <aside class="issues-pane" aria-label="Находки">
          <div class="issues-list">${shown.length ? shown.map(renderIssue).join("") : `<div class="empty-state">${icon("icon-check")}<div><h3>Находок нет</h3><p>Измените фильтр или начните новую проверку.</p></div></div>`}</div>
          <footer class="issues-footer"><span><kbd>J</kbd> <kbd>K</kbd> переход</span><span><kbd>H</kbd> скрыть</span><button class="restore-hidden" type="button">Скрытые: ${state.hiddenIssues.size}</button></footer>
        </aside>
      </section>
    </div>`);
  bindReview();
}

export function filterChip(value, label, count) {
  return `<button class="chip ${state.issueFilter === value ? "active" : ""}" type="button" data-issue-filter="${value}" aria-pressed="${state.issueFilter === value}">${value !== "all" ? `<i class="${value}"></i>` : ""}${label} <b>${count}</b></button>`;
}

export function markDocumentText(text, entries) {
  return renderRichText(text, [], entries);
}

export function renderRichText(text, formatting, marks) {
  const source = text || "";
  const events = [];
  (formatting || []).forEach((span, key) => {
    const start = Math.max(0, Number(span.start) || 0);
    const end = Math.min(source.length, Number(span.end) || 0);
    if (end <= start) return;
    if (span.bold) {
      events.push({ i: start, open: 1, tag: "strong", k: `b${key}` });
      events.push({ i: end, open: 0, tag: "strong", k: `b${key}` });
    }
    if (span.italic) {
      events.push({ i: start, open: 1, tag: "em", k: `i${key}` });
      events.push({ i: end, open: 0, tag: "em", k: `i${key}` });
    }
    if (span.underline) {
      events.push({ i: start, open: 1, tag: "u", k: `u${key}` });
      events.push({ i: end, open: 0, tag: "u", k: `u${key}` });
    }
  });
  (marks || []).forEach(({ issue, index }) => {
    const fragment = issue.fragment;
    if (!fragment) return;
    const at = source.indexOf(fragment);
    if (at < 0) return;
    const active = index === state.activeIssue ? " active" : "";
    events.push({
      i: at,
      open: 1,
      tag: "mark",
      k: `m${index}`,
      attrs: `class="finding ${issue.severity}${active}" data-issue-index="${index}"`,
    });
    events.push({ i: at + fragment.length, open: 0, tag: "mark", k: `m${index}` });
  });
  events.sort((a, b) => a.i - b.i || a.open - b.open || String(a.k).localeCompare(String(b.k)));
  let html = "";
  let cursor = 0;
  events.forEach((event) => {
    if (event.i > cursor) html += escapeHTML(source.slice(cursor, event.i)).replaceAll("\n", "<br>");
    html += event.open ? `<${event.tag}${event.attrs ? ` ${event.attrs}` : ""}>` : `</${event.tag}>`;
    cursor = event.i;
  });
  html += escapeHTML(source.slice(cursor)).replaceAll("\n", "<br>");
  return html;
}

export function blockBodyTag(block) {
  const type = block.type || "paragraph";
  if (type === "heading") return `h${Math.min(4, Math.max(1, Number(block.level) || 2))}`;
  if (type === "blockquote") return "blockquote";
  if (type === "fence" || type === "code_block" || type === "pre") return "pre";
  return "p";
}

export function renderDocument(report, issues) {
  if (Array.isArray(report?.blocks) && report.blocks.length) {
    return report.blocks.map((block, blockPosition) => {
      const blockIndex = block.index ?? blockPosition;
      const blockIssues = issues
        .map((issue, index) => ({ issue, index }))
        .filter(({ issue }) => (issue.raw.block_index ?? issue.raw.line) === blockIndex);
      const type = block.type || "paragraph";
      const text = block.text || block.plain || (Array.isArray(block.cells) ? block.cells.join(" · ") : "");
      const inner = renderRichText(text, block.formatting, blockIssues);
      const depth = Number(block.list_depth) || 0;
      const indent = type === "list_item" ? ` style="padding-left:${depth * 18}px"` : "";
      const marker = type === "list_item"
        ? (block.list_kind === "ordered" ? `${block.list_index || blockPosition + 1}.` : "•")
        : String(blockPosition + 1);
      const tag = blockBodyTag(block);
      return `<div class="document-block" data-type="${escapeHTML(type)}"${indent}><span class="block-number">${escapeHTML(String(marker))}</span><${tag}>${inner}</${tag}></div>`;
    }).join("");
  }
  const entries = issues.map((issue, index) => ({ issue, index }));
  return markDocumentText(reportText(report) || "Текст недоступен", entries).split(/\n{2,}/).map((paragraph, index) => index === 0
    ? `<h3>${paragraph.replaceAll("\n", "<br>")}</h3>`
    : `<p>${paragraph.replaceAll("\n", "<br>")}</p>`).join("");
}

export function scrollChildIntoView(container, element) {
  if (!container || !element) return;
  const area = container.getBoundingClientRect();
  const box = element.getBoundingClientRect();
  if (box.top < area.top) container.scrollTop -= area.top - box.top - 24;
  else if (box.bottom > area.bottom) container.scrollTop += box.bottom - area.bottom + 24;
}

export function selectIssue(index, { focus = false } = {}) {
  const shown = visibleIssues();
  if (!shown.length) return;
  state.activeIssue = Math.max(0, Math.min(index, shown.length - 1));
  document.querySelectorAll(".issue").forEach((element) => {
    const active = Number(element.dataset.issueIndex) === state.activeIssue;
    element.classList.toggle("active", active);
    element.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll(".finding").forEach((element) => {
    element.classList.toggle("active", Number(element.dataset.issueIndex) === state.activeIssue);
  });
  document.querySelectorAll(".map-point").forEach((element) => {
    element.classList.toggle("active", Number(element.dataset.issueIndex) === state.activeIssue);
  });
  scrollChildIntoView(document.querySelector(".document-scroll"), document.querySelector(".document-scroll .finding.active"));
  const issue = document.querySelector(`.issue[data-issue-index="${state.activeIssue}"]`);
  scrollChildIntoView(document.querySelector(".issues-list"), issue);
  if (focus) issue?.focus({ preventScroll: true });
}

export function renderIssue(issue, index) {
  const label = issue.severity === "error" ? "Ошибка" : issue.severity === "suggestion" ? "Совет" : "Замечание";
  return `<button class="issue ${index === state.activeIssue ? "active" : ""}" type="button" data-issue-index="${index}" aria-pressed="${index === state.activeIssue}">
    <span class="badge ${issue.severity}">${label}</span><span class="issue-location">Строка ${escapeHTML(issue.line)}${issue.engine ? ` · ${escapeHTML(issue.engine)}` : ""}</span>
    <strong>${escapeHTML(issue.message)}</strong>
    ${issue.fragment ? `<span class="issue-quote">«${escapeHTML(issue.fragment)}»</span>` : ""}
    ${issue.recommendation ? `<span class="issue-fix">${issue.fragment ? `<del>${escapeHTML(issue.fragment)}</del>` : ""}<ins>${escapeHTML(issue.recommendation)}</ins></span>` : ""}
    <span class="issue-rule">${escapeHTML(issue.rule)}${icon("icon-arrow")}</span>
  </button>`;
}

export function bindReview() {
  window.requestAnimationFrame(() => selectIssue(state.activeIssue));
  document.querySelectorAll("[data-issue-filter]").forEach((button) => button.addEventListener("click", () => {
    state.issueFilter = button.dataset.issueFilter;
    state.activeIssue = 0;
    renderReview();
  }));
  document.querySelectorAll("[data-issue-index]").forEach((element) => element.addEventListener("click", (event) => {
    event.preventDefault();
    selectIssue(Number(element.dataset.issueIndex) || 0, { focus: element.classList.contains("issue") });
  }));
  document.querySelector(".new-check")?.addEventListener("click", () => {
    state.sourceFile = null;
    go("check");
  });
  document.querySelector(".restore-hidden")?.addEventListener("click", () => {
    state.hiddenIssues.clear();
    renderReview();
  });
}

export async function exportReport() {
  if (!state.currentReport) return;
  try {
    const issues = normalizedIssues().filter((_, index) => !state.hiddenIssues.has(index)).map((item) => item.raw);
    const blob = await api("/api/report-issues", {
      method: "POST",
      body: JSON.stringify({ issues, source: state.currentReport.document || state.currentReport.source || "Текст" }),
    });
    downloadBlob(blob, "report.xlsx");
  } catch (error) {
    showError(error);
  }
}


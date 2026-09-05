import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export function stopWatchPoll() {
  window.clearInterval(state.watchPoll);
  state.watchPoll = 0;
}

export function watchAuthLabel(kind) {
  return { none: "Без входа", basic: "HTTP Basic", form: "Форма на сайте" }[kind] || "Без входа";
}

export function watchStatusLabel(status) {
  return { pending: "не проверялась", same: "без изменений", changed: "изменилась", error: "ошибка" }[status] || status || "не проверялась";
}

export function watchStatusBadge(status, always = false) {
  if (status === "changed") return `<span class="badge warning">изменилась</span>`;
  if (status === "error") return `<span class="badge error">ошибка</span>`;
  if (!always) return "";
  return `<span class="badge">${escapeHTML(watchStatusLabel(status))}</span>`;
}

export function watchGroupBadge(group) {
  if (group.running) return "";
  if (Number(group.changed_count)) return `<span class="badge warning">изменилась</span>`;
  if (Number(group.error_count)) return `<span class="badge error">ошибка</span>`;
  return "";
}

export function watchPageBadge(page) {
  if (page.running) return "";
  if (page.last_status === "changed") return `<span class="badge warning">изменилась</span>`;
  if (page.last_status === "error" || page.last_error) return `<span class="badge error">ошибка</span>`;
  return "";
}

export function watchPath(groupId, pageId) {
  if (pageId) return `watch/${groupId}/${pageId}`;
  if (groupId) return `watch/${groupId}`;
  return "watch";
}

export function openWatch(groupId, pageId) {
  const route = watchPath(groupId, pageId);
  if (window.location.hash === `#/${route}`) {
    state.watch.groupId = groupId || null;
    state.watch.pageId = pageId || null;
    renderWatch();
    return;
  }
  go(route);
}

export async function refreshWatchBadge(groups) {
  if (!groups) {
    try { groups = (await api("/api/watch/groups")).groups || []; } catch { groups = []; }
  }
  state.watchChanged = groups.reduce((sum, group) => sum + (group.changed_count || 0), 0);
  const link = document.querySelector('.primary-nav a[href="#/watch"]');
  if (!link) return;
  let badge = link.querySelector(".nav-count");
  if (state.watchChanged) {
    if (!badge) {
      badge = document.createElement("b");
      badge.className = "nav-count";
      link.append(badge);
    }
    badge.textContent = String(state.watchChanged);
  } else {
    badge?.remove();
  }
}

export function bindWatchAuthFields(form) {
  const update = () => {
    const kind = form.elements.auth_kind.value;
    form.querySelectorAll("[data-watch-auth]").forEach((row) => {
      row.hidden = !row.dataset.watchAuth.split(" ").includes(kind);
    });
  };
  form.elements.auth_kind.addEventListener("change", update);
  update();
}

export function watchAuthFields(group = {}) {
  const kind = group.auth_kind || "none";
  const passwordHint = group.has_password ? "Ключ задан, оставь пустым, чтобы не менять" : "";
  return `<label class="field"><span>Вход</span><select name="auth_kind">
      <option value="none" ${kind === "none" ? "selected" : ""}>Без входа</option>
      <option value="form" ${kind === "form" ? "selected" : ""}>Форма на сайте</option>
      <option value="basic" ${kind === "basic" ? "selected" : ""}>HTTP Basic</option>
    </select></label>
    <label class="field" data-watch-auth="form"><span>Страница входа</span><input name="login_url" value="${escapeHTML(group.login_url || "")}" placeholder="https://portal.example/login"></label>
    <label class="field" data-watch-auth="basic form"><span>Логин</span><input name="username" value="${escapeHTML(group.username || "")}" autocomplete="off"></label>
    <label class="field" data-watch-auth="basic form"><span>Пароль</span><input name="password" type="password" autocomplete="new-password">${passwordHint ? `<small class="field-hint">${passwordHint}</small>` : ""}</label>
    <details class="watch-auth-extra" data-watch-auth="form">
      <summary>Имена полей формы</summary>
      <div class="field-row">
        <label class="field"><span>Поле логина</span><input name="username_field" value="${escapeHTML(group.username_field || "username")}"></label>
        <label class="field"><span>Поле пароля</span><input name="password_field" value="${escapeHTML(group.password_field || "password")}"></label>
      </div>
    </details>`;
}

export function watchGroupFields(group = {}) {
  return `<label class="field"><span>Название</span><input name="name" required value="${escapeHTML(group.name || "")}" placeholder="Клиентский портал"></label>
    ${watchAuthFields(group)}`;
}

export function watchFormPayload(form) {
  const body = {
    name: form.elements.name.value.trim(),
    auth_kind: form.elements.auth_kind.value,
    login_url: form.elements.login_url.value.trim(),
    username: form.elements.username.value.trim(),
    username_field: form.elements.username_field.value.trim() || "username",
    password_field: form.elements.password_field.value.trim() || "password",
  };
  if (form.elements.password.value) body.password = form.elements.password.value;
  return body;
}

export function showWatchGroupDialog(group) {
  modal({
    title: "Группа",
    body: `<form class="dialog-body">${watchGroupFields(group)}<div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      bindWatchAuthFields(form);
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector("[type=submit]");
        setBusy(button, true);
        try {
          await api(`/api/watch/groups/${encodeURIComponent(group.id)}`, { method: "PATCH", body: JSON.stringify(watchFormPayload(form)) });
          close();
          toast("Группа сохранена");
          openWatch(group.id);
        } catch (error) {
          showError(error);
          setBusy(button, false);
        }
      });
    },
  });
}

export function bindWatchUrlBar(groupId) {
  const form = document.querySelector(".watch-url-bar");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = form.elements.url.value.trim();
    if (!url) return;
    const button = form.querySelector("[type=submit]");
    setBusy(button, true, "Добавление…");
    try {
      await api(`/api/watch/groups/${encodeURIComponent(groupId)}/pages`, { method: "POST", body: JSON.stringify({ url, title: form.elements.title.value.trim() }) });
      toast("Адрес добавлен");
      openWatch(groupId);
    } catch (error) {
      showError(error);
      setBusy(button, false);
    }
  });
}

export function renderWatchComposer({ back = false } = {}) {
  renderShell(`
    <div class="page">
      ${back ? `<div class="page-head"><div><button class="text-link back-watch" type="button">${icon("icon-arrow")} Наблюдение</button></div></div>` : ""}
      <form class="check-layout watch-setup">
        <section class="panel elevated source-picker">
          <div class="source-content">
            <label class="field"><span>Название</span><input name="name" required placeholder="Клиентский портал" autocomplete="off"></label>
            <label class="field"><span>Адреса</span><textarea name="urls" rows="10" placeholder="https://" spellcheck="false"></textarea></label>
          </div>
        </section>
        <aside class="check-options">
          <section class="panel">
            <div class="panel-body">
              ${watchAuthFields()}
              <button class="button primary start-check" type="submit">Создать</button>
            </div>
          </section>
        </aside>
      </form>
    </div>`);
  const form = document.querySelector(".watch-setup");
  bindWatchAuthFields(form);
  form.elements.name.focus();
  document.querySelector(".back-watch")?.addEventListener("click", () => go("watch"));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("[type=submit]");
    const urls = form.elements.urls.value.split(/\n/).map((line) => line.trim()).filter(Boolean);
    setBusy(button, true);
    try {
      const saved = await api("/api/watch/groups", { method: "POST", body: JSON.stringify(watchFormPayload(form)) });
      for (const url of urls) {
        await api(`/api/watch/groups/${encodeURIComponent(saved.id)}/pages`, { method: "POST", body: JSON.stringify({ url }) });
      }
      toast("Группа создана");
      openWatch(saved.id);
    } catch (error) {
      showError(error);
      setBusy(button, false);
    }
  });
}

function plural(n, one, few, many) {
  const mod10 = Number(n) % 10;
  const mod100 = Number(n) % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function watchChangeSummary(diff) {
  const n = watchChanges(diff).length;
  if (!n) return "";
  return `${n} ${plural(n, "изменение", "изменения", "изменений")}`;
}

// Один список обычным языком: «что было — что стало». Пути вида article#0
// и слова вроде «атрибут» человеку не нужны — остаются только в API.
export function watchChanges(diff) {
  const out = [];
  const hunks = diff?.hunks || [];
  const ui = (diff?.ui || []).filter((e) => e.kind !== "more");
  const uiAdded = new Set(ui.filter((e) => e.kind === "added").map((e) => e.new_text || ""));
  const uiRemoved = new Set(ui.filter((e) => e.kind === "removed").map((e) => e.old_text || ""));
  for (let i = 0; i < hunks.length; i += 1) {
    const cur = hunks[i];
    const nxt = hunks[i + 1];
    if (!cur || cur.op === "eq" || cur.op === "skip") continue;
    if (cur.op === "del" && nxt?.op === "add") {
      out.push({ text: `Было «${(cur.lines || []).join(" ")}», стало «${(nxt.lines || []).join(" ")}».` });
      i += 1;
      continue;
    }
    // Добавление/удаление, которое уже описано событием интерфейса
    // (там есть куда ведёт ссылка), второй раз не повторяем.
    if (cur.op === "del" && uiRemoved.has((cur.lines || []).join(" "))) continue;
    if (cur.op === "add" && uiAdded.has((cur.lines || []).join(" "))) continue;
    if (cur.op === "del") out.push({ text: `Убрали текст «${(cur.lines || []).join(" ")}».` });
    if (cur.op === "add") out.push({ text: `Добавился текст «${(cur.lines || []).join(" ")}».` });
  }
  // Та же правка текста видна и в структуре — второй раз её не повторяем.
  const textCovered = out.length > 0;
  for (const event of ui) {
    if (event.kind === "text" && textCovered) continue;
    const sentence = watchUiSentence(event);
    if (sentence) out.push({ text: sentence });
  }
  return out;
}

export function renderWatchChanges(diff, { status = "", error = "" } = {}) {
  if (error || diff?.page?.last_error) {
    const msg = error || diff.page.last_error;
    return `<div class="empty-state">${icon("icon-eye-off")}<div><h3>Страница не загрузилась</h3><p>${escapeHTML(msg)}</p><p class="empty-hint">Проверь адрес и вход группы, затем нажми «Проверить».</p></div></div>`;
  }
  const items = watchChanges(diff);
  if (!items.length) {
    if (status === "pending") return `<div class="empty-state">${icon("icon-clock")}<div><h3>Ещё не проверялась</h3><p>Нажми «Проверить», чтобы снять первый снимок.</p></div></div>`;
    if (status === "same") return `<div class="empty-state">${icon("icon-check")}<div><h3>Без изменений</h3><p>С прошлого снимка ничего не поменялось.</p></div></div>`;
    return `<div class="empty-state">${icon("icon-eye")}<div><h3>Сравнить пока нечего</h3><p>Нужны два снимка: проверь страницу дважды.</p></div></div>`;
  }
  return `<ol class="watch-changes">${items.map((item) => `<li>${escapeHTML(item.text)}</li>`).join("")}</ol>`;
}

function watchUiSentence(event) {
  const text = event.new_text || event.old_text || "";
  if (event.kind === "added") {
    const href = (event.attrs && event.attrs.href) || "";
    if (text && href && href !== text) return `Добавили ссылку «${text}» — ведёт на ${href}.`;
    if (text) return `Добавили «${text}».`;
    return href ? `Добавили ссылку — ведёт на ${href}.` : "Что-то добавили на страницу.";
  }
  if (event.kind === "removed") return text ? `Убрали «${text}».` : "Что-то убрали со страницы.";
  if (event.kind === "moved") return text ? `«${text}» переставили в другое место страницы.` : "Что-то переставили в другое место.";
  if (event.kind === "tag") {
    const from = event.old_tag || "";
    const to = event.tag || "";
    if (text && from && to && from !== to) return `«${text}» оформили иначе (было ${from}, стало ${to}), смысл тот же.`;
    return text ? `«${text}» оформили иначе, смысл тот же.` : "Что-то оформили иначе, смысл тот же.";
  }
  if (event.kind === "attr") {
    const from = (event.old_attrs && event.old_attrs.href) || "";
    const to = (event.attrs && event.attrs.href) || "";
    if (text && from && to && from !== to) return `Ссылка «${text}» теперь ведёт на ${to} (было ${from}).`;
    if (from && to && from !== to) return `Одна из ссылок теперь ведёт на ${to} (было ${from}).`;
    return text ? `У «${text}» поменялась ссылка.` : "У одной из ссылок поменялся адрес.";
  }
  if (event.kind === "text") return `Было «${event.old_text}», стало «${event.new_text}».`;
  return "";
}

// Живая копия: сохранённое тело страницы в песочнице, без скриптов.
// Подсветка уже стоит в разметке (классы pvwatch-is-*), фрейм только
// показывает её и держит высоту по содержимому.
export function watchCopyUrl(pageId) {
  return `/api/watch/pages/${encodeURIComponent(pageId)}/copy`;
}

export function renderWatchCopy(diff, pageId) {
  if (!diff?.has_copy) return "";
  return `<div class="watch-copy-wrap"><iframe class="watch-copy" title="Как страница выглядит сейчас" sandbox="" loading="lazy" src="${watchCopyUrl(pageId)}"></iframe></div>`;
}

export function bindWatchCopy() {
  const frame = document.querySelector(".watch-copy");
  if (!frame) return;
  const fit = () => {
    try {
      const doc = frame.contentDocument;
      if (!doc) return;
      frame.style.height = `${Math.min(Math.max(doc.documentElement.scrollHeight, 200), 1200)}px`;
    } catch { /* чужой документ — высоту не трогаем */ }
  };
  frame.addEventListener("load", fit);
}

export async function startWatchRun(path) {
  try {
    await api(path, { method: "POST", body: "{}" });
    toast("Проверка запущена");
    renderWatch();
  } catch (error) {
    showError(error);
  }
}

export function watchCount(n) {
  const count = Number(n) || 0;
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word = mod10 === 1 && mod100 !== 11 ? "адрес" : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "адреса" : "адресов";
  return `${count} ${word}`;
}

export function watchPageMeta(page) {
  if (page.running) return "Проверяем…";
  if (page.last_error) return page.last_error;
  const checked = page.last_checked_at ? `проверено ${formatDate(page.last_checked_at, false)}` : "";
  if (page.last_status === "pending" || !page.last_checked_at) return "Ещё не проверялась";
  if (page.last_status === "changed") {
    const changed = page.last_changed_at ? `изменилась ${formatDate(page.last_changed_at, false)}` : "изменилась";
    return checked ? `${changed} · ${checked}` : changed;
  }
  if (page.last_status === "error") return checked || "Не загрузилась";
  return checked ? `Без изменений · ${checked}` : "Без изменений";
}

export function watchGroupMeta(group) {
  // Одна строка обычным языком: сколько адресов и что с ними.
  const total = Number(group.page_count) || 0;
  const changed = Number(group.changed_count) || 0;
  const errors = Number(group.error_count) || 0;
  const locked = group.auth_kind && group.auth_kind !== "none" ? " · со входом" : "";
  if (!total) return `Пока нет адресов${locked}`;
  if (group.running) return `${watchCount(total)} · проверяем…${locked}`;
  if (changed) return `${watchCount(total)} · ${changed} ${plural(changed, "изменился", "изменились", "изменились")}${locked}`;
  if (errors) return `${watchCount(total)} · ${errors} ${plural(errors, "не загрузился", "не загрузились", "не загрузились")}${locked}`;
  const checked = group.last_run_at ? ` · проверено ${formatDate(group.last_run_at, false)}` : "";
  return `${watchCount(total)} · без изменений${checked}${locked}`;
}

export function watchGroupsSummary(groups) {
  const total = groups.reduce((n, group) => n + (Number(group.page_count) || 0), 0);
  const changed = groups.reduce((n, group) => n + (Number(group.changed_count) || 0), 0);
  const errors = groups.reduce((n, group) => n + (Number(group.error_count) || 0), 0);
  if (!groups.length) return "";
  if (changed) return `${groups.length} ${plural(groups.length, "группа", "группы", "групп")} · ${total} ${plural(total, "адрес", "адреса", "адресов")} · ${changed} ${plural(changed, "изменился", "изменились", "изменились")}`;
  if (errors) return `${groups.length} ${plural(groups.length, "группа", "группы", "групп")} · ${total} ${plural(total, "адрес", "адреса", "адресов")} · ошибка на ${errors}`;
  return `${groups.length} ${plural(groups.length, "группа", "группы", "групп")} · ${total} ${plural(total, "адрес", "адреса", "адресов")} · без изменений`;
}

export function watchPagesSummary(pages) {
  const total = pages.length;
  if (!total) return "";
  const changed = pages.filter((page) => page.last_status === "changed").length;
  const errors = pages.filter((page) => page.last_status === "error" || page.last_error).length;
  const running = pages.filter((page) => page.running).length;
  if (running) return `${watchCount(total)} · проверяем ${running}`;
  if (changed) return `${watchCount(total)} · ${changed} ${plural(changed, "изменился", "изменились", "изменились")}`;
  if (errors) return `${watchCount(total)} · ${errors} ${plural(errors, "не загрузился", "не загрузились", "не загрузились")}`;
  return `${watchCount(total)} · без изменений`;
}

export function bindWatchList() {
  document.querySelectorAll(".add-watch-group").forEach((button) => button.addEventListener("click", () => go("watch/new")));
  document.querySelectorAll("[data-watch-group]").forEach((row) => row.addEventListener("click", () => openWatch(row.dataset.watchGroup)));
}

export async function renderWatch() {
  stopWatchPoll();
  const { groupId, pageId } = state.watch;
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  if (state.route !== "watch") return;
  if (groupId === "new") {
    renderWatchComposer({ back: true });
    return;
  }
  if (!groupId) {
    let groups = [];
    try { groups = (await api("/api/watch/groups")).groups || []; } catch (error) { showError(error); }
    if (state.route !== "watch") return;
    refreshWatchBadge(groups);
    if (!groups.length) {
      renderWatchComposer();
      return;
    }
    const summary = watchGroupsSummary(groups);
    renderShell(`
      <div class="page watch-page">
        <div class="page-head watch-head">
          <div class="watch-title">
            <h2>Наблюдение</h2>
            <p class="watch-meta">${summary ? `<span>${escapeHTML(summary)}</span>` : "<span>Следим за страницами</span>"}</p>
            <p class="watch-meta watch-meta-dim">Показываем, что поменялось, обычным языком — без путей и тегов</p>
          </div>
          <div class="head-actions"><button class="button primary add-watch-group" type="button">${icon("icon-plus")}Группа</button></div>
        </div>
        <section class="panel fill-panel" aria-label="Группы">
          <div class="panel-head"><div><h3>Группы</h3><p>Нажми на группу, чтобы увидеть её адреса</p></div></div>
          <div class="panel-body">
            <div class="watch-list">${groups.map((group) => `<button class="file-row" type="button" data-watch-group="${escapeHTML(group.id)}">${icon("icon-eye")}<span><strong>${escapeHTML(group.name)}</strong><small>${escapeHTML(watchGroupMeta(group))}</small></span><span class="file-row-end">${watchGroupBadge(group)}${icon("icon-arrow")}</span></button>`).join("")}</div>
          </div>
        </section>
      </div>`);
    bindWatchList();
    return;
  }
  let group;
  try { group = await api(`/api/watch/groups/${encodeURIComponent(groupId)}`); } catch (error) {
    showError(error);
    go("watch");
    return;
  }
  if (state.route !== "watch") return;
  const pages = group.pages || [];
  if (pageId) {
    const page = pages.find((item) => item.id === pageId);
    let diff = { hunks: [], ui: [], page: page || { title: "Адрес", url: "" } };
    try { diff = await api(`/api/watch/pages/${encodeURIComponent(pageId)}/diff`); } catch (error) { showError(error); }
    if (state.route !== "watch") return;
    const running = Boolean(page?.running);
    const status = diff.page?.last_status || page?.last_status || "pending";
    const summary = watchChangeSummary(diff);
    const checked = diff.page?.last_checked_at || page?.last_checked_at;
    const changedAt = diff.page?.last_changed_at || page?.last_changed_at;
    renderShell(`
      <div class="page watch-page">
        <div class="page-head watch-head">
          <div class="watch-title">
            <button class="text-link back-watch" type="button">${icon("icon-arrow")} ${escapeHTML(group.name)}</button>
            <h2>${escapeHTML(diff.page?.title || page?.title || "Адрес")}</h2>
            <p class="watch-url"><a href="${escapeHTML(diff.page?.url || page?.url || "")}" target="_blank" rel="noopener">${escapeHTML(diff.page?.url || page?.url || "")}</a></p>
            <p class="watch-meta">
              ${watchStatusBadge(status, true)}
              ${summary ? `<span>${escapeHTML(summary)}</span>` : ""}
            </p>
            <p class="watch-meta watch-meta-dim">
              ${checked ? `проверено ${escapeHTML(formatDate(checked, false))}` : "ещё не проверялась"}${changedAt ? ` · изменилась ${escapeHTML(formatDate(changedAt, false))}` : ""}
            </p>
            ${diff.page?.last_error ? `<p class="field-hint" role="alert">${escapeHTML(diff.page.last_error)}</p>` : ""}
          </div>
          <div class="head-actions">
            <button class="button secondary run-watch-page" type="button" ${running ? "disabled" : ""}>${icon("icon-refresh")}${running ? "Проверяем…" : "Проверить"}</button>
            <button class="icon-button delete-watch-page" type="button" aria-label="Удалить адрес">${icon("icon-trash")}</button>
          </div>
        </div>
        ${running ? `<div class="watch-progress" role="status" aria-live="polite"><span class="watch-progress-dot"></span>Снимаю свежий снимок…</div>` : ""}
        <section class="panel fill-panel watch-diff-panel" aria-label="Что изменилось">
          <div class="panel-head"><div><h3>Что изменилось</h3><p>${summary ? escapeHTML(summary) : status === "same" ? "Со прошлого снимка ничего не поменялось" : status === "pending" ? "Первый снимок ещё не снят" : ""}</p></div></div>
          <div class="panel-body">
            ${renderWatchChanges(diff, { status: diff.page?.last_status, error: diff.page?.last_error })}
          </div>
        </section>
        ${diff?.has_copy ? `<section class="panel fill-panel" aria-label="Как страница выглядит сейчас">
          <div class="panel-head"><div><h3>Как это выглядит</h3><p>Настоящая страница, изменения подсвечены прямо в ней</p></div></div>
          <div class="panel-body">
            ${renderWatchCopy(diff, pageId)}
          </div>
        </section>` : ""}
      </div>`);
    document.querySelector(".back-watch").addEventListener("click", () => openWatch(groupId));
    bindWatchCopy();
    document.querySelector(".run-watch-page").addEventListener("click", () => startWatchRun(`/api/watch/pages/${encodeURIComponent(pageId)}/run`));
    document.querySelector(".delete-watch-page")?.addEventListener("click", () => {
      confirmAction({
        title: "Удалить адрес?",
        description: "Снимки этой страницы будут удалены.",
        async onConfirm() {
          await api(`/api/watch/pages/${encodeURIComponent(pageId)}`, { method: "DELETE" });
          toast("Адрес удалён");
          openWatch(groupId);
        },
      });
    });
    if (running) {
      // Прогон одной страницы идёт в фоне — опрашиваем, пока не закончится.
      state.watchPoll = window.setInterval(() => {
        if (state.route === "watch") renderWatch();
        else stopWatchPoll();
      }, 2000);
    }
    return;
  }
  const listSummary = watchPagesSummary(pages);
  const groupBadge = watchGroupBadge(group);
  const groupChecked = group.last_run_at ? `проверено ${formatDate(group.last_run_at, false)}` : "";
  renderShell(`
    <div class="page watch-page">
      <div class="page-head watch-head">
        <div class="watch-title">
          <button class="text-link back-watch" type="button">${icon("icon-arrow")} Наблюдение</button>
          <h2>${escapeHTML(group.name)}</h2>
          <p class="watch-meta">
            ${groupBadge}
            ${listSummary ? `<span>${escapeHTML(listSummary)}</span>` : "<span>Следим за адресами этой группы</span>"}
          </p>
          <p class="watch-meta watch-meta-dim">
            ${escapeHTML(watchAuthLabel(group.auth_kind))}${groupChecked ? ` · ${escapeHTML(groupChecked)}` : " · ещё не проверялась"}
          </p>
        </div>
        <div class="head-actions">
          <button class="icon-button edit-watch-group" type="button" aria-label="Изменить группу">${icon("icon-edit")}</button>
          <button class="icon-button delete-watch-group" type="button" aria-label="Удалить группу">${icon("icon-trash")}</button>
          <button class="button secondary run-watch-group" type="button" ${group.running ? "disabled" : ""}>${icon("icon-refresh")}${group.running ? "Проверяем…" : "Проверить"}</button>
        </div>
      </div>
      ${group.running ? `<div class="watch-progress" role="status" aria-live="polite"><span class="watch-progress-dot"></span>Снимаю свежие снимки…</div>` : ""}
      <section class="panel fill-panel" aria-label="Адреса">
        <div class="panel-head"><div><h3>Адреса</h3><p>${listSummary ? escapeHTML(listSummary) : "Вставь ссылку — снимем первый снимок"}</p></div></div>
        <div class="panel-body">
          <form class="watch-url-bar">
            <label class="field"><span>URL</span><input name="url" required type="url" inputmode="url" placeholder="https://" autocomplete="off"></label>
            <label class="field"><span>Название</span><input name="title" placeholder="Главная" autocomplete="off"></label>
            <button class="button primary" type="submit">${icon("icon-plus")}Добавить</button>
          </form>
          ${pages.length ? `<div class="watch-list">${pages.map((page) => {
            const label = page.title || page.url;
            const meta = watchPageMeta(page);
            const urlBit = page.title ? ` · ${page.url}` : "";
            return `<button class="file-row" type="button" data-watch-page="${escapeHTML(page.id)}">${icon("icon-link")}<span><strong>${escapeHTML(label)}</strong><small>${escapeHTML(meta)}${escapeHTML(urlBit)}</small></span><span class="file-row-end">${watchPageBadge(page)}${icon("icon-arrow")}</span></button>`;
          }).join("")}</div>` : `<div class="empty-state">${icon("icon-link")}<div><h3>Пока нет адресов</h3><p>Вставь ссылку выше и нажми «Добавить».</p></div></div>`}
        </div>
      </section>
    </div>`);
  document.querySelector(".back-watch").addEventListener("click", () => go("watch"));
  document.querySelector(".edit-watch-group")?.addEventListener("click", () => showWatchGroupDialog(group));
  document.querySelector(".delete-watch-group")?.addEventListener("click", () => {
    confirmAction({
      title: "Удалить группу?",
      description: "Страницы и снимки этой группы будут удалены.",
      async onConfirm() {
        await api(`/api/watch/groups/${encodeURIComponent(groupId)}`, { method: "DELETE" });
        toast("Группа удалена");
        go("watch");
      },
    });
  });
  document.querySelector(".run-watch-group")?.addEventListener("click", () => startWatchRun(`/api/watch/groups/${encodeURIComponent(groupId)}/run`));
  bindWatchUrlBar(groupId);
  document.querySelectorAll("[data-watch-page]").forEach((row) => row.addEventListener("click", () => openWatch(groupId, row.dataset.watchPage)));
  if (group.running) {
    state.watchPoll = window.setInterval(() => {
      if (state.route === "watch") renderWatch();
      else stopWatchPoll();
    }, 2000);
  }
}


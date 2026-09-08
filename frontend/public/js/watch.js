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
  if (status === "changed") return `<span class="badge warning">Изменилась</span>`;
  if (status === "error") return `<span class="badge error">Ошибка</span>`;
  if (!always) return "";
  return `<span class="badge">${escapeHTML(watchStatusLabel(status))}</span>`;
}

export function watchGroupBadge(group) {
  if (group.running) return "";
  if (Number(group.changed_count)) return `<span class="badge warning">Изменилась</span>`;
  if (Number(group.error_count)) return `<span class="badge error">Ошибка</span>`;
  return "";
}

export function watchPageBadge(page) {
  if (page.running) return "";
  if (page.last_status === "changed") return `<span class="badge warning">Изменилась</span>`;
  if (page.last_status === "error" || page.last_error) return `<span class="badge error">Ошибка</span>`;
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
      ${back ? `<div class="page-head"><div><button class="text-link back-watch" type="button">${icon("icon-arrow")} Мониторинг</button></div></div>` : ""}
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

const WATCH_TAG_LABEL = {
  p: "абзац", h1: "заголовок", h2: "заголовок", h3: "заголовок", h4: "заголовок",
  a: "ссылка", li: "пункт списка", ul: "список", ol: "список", button: "кнопка",
  img: "картинка", div: "блок", section: "раздел", article: "статья",
};

export function watchTagLabel(tag) {
  return WATCH_TAG_LABEL[tag] || "элемент";
}

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
    const oldText = (cur.op === "del" ? cur.lines : []).join(" ");
    const newText = (cur.op === "del" && nxt?.op === "add" ? nxt.lines : cur.op === "add" ? cur.lines : []).join(" ");
    if (cur.op === "del" && nxt?.op === "add") {
      out.push({ oldText, newText, loc: "текст" });
      i += 1;
      continue;
    }
    if (cur.op === "del" && uiRemoved.has(oldText)) continue;
    if (cur.op === "add" && uiAdded.has(newText)) continue;
    if (cur.op === "del") out.push({ oldText, newText: "", loc: "текст" });
    if (cur.op === "add") out.push({ oldText: "", newText, loc: "текст" });
  }
  const ordered = [...ui].sort((a, b) => (a.path || "").localeCompare(b.path || ""));
  const movedTexts = new Set(
    ordered.filter((e) => e.kind === "moved").flatMap((e) => [e.old_text || "", e.new_text || ""]).filter(Boolean),
  );
  const textCovered = out.some((item) => {
    const t = item.newText || item.oldText || "";
    return t && !movedTexts.has(t);
  });
  const moved = [];
  for (const event of ordered) {
    if (event.kind === "text" && textCovered) continue;
    if (event.kind === "text") {
      out.push({ oldText: event.old_text || "", newText: event.new_text || "", loc: watchTagLabel(event.tag), event, path: event.path || "" });
      continue;
    }
    if (event.kind === "moved") {
      moved.push(event);
      continue;
    }
    out.push({ oldText: "", newText: "", note: watchUiSentence(event), loc: watchTagLabel(event.tag), event, path: event.path || "" });
  }
  if (moved.length === 1) {
    const event = moved[0];
    const here = event.path ? event.path.split("/").slice(-2).join(" / ") : "";
    const there = (event.detail || "").split("→").map((s) => s.trim()).filter(Boolean);
    const from = there.length > 1 ? there[0].split("/").slice(-2).join(" / ") : "";
    const note = event.new_text || event.old_text
      ? `«${event.new_text || event.old_text}» был${from ? ` в ${from}` : ""}${here ? `, стал в ${here}` : ""}.`
      : "Элемент сместился.";
    out.push({ oldText: "", newText: "", note, loc: watchTagLabel(event.tag), event });
  } else if (moved.length > 1) {
    const names = [...new Set(moved.map((e) => e.new_text || e.old_text || "").filter(Boolean))].slice(0, 3);
    const first = [...moved].sort((a, b) => (a.path || "").localeCompare(b.path || ""))[0];
    const note = names.length
      ? `Переставили: ${names.map((n) => `«${n}»`).join(", ")}.`
      : "Элементы переставили местами.";
    out.push({
      oldText: "",
      newText: "",
      note,
      loc: watchTagLabel(first.tag),
      event: first,
    });
  }
  return out.filter((item) => {
    if (item.oldText === undefined) return true;
    const t = item.newText || item.oldText || "";
    if (!t) return true;
    if (movedTexts.has(t) && !item.event) return false;
    return true;
  });
}

export function watchKindBadge(kind) {
  return {
    added: "Новое",
    removed: "Убрано",
    moved: "Сдвиг",
    tag: "Вид",
    attr: "Вид",
    text: "Изменение",
  }[kind] || "Изменение";
}

export function renderWatchChanges(diff, { status = "", error = "" } = {}) {
  if (error || diff?.page?.last_error) {
    const msg = error || diff.page.last_error;
    return `<div class="empty-state">${icon("icon-eye-off")}<div><h3>Страница не загрузилась</h3><p>${escapeHTML(msg)}</p><p class="empty-hint">Проверь адрес и вход группы, затем нажми «Проверить».</p></div></div>`;
  }
  const items = watchChanges(diff);
  if (!items.length) {
    if (status === "pending") return `<div class="empty-state">${icon("icon-clock")}<div><h3>Ещё не проверялась</h3><p>Нажми «Проверить», чтобы снять первый снимок.</p></div></div>`;
    return `<div class="empty-state">${icon("icon-check")}<div><h3>Без изменений</h3><p>Проверь ещё раз позже.</p></div></div>`;
  }
  return `<div class="issues-list">${items.map((item, index) => {
    const count = item.event?.count > 1 ? `<span class="issue-count">×${item.event.count}</span>` : "";
    if (item.note) return `<button class="issue" type="button" data-issue-index="${index}"><span class="badge warning">${escapeHTML(watchKindBadge(item.event?.kind))}</span>${count}<strong>${escapeHTML(watchUiSentence(item.event))}</strong><span class="issue-location">${escapeHTML(item.loc || "структура")}</span></button>`;
    const quote = item.newText || item.oldText || "";
    return `<button class="issue" type="button" data-issue-index="${index}"><span class="badge warning">${escapeHTML(watchKindBadge(item.event?.kind))}</span>${count}<span class="issue-quote">«${escapeHTML(quote)}»</span>${item.oldText && item.newText && item.oldText !== item.newText ? `<span class="issue-fix"><del>${escapeHTML(item.oldText)}</del><ins>${escapeHTML(item.newText)}</ins></span>` : ""}</button>`;
  }).join("")}</div>`;
}

export function bindWatchIssues() {
  const frames = () => Array.from(document.querySelectorAll(".pvwatch-frame"));
  const docOf = (node) => {
    if (node?.ownerDocument && node.ownerDocument !== document) return node.ownerDocument;
    return frames().map((f) => f.contentDocument).find(Boolean) || null;
  };
  const marks = () => {
    const out = [];
    for (const frame of frames()) {
      const root = frame.contentDocument;
      if (!root) continue;
      out.push(...root.querySelectorAll(".pvwatch-is-text,.pvwatch-is-added,.pvwatch-is-removed,.pvwatch-ghost,.pvwatch-is-attr,.pvwatch-is-moved,.pvwatch-is-tag"));
    }
    return out;
  };
  const highlight = (targets) => {
    const nodes = targets.filter((node) => node && docOf(node));
    if (!nodes.length) return;
    new Set(nodes.map(docOf)).forEach((root) => {
      root.querySelectorAll(".pvwatch-active").forEach((node) => node.classList.remove("pvwatch-active"));
    });
    nodes.forEach((node) => node.classList.add("pvwatch-active"));
    try { nodes[0].scrollIntoView({ block: "center", behavior: "smooth" }); } catch { /* фрейм ещё грузится */ }
  };
  document.querySelectorAll(".review-workspace [data-issue-index]").forEach((element) => {
    if (element.dataset.watchBound) return;
    element.dataset.watchBound = "1";
    element.addEventListener("click", (click) => {
      click.preventDefault();
      click.stopPropagation();
      const items = watchChanges(window.__watchDiff || {});
      const item = items[Number(element.dataset.issueIndex)];
      const list = marks();
      if (!list.length) return;
      let targets = [];
      const wants = [...(item?.event?.paths || [item?.event?.path || item?.path || ""]),
                     ...(item?.event?.old_paths || [])].map((p) => String(p).trim()).filter(Boolean);
      for (const node of list) {
        if (wants.includes(node.dataset?.pvwatchPath || "")) targets.push(node);
      }
      if (!targets.length && wants.length) {
        const needle = (item?.event?.new_text || item?.event?.old_text || "").slice(0, 24);
        if (needle) targets = list.filter((node) => node.textContent?.includes(needle));
      }
      if (!targets.length) targets = [list[Number(element.dataset.issueIndex)] || null].filter(Boolean);
      if (!targets.length) return;
      document.querySelectorAll(".issues-list [data-issue-index].active").forEach((other) => other.classList.remove("active"));
      document.querySelector(`.issues-list [data-issue-index="${element.dataset.issueIndex}"]`)?.classList.add("active");
      highlight(targets);
    });
  });
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
    const oldCls = (event.old_attrs && event.old_attrs.class) || "";
    const newCls = (event.attrs && event.attrs.class) || "";
    const hadStyle = Boolean(event.old_attrs && event.old_attrs.style);
    const hasStyle = Boolean(event.attrs && event.attrs.style);
    if (oldCls !== newCls || hadStyle !== hasStyle) {
      const what = text ? `«${text}»` : "Элемент";
      if (oldCls && newCls && oldCls !== newCls) return `${what} перекрасился: было «${oldCls}», стало «${newCls}».`;
      if (!oldCls && newCls) return `${what} получил оформление «${newCls}».`;
      if (oldCls && !newCls) return `${what} потерял оформление «${oldCls}».`;
      return `${what} перекрасился — поменялись стили.`;
    }
    return text ? `У «${text}» поменялись свойства.` : "У элемента поменялись свойства.";
  }
  if (event.kind === "text") return `Было «${event.old_text}», стало «${event.new_text}».`;
  return "";
}

export function watchCopyUrl(pageId, version = "new") {
  return `/api/watch/pages/${encodeURIComponent(pageId)}/copy${version === "old" ? "?v=old" : ""}`;
}

export function watchShotUrl(pageId, version = "new") {
  return `/api/watch/pages/${encodeURIComponent(pageId)}/shot${version === "old" ? "?v=old" : ""}`;
}

// Шапка панели копии: адрес слева, справа переключатель версий и кнопки
// снимка. Сегменты вместо точек, подписи кнопок только в title.
export function renderWatchCopyBar(diff, pageId) {
  const url = escapeHTML(diff.page?.url || "");
  const tabs = diff.has_prev
    ? `<div class="copy-tabs" role="tablist">
         <button class="copy-tab active" type="button" role="tab" data-copy-version="new">Стало</button>
         <button class="copy-tab" type="button" role="tab" data-copy-version="old">Было</button>
       </div>`
    : "";
  const tools = `<div class="copy-tools">
      <a class="icon-button copy-shot" href="${watchShotUrl(pageId)}" download title="Скачать страницу картинкой">${icon("icon-download")}</a>
      <button class="icon-button copy-shot-clip" type="button" title="Скопировать картинку в буфер">${icon("icon-copy")}</button>
    </div>`;
  return `<span>${url}</span><div class="copy-actions">${tabs}${tools}</div>`;
}

export function renderWatchCopy(diff, pageId) {
  if (!diff?.has_copy) return "";
  // Приложение берёт копию отдельным запросом через src (свой CSP). Превью
  // статично и не умеет отдавать /copy, поэтому там копия приходит прямо в
  // diff.copy и грузится через srcdoc.
  const inline = Boolean(diff.copy);
  const frame = `<iframe class="pvwatch-frame" title="Сохранённая копия страницы" sandbox="allow-same-origin allow-popups" ${inline ? `data-watch-inline="1"` : `src="${watchCopyUrl(pageId)}"`} data-watch-frame="${escapeHTML(pageId)}"></iframe>`;
  return `<div class="document-content watch-copy" aria-live="polite">${frame}</div>`;
}

const COPY_DESKTOP_WIDTH = 1280;

function fitWatchCopy() {
  document.querySelectorAll(".document-content.watch-copy").forEach((box) => {
    const width = box.clientWidth;
    if (!width) return;
    const scale = Math.min(1, width / COPY_DESKTOP_WIDTH);
    box.style.setProperty("--pvw-scale", String(scale));
  });
}

// Панель справа дорисовывается позже, чем мы считаем масштаб: без
// слежения за размером копии копия остаётся в старом масштабе, и справа
// зияет пустота. ResizeObserver ловит и появление скроллбара, и сдвиг
// сетки, и поворот окна — слушать только window.resize недостаточно.
function watchCopyResize() {
  if (typeof ResizeObserver === "undefined") return;
  if (!window.__watchFitObserver) window.__watchFitObserver = new ResizeObserver(() => fitWatchCopy());
  window.__watchFitObserver.disconnect();
  document.querySelectorAll(".document-content.watch-copy").forEach((box) => window.__watchFitObserver.observe(box));
}

// Прошлое превью не умеет рендерить PNG на сервере: картинку копии
// собираем на клиенте через SVG foreignObject. Живое приложение ходит
// на /shot, где снимок делает chromium.
async function rasterizeCopy(html, width = 1280) {
  // Мёртвый iframe даёт честную высоту: стили копии рассчитаны на body,
  // в обрезанном div они бы не применились и высота вышла бы меньше.
  const probe = document.createElement("iframe");
  probe.style.cssText = `position:fixed;left:-2000px;top:0;width:${width}px;height:640px;border:0`;
  document.body.appendChild(probe);
  probe.contentDocument.open();
  probe.contentDocument.write(html);
  probe.contentDocument.close();
  // Документ в iframe записан синхронно, но раскладка считается на следующем
  // кадре: до неё scrollHeight вернул бы высоту пустого about:blank.
  await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
  const height = Math.min(12000, Math.max(640, probe.contentWindow.document.documentElement.scrollHeight));
  probe.remove();
  const style = (html.match(/<style>([\s\S]*?)<\/style>/i) || [])[1] || "";
  const body = (html.match(/<body[^>]*>([\s\S]*)<\/body>/i) || [])[1] || html;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`
    + `<foreignObject width="100%" height="100%">`
    + `<div xmlns="http://www.w3.org/1999/xhtml"><style>${style}</style>${body}</div>`
    + `</foreignObject></svg>`;
  const img = new Image();
  // blob: URL затирает canvas (foreignObject + toBlob не дадут картинку),
  // data: URL Chromium экспорт разрешает.
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0);
  return await new Promise((res) => canvas.toBlob(res, "image/png"));
}

async function watchShotBlob(pageId, version) {
  if (!isPreview) {
    const resp = await fetch(watchShotUrl(pageId, version), { credentials: "same-origin" });
    if (!resp.ok) throw new Error(String(resp.status));
    return await resp.blob();
  }
  const html = (version === "old" ? window.__watchDiff?.copy_old : window.__watchDiff?.copy) || "";
  if (!html) throw new Error("empty");
  return await rasterizeCopy(html);
}

export function bindWatchCopy(diff) {
  window.__watchDiff = diff;
  const inline = diff?.copy || "";
  document.querySelectorAll("[data-watch-frame]").forEach((frame) => {
    if (frame.dataset.watchReady) return;
    frame.dataset.watchReady = "1";
    frame.addEventListener("load", () => {
      // Внутренний документ после загрузки новый, слушатели на метках сгорели.
      delete frame.dataset.markBound;
      bindWatchIssues();
    });
    if (inline && frame.dataset.watchInline) frame.srcdoc = inline;
  });
  document.querySelectorAll(".copy-tab").forEach((tab) => {
    if (tab.dataset.copyBound) return;
    tab.dataset.copyBound = "1";
    tab.addEventListener("click", () => {
      const frame = document.querySelector(".pvwatch-frame");
      const pageId = frame?.dataset.watchFrame || state.watch.pageId;
      if (!frame || !pageId) return;
      const version = tab.dataset.copyVersion === "old" ? "old" : "new";
      document.querySelectorAll(".copy-tab").forEach((other) => {
        other.classList.toggle("active", other === tab);
      });
      if (frame.dataset.watchInline) {
        frame.srcdoc = (version === "old" ? diff.copy_old : diff.copy) || "";
      } else {
        frame.src = watchCopyUrl(pageId, version);
      }
      document.querySelectorAll(".copy-shot").forEach((a) => {
        a.href = watchShotUrl(pageId, version);
      });
      const clip = document.querySelector(".copy-shot-clip");
      if (clip) clip.dataset.version = version;
    });
  });
  if (isPreview) {
    // Статичное превью не отдаёт /shot: перехватываем ссылку и собираем
    // картинку на клиенте, чтобы кнопка в демо не вела в 404.
    document.querySelectorAll("a.copy-shot").forEach((a) => {
      if (a.dataset.copyBound) return;
      a.dataset.copyBound = "1";
      a.addEventListener("click", async (event) => {
        event.preventDefault();
        const pageId = state.watch.pageId || "";
        const version = a.href.includes("v=old") ? "old" : "new";
        try {
          const blob = await watchShotBlob(pageId, version);
          downloadBlob(blob, `stranica-${pageId}-${version}.png`);
        } catch {
          toast("Не удалось собрать картинку");
        }
      });
    });
  }
  const clip = document.querySelector(".copy-shot-clip");
  if (clip && !clip.dataset.copyBound) {
    clip.dataset.copyBound = "1";
    clip.addEventListener("click", async () => {
      const pageId = state.watch.pageId;
      if (!pageId) return;
      const version = clip.dataset.version === "old" ? "old" : "new";
      clip.disabled = true;
      try {
        const blob = await watchShotBlob(pageId, version);
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        toast("Картинка скопирована");
      } catch {
        toast("Браузер не дал доступ к буферу");
      } finally {
        clip.disabled = false;
      }
    });
  }
  fitWatchCopy();
  watchCopyResize();
  if (!window.__watchFitBound) {
    window.__watchFitBound = true;
    window.addEventListener("resize", fitWatchCopy);
  }
  bindWatchIssues();
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
  if (page.last_status === "pending" || !page.last_checked_at) return "Ещё не проверялась";
  if (page.last_status === "changed") {
    return page.last_changed_at ? `Изменилась ${formatDate(page.last_changed_at, false)}` : "Изменилась";
  }
  if (page.last_status === "error") return "Не загрузилась";
  return page.last_checked_at ? `Проверено ${formatDate(page.last_checked_at, false)}` : "Без изменений";
}

export function watchGroupMeta(group) {
  const total = Number(group.page_count) || 0;
  const changed = Number(group.changed_count) || 0;
  const errors = Number(group.error_count) || 0;
  if (!total) return "Пока нет адресов";
  if (group.running) return `${watchCount(total)}, проверяем…`;
  if (changed) return `${watchCount(total)}, ${changed} ${plural(changed, "изменился", "изменились", "изменились")}`;
  if (errors) return `${watchCount(total)}, ${errors} ${plural(errors, "не загрузился", "не загрузились", "не загрузились")}`;
  return group.last_run_at ? `${watchCount(total)}, проверено ${formatDate(group.last_run_at, false)}` : watchCount(total);
}

export function watchStats(parts) {
  return parts.filter(Boolean).map((text) => `<span>${escapeHTML(text)}</span>`).join("");
}

export function watchGroupsSummary(groups) {
  const total = groups.reduce((n, group) => n + (Number(group.page_count) || 0), 0);
  const changed = groups.reduce((n, group) => n + (Number(group.changed_count) || 0), 0);
  const errors = groups.reduce((n, group) => n + (Number(group.error_count) || 0), 0);
  if (!groups.length) return "";
  const head = `${groups.length} ${plural(groups.length, "группа", "группы", "групп")}, ${total} ${plural(total, "адрес", "адреса", "адресов")}`;
  if (changed) return `${head}, ${changed} ${plural(changed, "изменился", "изменились", "изменились")}`;
  if (errors) return `${head}, ошибка на ${errors}`;
  return head;
}

export function watchPagesSummary(pages) {
  const total = pages.length;
  if (!total) return "";
  const changed = pages.filter((page) => page.last_status === "changed").length;
  const errors = pages.filter((page) => page.last_status === "error" || page.last_error).length;
  const running = pages.filter((page) => page.running).length;
  if (running) return `${watchCount(total)}, проверяем ${running}`;
  if (changed) return `${watchCount(total)}, ${changed} ${plural(changed, "изменился", "изменились", "изменились")}`;
  if (errors) return `${watchCount(total)}, ${errors} ${plural(errors, "не загрузился", "не загрузились", "не загрузились")}`;
  return watchCount(total);
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
    const headStats = summary ? [summary] : [];
    renderShell(`
      <div class="page watch-page">
        <div class="page-head">
          <div>
            <h2>Мониторинг</h2>
            <p class="watch-stats">${headStats.length ? watchStats(headStats) : "Следим за страницами"}</p>
          </div>
          <div class="head-actions"><button class="button primary add-watch-group" type="button">${icon("icon-plus")}Группа</button></div>
        </div>
        <section class="panel fill-panel" aria-label="Группы">
          <div class="panel-head"><div><h3>Группы</h3></div></div>
          <div class="panel-body">
            <div class="watch-list">${groups.map((group) => `<button class="file-row" type="button" data-watch-group="${escapeHTML(group.id)}">${icon("icon-eye")}<span><strong>${escapeHTML(group.name)}</strong><small class="watch-stats">${watchStats([watchGroupMeta(group)])}</small></span><span class="file-row-end">${watchGroupBadge(group)}${icon("icon-arrow")}</span></button>`).join("")}</div>
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
    // Открыли страницу с непросмотренным изменением — снимаем бейдж у «Мониторинга».
    if (diff.page?.unseen || page?.unseen) {
      api(`/api/watch/pages/${encodeURIComponent(pageId)}/seen`, { method: "POST" })
        .then(() => refreshWatchBadge())
        .catch(() => {});
    }
    const running = Boolean(page?.running);
    const status = diff.page?.last_status || page?.last_status || "pending";
    const summary = watchChangeSummary(diff);
    const checked = diff.page?.last_checked_at || page?.last_checked_at;
    const checkedBit = checked ? `Проверено ${escapeHTML(formatDate(checked, false))}` : "Ещё не проверялась";
    const statBits = [checkedBit, summary || (status === "changed" ? "" : "Изменений нет")].filter(Boolean);
    renderShell(`
    <div class="review-view">
      <section class="review-toolbar">
        <div class="review-toolbar-title"><button class="text-link back-watch" type="button">${icon("icon-arrow")} ${escapeHTML(group.name)}</button><strong>${escapeHTML(diff.page?.title || page?.title || "Адрес")}</strong><small class="watch-stats">${watchStats(statBits)}</small></div>
        <div class="head-actions">
          <button class="button secondary run-watch-page" type="button" ${running ? "disabled" : ""}>${icon("icon-refresh")}${running ? "Проверяем…" : "Проверить"}</button>
          <a class="button secondary watch-original" href="${escapeHTML(diff.page?.url || page?.url || "")}" target="_blank" rel="noopener" title="Живой сайт в новой вкладке — копия слева это сохранённый снимок">${icon("icon-link")}Оригинал</a>
          <button class="icon-button delete-watch-page" type="button" aria-label="Удалить адрес" title="Удалить адрес">${icon("icon-trash")}</button>
        </div>
      </section>
      ${running ? `<div class="watch-progress" role="status" aria-live="polite"><span class="watch-progress-dot"></span>Снимаю свежий снимок…</div>` : ""}
      ${diff.page?.last_error ? `<div class="partial-status" role="alert">${icon("icon-eye-off")}<span>${escapeHTML(diff.page.last_error)}</span></div>` : ""}
      <section class="review-workspace">
        <article class="document-pane" aria-label="Сохранённая копия страницы">
          <div class="pane-bar">${renderWatchCopyBar(diff, pageId)}</div>
          <div class="document-scroll">
            ${renderWatchCopy(diff, pageId)}
          </div>
        </article>
        <aside class="issues-pane" aria-label="Находки">
          ${renderWatchChanges(diff, { status: diff.page?.last_status, error: diff.page?.last_error })}
          ${status === "error" ? `<footer class="issues-footer"><span>${escapeHTML(watchStatusLabel(status))}</span></footer>` : ""}
        </aside>
      </section>
    </div>`);
    document.querySelector(".back-watch").addEventListener("click", () => openWatch(groupId));
    bindWatchCopy(diff);
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
      state.watchPoll = window.setInterval(() => {
        if (state.route === "watch") renderWatch();
        else stopWatchPoll();
      }, 2000);
    }
    return;
  }
  const listSummary = watchPagesSummary(pages);
  const groupBadge = watchGroupBadge(group);
  const groupChecked = group.last_run_at ? `Проверено ${formatDate(group.last_run_at, false)}` : "";
  const groupStats = [listSummary || "Следим за адресами этой группы", watchAuthLabel(group.auth_kind), groupChecked].filter(Boolean);
  renderShell(`
    <div class="page watch-page">
      <div class="page-head">
        <div>
          <button class="text-link back-watch" type="button">${icon("icon-arrow")} Мониторинг</button>
          <h2>${escapeHTML(group.name)}</h2>
          <p class="watch-stats">${watchStats(groupStats)}</p>
        </div>
        <div class="head-actions">
          <button class="icon-button edit-watch-group" type="button" aria-label="Изменить группу">${icon("icon-edit")}</button>
          <button class="icon-button delete-watch-group" type="button" aria-label="Удалить группу">${icon("icon-trash")}</button>
          <button class="button secondary run-watch-group" type="button" ${group.running ? "disabled" : ""}>${icon("icon-refresh")}${group.running ? "Проверяем…" : "Проверить"}</button>
        </div>
      </div>
      ${group.running ? `<div class="watch-progress" role="status" aria-live="polite"><span class="watch-progress-dot"></span>Снимаю свежие снимки…</div>` : ""}
      <section class="panel fill-panel" aria-label="Адреса">
        <div class="panel-head"><div><h3>Адреса</h3><p>${listSummary ? escapeHTML(listSummary) : "Вставь ссылку — снимем первый снимок"}</p></div><div>${groupBadge}</div></div>
        <div class="panel-body">
          <form class="watch-url-bar">
            <label class="field"><span>URL</span><input name="url" required type="url" inputmode="url" placeholder="https://" autocomplete="off"></label>
            <label class="field"><span>Название</span><input name="title" placeholder="Главная" autocomplete="off"></label>
            <button class="button primary" type="submit">${icon("icon-plus")}Добавить</button>
          </form>
          ${pages.length ? `<div class="watch-list">${pages.map((page) => {
            const label = page.title || page.url;
            const rowStats = [watchPageMeta(page), page.title ? page.url : ""].filter(Boolean);
            return `<button class="file-row" type="button" data-watch-page="${escapeHTML(page.id)}">${icon("icon-link")}<span><strong>${escapeHTML(label)}</strong><small class="watch-stats">${watchStats(rowStats)}</small></span><span class="file-row-end">${watchPageBadge(page)}${icon("icon-arrow")}</span></button>`;
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


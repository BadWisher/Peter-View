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

export function renderWatchHunks(hunks) {
  if (!hunks?.length) return `<div class="empty-state"><div><h3>Сравнить пока нечего</h3></div></div>`;
  return `<pre class="watch-diff">${hunks.map((hunk) => {
    if (hunk.op === "skip") return `<div class="watch-skip">… ${hunk.count} строк без изменений …</div>`;
    const prefix = hunk.op === "add" ? "+" : hunk.op === "del" ? "−" : " ";
    return (hunk.lines || []).map((line) => `<div class="watch-${hunk.op}">${prefix} ${escapeHTML(line)}</div>`).join("");
  }).join("")}</pre>`;
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

export function watchGroupMeta(group) {
  const parts = [watchCount(group.page_count)];
  if (group.auth_kind && group.auth_kind !== "none") parts.push("вход");
  if (group.error_count) parts.push("ошибка");
  if (group.last_run_at) parts.push(formatDate(group.last_run_at, false));
  return parts.join(" · ");
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
    renderShell(`
      <div class="page">
        <div class="page-actions"><button class="button primary add-watch-group" type="button">${icon("icon-plus")}Группа</button></div>
        <div class="watch-list">${groups.map((group) => `<button class="file-row" type="button" data-watch-group="${escapeHTML(group.id)}">${icon("icon-eye")}<span><strong>${escapeHTML(group.name)}</strong><small>${escapeHTML(watchGroupMeta(group))}</small></span><span class="file-row-end">${group.changed_count ? `<i class="new-mark" aria-label="Есть изменения"></i>` : ""}${icon("icon-arrow")}</span></button>`).join("")}</div>
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
    let diff = { hunks: [], page: page || { title: "Адрес", url: "" } };
    try { diff = await api(`/api/watch/pages/${encodeURIComponent(pageId)}/diff`); } catch (error) { showError(error); }
    if (state.route !== "watch") return;
    renderShell(`
      <div class="page watch-page">
        <div class="page-head">
          <div>
            <button class="text-link back-watch" type="button">${icon("icon-arrow")} ${escapeHTML(group.name)}</button>
            <h2>${escapeHTML(diff.page?.title || page?.title || "Адрес")}</h2>
            <p class="watch-url">${escapeHTML(diff.page?.url || page?.url || "")}</p>
          </div>
          <div class="head-actions">
            ${watchStatusBadge(diff.page?.last_status || page?.last_status, true)}
            <button class="button secondary run-watch-page" type="button">${icon("icon-refresh")}Проверить</button>
            <button class="icon-button delete-watch-page" type="button" aria-label="Удалить адрес">${icon("icon-trash")}</button>
          </div>
        </div>
        <section class="panel fill-panel watch-diff-panel">${renderWatchHunks(diff.hunks)}</section>
      </div>`);
    document.querySelector(".back-watch").addEventListener("click", () => openWatch(groupId));
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
    return;
  }
  renderShell(`
    <div class="page">
      <div class="page-head">
        <div>
          <button class="text-link back-watch" type="button">${icon("icon-arrow")} Наблюдение</button>
          <h2>${escapeHTML(group.name)}</h2>
        </div>
        <div class="head-actions">
          <button class="icon-button edit-watch-group" type="button" aria-label="Изменить группу">${icon("icon-edit")}</button>
          <button class="icon-button delete-watch-group" type="button" aria-label="Удалить группу">${icon("icon-trash")}</button>
          <button class="button secondary run-watch-group" type="button" ${group.running ? "disabled" : ""}>${icon("icon-refresh")}${group.running ? "Проверяем…" : "Проверить"}</button>
        </div>
      </div>
      <form class="watch-url-bar">
        <label class="field"><span>URL</span><input name="url" required type="url" inputmode="url" placeholder="https://" autocomplete="off"></label>
        <label class="field"><span>Название</span><input name="title" placeholder="Главная" autocomplete="off"></label>
        <button class="button primary" type="submit">${icon("icon-plus")}Добавить</button>
      </form>
      ${pages.length ? `<div class="watch-list">${pages.map((page) => `<button class="file-row" type="button" data-watch-page="${escapeHTML(page.id)}">${icon("icon-link")}<span><strong>${escapeHTML(page.title || page.url)}</strong><small>${escapeHTML(page.url)}</small></span>${watchStatusBadge(page.last_status)}</button>`).join("")}</div>` : ""}
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


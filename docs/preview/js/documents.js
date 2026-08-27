import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderDocuments() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`);
  try {
    const data = await api(`/api/repo/folders?parent=${encodeURIComponent(state.repo.folderId || "")}`);
    state.repo = {
      folderId: data.folder_id,
      folders: data.folders || [],
      documents: data.documents || [],
      breadcrumbs: data.breadcrumbs || [],
      archived: false,
    };
  } catch (error) {
    showError(error);
  }
  if (state.route !== "documents") return;
  drawDocuments();
}

export function drawDocuments() {
  renderShell(`
    <div class="repository-layout">
      <aside class="folder-tree">
        <div class="tree-title"><strong>Папки</strong><button class="icon-button create-folder" type="button" aria-label="Создать папку">${icon("icon-plus")}</button></div>
        <div class="tree-list">
          <button class="tree-item ${!state.repo.folderId ? "active" : ""}" type="button" data-folder-id="">${icon("icon-folder")}<span>Все документы</span></button>
          ${state.repo.folders.map((folder) => `<button class="tree-item" type="button" data-folder-id="${escapeHTML(folder.id)}">${icon("icon-folder")}<span>${escapeHTML(folder.name)}</span><b>${folder.item_count || 0}</b></button>`).join("")}
          <button class="tree-item archived-folder ${state.repo.archived ? "active" : ""}" type="button">${icon("icon-archive")}<span>Архив</span></button>
        </div>
      </aside>
      <section class="repo-main">
        ${state.repo.archived ? "" : `<div class="page-actions"><button class="button secondary create-folder" type="button">${icon("icon-folder")}Папка</button><button class="button primary upload-document" type="button">${icon("icon-upload")}Загрузить</button></div>`}
        <div class="breadcrumbs"><button type="button" data-folder-id="">Документы</button>${state.repo.breadcrumbs.map((crumb) => `<span>/</span><button type="button" data-folder-id="${escapeHTML(crumb.id)}">${escapeHTML(crumb.name)}</button>`).join("")}</div>
        <div class="toolbar"><label class="search-field">${icon("icon-search")}<span class="visually-hidden">Поиск документов</span><input id="repo-search" type="search" placeholder="Название или Jira…" autocomplete="off"></label></div>
        ${state.repo.documents.length || state.repo.folders.length ? `<div class="file-grid">
          ${state.repo.folders.map((folder) => `<button class="file-row" type="button" data-folder-id="${escapeHTML(folder.id)}">${icon("icon-folder")}<span><strong>${escapeHTML(folder.name)}</strong><small>${folder.item_count || 0} элементов</small></span>${icon("icon-arrow")}</button>`).join("")}
          ${state.repo.documents.map((doc) => `<button class="file-row" type="button" data-doc-id="${escapeHTML(doc.id)}" data-archived="${state.repo.archived || doc.archived ? "true" : "false"}">${icon("icon-file")}<span><strong>${escapeHTML(doc.name)}</strong><small>${doc.version_count || 0} версий · ${formatDate(doc.last_activity_at, false)}</small></span>${doc.is_new ? `<i class="new-mark" aria-label="Обновлено"></i>` : ""}</button>`).join("")}
        </div>` : `<div class="panel empty-state">${icon(state.repo.archived ? "icon-archive" : "icon-folder")}<div><h3>${state.repo.archived ? "Архив пуст" : "Здесь пока пусто"}</h3><p>${state.repo.archived ? "Перемещённые в архив документы появятся здесь." : "Загрузите документ или создайте папку."}</p>${state.repo.archived ? "" : `<button class="button primary upload-document" type="button">Загрузить документ</button>`}</div></div>`}
      </section>
    </div>`);
  bindDocuments();
}

export function bindDocuments() {
  document.querySelectorAll("[data-folder-id]").forEach((button) => button.addEventListener("click", () => {
    state.repo.folderId = button.dataset.folderId || null;
    renderDocuments();
  }));
  document.querySelectorAll(".create-folder").forEach((button) => button.addEventListener("click", showCreateFolder));
  document.querySelectorAll(".upload-document").forEach((button) => button.addEventListener("click", () => showUploadDocument()));
  document.querySelectorAll("[data-doc-id]").forEach((button) => button.addEventListener("click", () => showDocument(button.dataset.docId, button.dataset.archived === "true")));
  document.querySelector(".archived-folder")?.addEventListener("click", renderArchive);
  if (!state.repo.archived) bindDropTarget(document.querySelector(".repo-main"), (file) => showUploadDocument(file));
  document.querySelector("#repo-search")?.addEventListener("input", async (event) => {
    const query = event.target.value.trim();
    if (!query) {
      renderDocuments();
      return;
    }
    if (query.length < 2) return;
    try {
      const data = await api(`/api/repo/search?q=${encodeURIComponent(query)}`);
      state.repo.documents = data.documents || [];
      document.querySelectorAll("[data-doc-id]").forEach((node) => node.remove());
      drawDocuments();
      document.querySelector("#repo-search").value = query;
      document.querySelector("#repo-search").focus();
    } catch (error) {
      showError(error);
    }
  });
}

export function showCreateFolder() {
  modal({
    title: "Новая папка",
    body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" required maxlength="80" autocomplete="off"></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Создать</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await api("/api/repo/folders", { method: "POST", body: JSON.stringify({ name: form.elements.name.value.trim(), parent_id: state.repo.folderId }) });
          close();
          toast("Папка создана");
          renderDocuments();
        } catch (error) {
          showError(error);
        }
      });
    },
  });
}

export function showUploadDocument(initialFile = null) {
  modal({
    title: "Загрузить документ",
    body: `<form class="dialog-body">
      <label class="field"><span>Файл</span><input name="file" type="file" required></label>
      <label class="field"><span>Название</span><input name="name" placeholder="Название документа…" autocomplete="off"></label>
      <div class="field-row"><label class="field"><span>Jira</span><input name="jira" placeholder="DOC-123" autocomplete="off" spellcheck="false"></label><label class="field"><span>Комментарий</span><input name="note" placeholder="Что изменилось…" autocomplete="off"></label></div>
      <div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Загрузить</button></div>
    </form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      if (initialFile) {
        const transfer = new DataTransfer();
        transfer.items.add(initialFile);
        form.elements.file.files = transfer.files;
        if (!form.elements.name.value) form.elements.name.value = initialFile.name.replace(/\.[^.]+$/, "");
      }
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData();
        data.append("file", form.elements.file.files[0]);
        data.append("folder_id", state.repo.folderId || "");
        data.append("name", form.elements.name.value.trim());
        data.append("jira", form.elements.jira.value.trim());
        data.append("note", form.elements.note.value.trim());
        try {
          await api("/api/repo/documents", { method: "POST", body: data });
          close();
          toast("Документ загружен");
          renderDocuments();
        } catch (error) {
          showError(error);
        }
      });
    },
  });
}

export async function showDocument(id, isArchived = false) {
  try {
    const doc = await api(`/api/repo/documents/${encodeURIComponent(id)}`);
    const versions = doc.versions || [];
    modal({
      title: doc.name || "Документ",
      description: `${versions.length} версий`,
      wide: true,
      body: `<div class="dialog-body detail-drawer">
        <div class="inline-actions"><button class="button primary add-version" type="button">${icon("icon-upload")}Новая версия</button><button class="button secondary archive-doc" type="button">${icon("icon-archive")}${isArchived ? "Восстановить" : "В архив"}</button><button class="button ghost delete-doc" type="button">${icon("icon-trash")}Удалить</button></div>
        <div class="version-timeline">${versions.slice().reverse().map((version) => `<div class="version"><span class="version-number">v${version.number}</span><div><strong>${escapeHTML(version.filename || `Версия ${version.number}`)}</strong><small>${escapeHTML(version.uploaded_by || "")} · ${formatDate(version.created_at)}${version.jira ? ` · ${escapeHTML(version.jira)}` : ""}</small></div><a class="button secondary version-download" data-filename="${escapeHTML(version.filename || `version-${version.number}`)}" href="/api/repo/documents/${encodeURIComponent(id)}/versions/${version.number}">${icon("icon-download")}Скачать</a></div>`).join("") || `<div class="empty-state"><p>Версий нет.</p></div>`}</div>
      </div>`,
      onReady(dialog, close) {
        if (isPreview) dialog.querySelectorAll(".version-download").forEach((link) => link.addEventListener("click", async (event) => {
          event.preventDefault();
          const blob = await previewApi(new URL(link.href).pathname);
          downloadBlob(blob instanceof Blob ? blob : new Blob(["Preview document"]), link.dataset.filename);
        }));
        dialog.querySelector(".add-version").addEventListener("click", () => showAddVersion(id, close));
        dialog.querySelector(".archive-doc").addEventListener("click", async () => {
          try {
            await api(`/api/repo/documents/${encodeURIComponent(id)}/${isArchived ? "unarchive" : "archive"}`, { method: "POST", body: "{}" });
            close();
            toast(isArchived ? "Документ восстановлен" : "Документ перемещён в архив");
            if (isArchived) renderArchive();
            else renderDocuments();
          } catch (error) { showError(error); }
        });
        dialog.querySelector(".delete-doc").addEventListener("click", () => {
          close();
          confirmAction({
            title: "Удалить документ?",
            description: "Версии будут удалены.",
            async onConfirm() {
              await api(`/api/repo/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
              toast("Документ удалён");
              renderDocuments();
            },
          });
        });
      },
    });
  } catch (error) {
    showError(error);
  }
}

export function showAddVersion(id, parentClose) {
  parentClose();
  modal({
    title: "Новая версия",
    body: `<form class="dialog-body"><label class="field"><span>Файл</span><input name="file" type="file" required></label><div class="field-row"><label class="field"><span>Jira</span><input name="jira" placeholder="DOC-123" autocomplete="off"></label><label class="field"><span>Комментарий</span><input name="note" placeholder="Что изменилось…" autocomplete="off"></label></div><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Добавить версию</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData();
        data.append("file", form.elements.file.files[0]);
        data.append("jira", form.elements.jira.value.trim());
        data.append("note", form.elements.note.value.trim());
        try {
          await api(`/api/repo/documents/${encodeURIComponent(id)}/versions`, { method: "POST", body: data });
          close();
          toast("Версия добавлена");
          renderDocuments();
        } catch (error) { showError(error); }
      });
    },
  });
}

export async function renderArchive() {
  try {
    const data = await api("/api/repo/archived");
    state.repo.documents = data.documents || [];
    state.repo.folders = [];
    state.repo.breadcrumbs = [{ name: "Архив", id: "" }];
    state.repo.archived = true;
    drawDocuments();
  } catch (error) { showError(error); }
}


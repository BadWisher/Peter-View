import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderUsers() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div></div>`);
  let users = [];
  try { users = (await api("/api/users")).users || []; } catch (error) { showError(error); }
  if (state.route !== "users") return;
  renderShell(`
    <div class="page">
      <div class="page-actions"><button class="button primary add-user" type="button">${icon("icon-plus")}Добавить</button></div>
      <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Пользователь</th><th>Доступ</th><th></th></tr></thead><tbody>${users.map((user) => {
        const name = user.username || user;
        const role = user.role || "editor";
        return `<tr><td><div class="inline-actions"><span class="avatar">${escapeHTML(initials(name))}</span><strong>${escapeHTML(name)}</strong></div></td><td><span class="badge">${escapeHTML(role === "admin" ? t("role.admin") : t("role.editor"))}</span></td><td><button class="icon-button row-action delete-user" data-username="${escapeHTML(name)}" type="button" aria-label="${t("users.delete")}">${icon("icon-trash")}</button></td></tr>`;
      }).join("")}</tbody></table></div></section>
    </div>`);
  document.querySelector(".add-user").addEventListener("click", showAddUser);
  document.querySelectorAll(".delete-user").forEach((button) => button.addEventListener("click", () => confirmAction({
    title: `Удалить ${button.dataset.username}?`,
    description: "Активные сессии пользователя завершатся.",
    async onConfirm() {
      await api(`/api/users/${encodeURIComponent(button.dataset.username)}`, { method: "DELETE" });
      toast("Пользователь удалён");
      renderUsers();
    },
  })));
}

export function showAddUser() {
  modal({
    title: "Новый пользователь",
    body: `<form class="dialog-body"><label class="field"><span>Логин</span><input name="username" required autocomplete="off" spellcheck="false"></label><label class="field"><span>Пароль</span><input name="password" type="password" autocomplete="new-password" minlength="8"><small class="field-hint">Если оставить поле пустым, сервис создаст пароль. Минимум 8 символов.</small></label><label class="field"><span>Роль</span><select name="role"><option value="editor">Редактор</option><option value="admin">Администратор</option></select></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Создать</button></div></form>`,
    onReady(dialog, close) {
      const form = dialog.querySelector("form");
      form.querySelector(".cancel").addEventListener("click", close);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const result = await api("/api/users", { method: "POST", body: JSON.stringify({ username: form.elements.username.value.trim(), password: form.elements.password.value, role: form.elements.role.value }) });
          close();
          modal({ title: "Пользователь создан", description: "Пароль показывается один раз.", body: `<div class="dialog-body"><div class="selected-file">${icon("icon-key")}<div><strong>${escapeHTML(result.username)}</strong><small>${escapeHTML(result.password)}</small></div></div><div class="dialog-actions"><button class="button primary done" type="button">Готово</button></div></div>`, onReady(doneDialog, doneClose) { doneDialog.querySelector(".done").addEventListener("click", () => { doneClose(); renderUsers(); }); } });
        } catch (error) { showError(error); }
      });
    },
  });
}


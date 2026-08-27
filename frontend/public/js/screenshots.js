import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export function renderScreenshots() {
  renderShell(`
    <div class="page">
      <div class="page-actions"><label class="button secondary shot-open">${icon("icon-upload")}Открыть<input id="shot-file" class="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp"></label><button class="button primary shot-download" type="button" disabled>${icon("icon-download")}Скачать PNG</button></div>
      <section class="shot-layout">
        <aside class="shot-tools"><h3>Инструменты</h3><div class="tool-stack">
          <button class="shot-tool active" data-shot-tool="crop" type="button" disabled>${icon("icon-image")}<span>Кадрировать</span></button>
          <button class="shot-tool" data-shot-tool="redact" type="button" disabled>${icon("icon-eye-off")}<span>Скрыть область</span></button>
          <button class="shot-tool" data-shot-tool="picker" type="button" disabled>${icon("icon-edit")}<span>Пипетка</span></button>
          <button class="shot-tool shot-undo" type="button" disabled>${icon("icon-arrow")}<span>Отменить</span></button>
        </div><p class="shot-tool-hint">Проведите мышью по изображению, чтобы применить выбранный инструмент.</p></aside>
        <div class="shot-canvas"><label class="canvas-empty" for="shot-file"><span>${icon("icon-upload")}<strong>Откройте изображение или вставьте Ctrl+V</strong><span>PNG, JPG, WebP</span></span></label><canvas id="shot-stage" hidden aria-label="Редактируемый скриншот"></canvas></div>
        <aside class="shot-inspector"><h3>Экспорт</h3><label class="dark-field"><span>Ширина, px</span><input id="shot-width" type="number" min="100" max="4000" value="1200" inputmode="numeric"></label><label class="dark-field"><span>Шаблон</span><select id="shot-template"><option value="">Без шаблона</option></select></label><label class="dark-field shot-color-field"><span>Цвет скрытия</span><input id="shot-color" type="color" value="#172b28"></label><div class="shot-template-actions"><button class="button secondary save-template" type="button">Сохранить шаблон</button><button class="icon-button delete-template" type="button" aria-label="Удалить шаблон" disabled>${icon("icon-trash")}</button></div></aside>
      </section>
    </div>`);
  bindScreenshots();
}

export async function bindScreenshots() {
  try {
    const data = await api("/api/screenshot-templates");
    const select = document.querySelector("#shot-template");
    if (state.route !== "screenshots" || !select) return;
    select.insertAdjacentHTML("beforeend", (data.templates || []).map((template) => `<option value="${template.width}" data-template-id="${escapeHTML(template.id)}">${escapeHTML(template.name)} · ${template.width}px</option>`).join(""));
  } catch {}
  document.querySelector("#shot-template")?.addEventListener("change", (event) => {
    if (event.target.value) document.querySelector("#shot-width").value = event.target.value;
    document.querySelector(".delete-template").disabled = !event.target.selectedOptions[0]?.dataset.templateId;
  });
  document.querySelector("#shot-file")?.addEventListener("change", (event) => loadShotFile(event.target.files[0]));
  state.pasteCleanup?.();
  const onPaste = (event) => {
    const file = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/"))?.getAsFile();
    if (file) {
      event.preventDefault();
      loadShotFile(file);
    }
  };
  document.addEventListener("paste", onPaste);
  state.pasteCleanup = () => document.removeEventListener("paste", onPaste);
  document.querySelectorAll("[data-shot-tool]").forEach((button) => button.addEventListener("click", () => {
    state.shot.tool = button.dataset.shotTool;
    document.querySelectorAll("[data-shot-tool]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  document.querySelector("#shot-color")?.addEventListener("input", (event) => { state.shot.color = event.target.value; });
  document.querySelector(".shot-undo")?.addEventListener("click", undoShot);
  document.querySelector(".shot-download")?.addEventListener("click", downloadShot);
  document.querySelector(".delete-template")?.addEventListener("click", () => {
    const select = document.querySelector("#shot-template");
    const templateId = select.selectedOptions[0]?.dataset.templateId;
    if (!templateId) return;
    confirmAction({
      title: "Удалить шаблон?",
      description: `Шаблон «${select.selectedOptions[0].textContent}» будет удалён.`,
      async onConfirm() {
        await api(`/api/screenshot-templates/${encodeURIComponent(templateId)}`, { method: "DELETE" });
        toast("Шаблон удалён");
        renderScreenshots();
      },
    });
  });
  document.querySelector(".save-template")?.addEventListener("click", () => {
    const width = Number(document.querySelector("#shot-width").value);
    modal({
      title: "Сохранить шаблон",
      body: `<form class="dialog-body"><label class="field"><span>Название</span><input name="name" required autocomplete="off"></label><div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button primary" type="submit">Сохранить</button></div></form>`,
      onReady(dialog, close) {
        const form = dialog.querySelector("form");
        form.querySelector(".cancel").addEventListener("click", close);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          try {
            await api("/api/screenshot-templates", { method: "POST", body: JSON.stringify({ name: form.elements.name.value.trim(), width }) });
            close();
            toast("Шаблон сохранён");
            renderScreenshots();
          } catch (error) { showError(error); }
        });
      },
    });
  });
}

export function loadShotFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const image = new Image();
    image.onload = () => {
      const canvas = document.querySelector("#shot-stage");
      if (!canvas || state.route !== "screenshots") {
        URL.revokeObjectURL(image.src);
        return;
      }
      const maxPixels = 4_000_000;
      const scale = Math.min(1, 4000 / image.naturalWidth, 4000 / image.naturalHeight, Math.sqrt(maxPixels / (image.naturalWidth * image.naturalHeight)));
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.hidden = false;
      document.querySelector(".canvas-empty")?.remove();
      state.shot.canvas = canvas;
      state.shot.history = [];
      bindShotCanvas(canvas);
      document.querySelector("#shot-width").value = Math.min(image.naturalWidth, 4000);
      document.querySelector(".shot-download").disabled = false;
      document.querySelectorAll("[data-shot-tool]").forEach((button) => { button.disabled = false; });
      updateShotUndo();
      if (scale < 1) toast("Изображение уменьшено", `${canvas.width} × ${canvas.height} px для стабильной работы редактора.`);
      URL.revokeObjectURL(image.src);
    };
    image.src = URL.createObjectURL(file);
}

export function shotPoint(canvas, event) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)),
    y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height)),
  };
}

export function snapshotShot(canvas) {
  return { width: canvas.width, height: canvas.height, data: canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height) };
}

export function restoreShot(canvas, snapshot) {
  canvas.width = snapshot.width;
  canvas.height = snapshot.height;
  canvas.getContext("2d").putImageData(snapshot.data, 0, 0);
}

export function pushShotHistory(canvas, snapshot = snapshotShot(canvas)) {
  state.shot.history.push(snapshot);
  if (state.shot.history.length > 6) state.shot.history.shift();
  updateShotUndo();
}

export function updateShotUndo() {
  const button = document.querySelector(".shot-undo");
  if (button) button.disabled = !state.shot.history.length;
}

export function bindShotCanvas(canvas) {
  canvas.onpointerdown = (event) => {
    if (state.shot.tool === "picker") {
      const point = shotPoint(canvas, event);
      const pixel = canvas.getContext("2d").getImageData(point.x, point.y, 1, 1).data;
      state.shot.color = `#${[pixel[0], pixel[1], pixel[2]].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
      document.querySelector("#shot-color").value = state.shot.color;
      toast("Цвет выбран", state.shot.color);
      return;
    }
    canvas.setPointerCapture(event.pointerId);
    state.shot.drag = { start: shotPoint(canvas, event), before: snapshotShot(canvas) };
  };
  canvas.onpointermove = (event) => {
    if (!state.shot.drag) return;
    const end = shotPoint(canvas, event);
    const { start, before } = state.shot.drag;
    restoreShot(canvas, before);
    const context = canvas.getContext("2d");
    context.save();
    context.strokeStyle = state.shot.tool === "crop" ? "#00a98f" : state.shot.color;
    context.lineWidth = Math.max(2, canvas.width / 600);
    context.setLineDash([10, 7]);
    context.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y);
    context.restore();
  };
  canvas.onpointerup = (event) => {
    if (!state.shot.drag) return;
    const { start, before } = state.shot.drag;
    const end = shotPoint(canvas, event);
    state.shot.drag = null;
    restoreShot(canvas, before);
    const x = Math.round(Math.min(start.x, end.x));
    const y = Math.round(Math.min(start.y, end.y));
    const width = Math.round(Math.abs(end.x - start.x));
    const height = Math.round(Math.abs(end.y - start.y));
    if (width < 4 || height < 4) return;
    pushShotHistory(canvas, before);
    if (state.shot.tool === "redact") {
      const context = canvas.getContext("2d");
      context.fillStyle = state.shot.color;
      context.fillRect(x, y, width, height);
    } else {
      const cropped = canvas.getContext("2d").getImageData(x, y, width, height);
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").putImageData(cropped, 0, 0);
      document.querySelector("#shot-width").value = Math.min(width, 4000);
    }
  };
}

export function undoShot() {
  const snapshot = state.shot.history.pop();
  if (!snapshot || !state.shot.canvas) return;
  restoreShot(state.shot.canvas, snapshot);
  document.querySelector("#shot-width").value = Math.min(snapshot.width, 4000);
  updateShotUndo();
}

export function downloadShot() {
  const canvas = state.shot.canvas;
  if (!canvas) return;
  const width = Math.max(100, Math.min(4000, Number(document.querySelector("#shot-width").value) || canvas.width));
  const height = Math.round(canvas.height * width / canvas.width);
  const output = document.createElement("canvas");
  output.width = width;
  output.height = height;
  output.getContext("2d").drawImage(canvas, 0, 0, width, height);
  output.toBlob((blob) => {
    if (blob) downloadBlob(blob, `screenshot-${width}px.png`);
  }, "image/png");
}


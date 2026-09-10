import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "loose",
  themeVariables: { fontFamily: "inherit", fontSize: "15px" },
  flowchart: { htmlLabels: true, curve: "basis", nodeSpacing: 48, rankSpacing: 58, padding: 12 },
});

// Блоки получают класс pv-mermaid (настраивается в mkdocs.yml через
// superfences.custom_fences). Отдельный класс нужен, чтобы встроенный
// обработчик mermaid темы Material не перехватывал разметку: он ищет
// элементы с классом mermaid и в этой версии темы теряет их содержимое.
async function renderMermaid() {
  const nodes = document.querySelectorAll("pre.pv-mermaid > code");
  if (!nodes.length) return;
  nodes.forEach((code) => {
    const pre = code.parentElement;
    if (pre.dataset.done === "1") return;
    pre.dataset.done = "1";
    const holder = document.createElement("div");
    holder.className = "pv-mermaid-render";
    holder.textContent = code.textContent;
    pre.replaceWith(holder);
  });
  mermaid.run({ querySelector: "div.pv-mermaid-render" });
}

document$.subscribe(renderMermaid);

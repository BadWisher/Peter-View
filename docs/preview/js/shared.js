import { t, setLocale, currentLocale, loadLocale } from "./i18n.js";
export { t, setLocale, currentLocale, loadLocale };
export const hooks = { bindShell() {}, renderApp() {} };

export const app = document.querySelector("#app");
export const overlayRoot = document.querySelector("#overlay-root");
export const toastRoot = document.querySelector("#toast-root");
const previewPath = window.location.pathname.replace(/\/index\.html$/, "/");
export const isPreview =
  new URLSearchParams(window.location.search).get("preview") === "1" ||
  /(?:^|\/)preview(?:\/|$)/.test(previewPath);
export let previewExtractTick = 0;

export function waitPreview(ms, value) {
  return new Promise((resolve) => window.setTimeout(() => resolve(value), ms));
}

export const previewFixtures = {
  guides: [
    { id: "preview", name: "Основной Style Guide", rule_count: 3, lexicon_count: 4, selected: true, updated_at: Date.now() / 1000 },
    { id: "product", name: "Продуктовые тексты", rule_count: 2, lexicon_count: 2, selected: false, updated_at: Date.now() / 1000 - 86400 },
  ],
  guide: {
    id: "preview",
    name: "Основной Style Guide",
    builtin: true,
    selected: true,
    rules: [
      { rule_id: "UITerms_Click", title: "Действия в интерфейсе", group: "Интерфейс", severity: "blocker", description: "Используйте точные глаголы для элементов интерфейса." },
      { rule_id: "Bureaucracy", title: "Отглагольные существительные", group: "Ясность", severity: "suggestion", description: "Заменяйте тяжёлые конструкции прямым действием." },
      { rule_id: "Dash_NoSpace", title: "Пробелы рядом с тире", group: "Пунктуация", severity: "minor", description: "Проверяйте пробелы рядом со средним тире." },
    ],
    lexicon: {
      forbidden: [{ term: "кликнуть" }, { term: "произвести установку" }],
      allowed: [{ term: "нажать" }, { term: "установить" }],
    },
  },
  folders: [
    { id: "knowledge", name: "База знаний", item_count: 3 },
    { id: "releases", name: "Релизные заметки", item_count: 2 },
  ],
  documents: [
    { id: "network", name: "Настройка сетевой защиты", version_count: 4, last_activity_at: Date.now() / 1000 - 2600, is_new: true },
    { id: "install", name: "Установка агента", version_count: 2, last_activity_at: Date.now() / 1000 - 86400, is_new: false },
    { id: "api-doc", name: "OpenAPI: Управление политиками", version_count: 6, last_activity_at: Date.now() / 1000 - 172800, is_new: false },
  ],
  watchGroups: [
    { id: "portal", name: "Клиентский портал", auth_kind: "form", has_password: true, page_count: 3, changed_count: 1, error_count: 0, last_run_at: Date.now() / 1000 - 3600 },
    { id: "public", name: "Публичная документация", auth_kind: "none", has_password: false, page_count: 2, changed_count: 0, error_count: 0, last_run_at: Date.now() / 1000 - 86400 },
  ],
  specs: [
    { id: "policies", name: "Управление политиками", has_previous: true, ru: { name: "policies-ru.yaml" }, en: { name: "policies-en.yaml" } },
    { id: "events", name: "Журнал событий", has_previous: false, ru: { name: "events-ru.yaml" }, en: { name: "events-en.yaml" } },
  ],
  users: [{ username: "ivan", role: "editor" }, { username: "olga", role: "admin" }],
};


export const state = {
  user: null,
  route: "check",
  sourceMode: "file",
  sourceFile: null,
  sourceUrl: "",
  sourceText: "",
  checks: { language: true, styleguide: true, consistency: true },
  checkPrompt: "",
  currentJob: null,
  currentReport: null,
  activeIssue: 0,
  issueFilter: "all",
  hiddenIssues: new Set(),
  guides: [],
  selectedGuide: "",
  repo: { folderId: null, folders: [], documents: [], breadcrumbs: [], archived: false },
  specs: [],
  activeSpec: null,
  specTab: "segments",
  specQuery: "",
  specPage: 0,
  apiEdits: { ru: {}, en: {} },
  guide: null,
  guideExtract: null,
  health: null,
  healthAt: 0,
  accountOpen: false,
  shot: { tool: "crop", canvas: null, history: [], drag: null, color: "#172b28" },
  watch: { groupId: null, pageId: null },
  watchChanged: 0,
  features: { documents: false, api: false, watch: false, screenshots: false },
  config: { oidc: false, docs: false, version: "0.1.0" },
  themeFlipFocus: false,
  themeMotionReady: false,
};

export const routeMeta = {
  check: "Вычитка",
  review: "Результат",
  documents: "Документы",
  api: "API",
  guides: "Style Guide",
  screenshots: "Скриншоты",
  history: "История",
  watch: "Наблюдение",
  insights: "Аналитика",
  settings: "Настройки",
  users: "Пользователи",
  health: "Система",
};

export const FEATURE_ROUTES = { documents: "documents", watch: "watch", api: "api", screenshots: "screenshots" };
export const navItems = [
  ["check", "icon-check", "Вычитка"],
  ["documents", "icon-folder", "Документы"],
  ["watch", "icon-eye", "Наблюдение"],
  ["api", "icon-code", "API"],
  ["guides", "icon-book", "Style Guide"],
  ["screenshots", "icon-image", "Скриншоты"],
  ["history", "icon-clock", "История"],
  ["insights", "icon-activity", "Аналитика"],
];

export const adminItems = [
  ["settings", "icon-settings", "Настройки"],
  ["users", "icon-users", "Пользователи"],
];

export function icon(name, className = "") {
  return `<svg class="${className}" aria-hidden="true"><use href="#${name}"></use></svg>`;
}

export function escapeHTML(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function initials(name = "") {
  return name.trim().slice(0, 2).toUpperCase() || "PV";
}

export function healthServicesOk(data = state.health) {
  if (!data) return null;
  if (data.llm?.ok === false || data.embedding?.ok === false) return false;
  return true;
}

export function systemSignal() {
  const ok = healthServicesOk();
  const status = ok === false ? "down" : ok ? "ok" : "pending";
  const label = ok === false ? "Есть проблемы" : ok ? "Сервисы в порядке" : "Проверяю сервисы";
  return `<a class="system-signal ${state.route === "health" ? "active" : ""}" href="#/health"><span class="signal-dot ${status}"></span><div><strong>Система</strong><small>${label}</small></div></a>`;
}

export function paintHealthSignal() {
  const node = document.querySelector(".system-signal");
  if (!node) return;
  node.outerHTML = systemSignal();
}

export async function refreshHealthSignal(force = false) {
  if (!force && state.health && Date.now() - state.healthAt < 60_000) {
    paintHealthSignal();
    return;
  }
  try {
    state.health = await api("/api/health/full");
  } catch {
    state.health = { llm: { ok: false }, embedding: { ok: false } };
  }
  state.healthAt = Date.now();
  paintHealthSignal();
}

export function formatDate(value, withTime = true) {
  if (!value) return "Нет данных";
  const date = typeof value === "number" && value < 10_000_000_000
    ? new Date(value * 1000)
    : new Date(value);
  if (Number.isNaN(date.getTime())) return "Нет данных";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

export function formatBytes(value = 0) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bytes / 1024)} КБ`;
  if (bytes < 1024 ** 3) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bytes / 1024 ** 2)} МБ`;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bytes / 1024 ** 3)} ГБ`;
}

export async function copyText(value) {
  const text = String(value || "");
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано", text);
  } catch {
    toast("Не удалось скопировать", text, "error");
  }
}

export async function previewApi(path, options = {}) {
  const method = options.method || "GET";

  if (path === "/api/styleguides") {
    return { styleguides: previewFixtures.guides, selected: "preview" };
  }
  if (path === "/api/styleguides/extract" && method === "POST") {
    previewExtractTick = 0;
    return { job_id: "preview-extract" };
  }
  if (path === "/api/styleguides/extract/preview-extract") {
    previewExtractTick += 1;
    if (previewExtractTick < 4) {
      return { status: "running", stage: `Извлечение правил: ${previewExtractTick} из 3` };
    }
    return {
      status: "done",
      stage: "Готово",
      source_filename: "Обновлённый гайд.docx",
      rules: [
        { title: "Действия в интерфейсе", rule: "Используйте точные глаголы: нажать, выбрать, открыть.", group: "Интерфейс", severity: "blocker" },
        { title: "Отглагольные существительные", rule: "Заменяйте тяжёлые конструкции прямым действием.", group: "Ясность", severity: "suggestion" },
        { title: "Пробелы рядом с тире", rule: "Проверяйте пробелы рядом со средним тире.", group: "Пунктуация", severity: "minor" },
        { title: "Кавычки в интерфейсе", rule: "Названия кнопок заключайте в кавычки.", group: "Интерфейс", severity: "suggestion" },
      ],
      lexicon: {
        forbidden: [{ term: "кликнуть" }, { term: "закликать" }],
        allowed: [{ term: "нажать" }, { term: "выбрать" }],
      },
    };
  }
  if (/^\/api\/styleguides\/[^/]+$/.test(path) && method === "GET") {
    const id = path.split("/").at(-1);
    if (id === "product") {
      return { ...previewFixtures.guide, id, name: "Продуктовые тексты", builtin: false, selected: false, rules: previewFixtures.guide.rules.slice(0, 2) };
    }
    return previewFixtures.guide;
  }
  if (/^\/api\/styleguides\/[^/]+$/.test(path) && method === "PUT") {
    const id = path.split("/").at(-1);
    const body = JSON.parse(options.body || "{}");
    const next = { ...previewFixtures.guide, ...body, id };
    if (id !== "product") Object.assign(previewFixtures.guide, next);
    const meta = previewFixtures.guides.find((item) => item.id === id);
    if (meta) {
      if (body.name) meta.name = body.name;
      if (body.rules) meta.rule_count = body.rules.length;
      if (body.lexicon) meta.lexicon_count = (body.lexicon.forbidden || []).length + (body.lexicon.allowed || []).length;
    }
    return next;
  }
  if (path === "/api/watch/groups" && method === "GET") {
    return { groups: previewFixtures.watchGroups };
  }
  if (path === "/api/watch/groups" && method === "POST") {
    const body = JSON.parse(options.body || "{}");
    const group = {
      id: `g-${Date.now()}`,
      name: body.name || "Группа",
      auth_kind: body.auth_kind || "none",
      has_password: Boolean(body.password),
      page_count: 0,
      changed_count: 0,
      error_count: 0,
      last_run_at: null,
      login_url: body.login_url || "",
      username: body.username || "",
      username_field: body.username_field || "username",
      password_field: body.password_field || "password",
      pages: [],
    };
    previewFixtures.watchGroups.push(group);
    return group;
  }
  if (/^\/api\/watch\/groups\/[^/]+$/.test(path) && method === "GET") {
    const id = path.split("/").at(-1);
    const group = previewFixtures.watchGroups.find((item) => item.id === id) || previewFixtures.watchGroups[0];
    const pages = group.pages || (id === "public"
      ? [
        { id: "pub-1", group_id: id, url: "https://docs.example.test/start", title: "Начало работы", enabled: true, last_status: "same", last_checked_at: Date.now() / 1000 - 86400, last_changed_at: null, last_error: null },
        { id: "pub-2", group_id: id, url: "https://docs.example.test/api", title: "API", enabled: true, last_status: "same", last_checked_at: Date.now() / 1000 - 86400, last_changed_at: null, last_error: null },
      ]
      : [
        { id: "home", group_id: id, url: "https://portal.example.test/", title: "Главная", enabled: true, last_status: "changed", last_checked_at: Date.now() / 1000 - 3600, last_changed_at: Date.now() / 1000 - 3600, last_error: null },
        { id: "policies", group_id: id, url: "https://portal.example.test/policies", title: "Политики", enabled: true, last_status: "same", last_checked_at: Date.now() / 1000 - 3600, last_changed_at: null, last_error: null },
        { id: "billing", group_id: id, url: "https://portal.example.test/billing", title: "Биллинг", enabled: true, last_status: "error", last_checked_at: Date.now() / 1000 - 3600, last_changed_at: null, last_error: "Страница недоступна (HTTP 401)" },
      ]);
    if (!group.pages) group.pages = pages;
    group.page_count = group.pages.length;
    return { ...group, login_url: group.login_url || "https://portal.example.test/login", username: group.username || "docs", username_field: group.username_field || "username", password_field: group.password_field || "password", pages: group.pages };
  }
  if (/^\/api\/watch\/groups\/[^/]+$/.test(path) && method === "PATCH") {
    const id = path.split("/").at(-1);
    const group = previewFixtures.watchGroups.find((item) => item.id === id);
    const body = JSON.parse(options.body || "{}");
    if (group) Object.assign(group, body, { has_password: group.has_password || Boolean(body.password) });
    return group || { id, ...body };
  }
  if (/^\/api\/watch\/groups\/[^/]+$/.test(path) && method === "DELETE") {
    const id = path.split("/").at(-1);
    previewFixtures.watchGroups = previewFixtures.watchGroups.filter((item) => item.id !== id);
    return { ok: true };
  }
  if (/^\/api\/watch\/groups\/[^/]+\/pages$/.test(path) && method === "POST") {
    const id = path.split("/")[4];
    const group = previewFixtures.watchGroups.find((item) => item.id === id);
    const body = JSON.parse(options.body || "{}");
    const page = { id: `p-${Date.now()}`, group_id: id, url: body.url, title: body.title || "", enabled: true, last_status: "pending", last_checked_at: null, last_changed_at: null, last_error: null };
    if (group) {
      group.pages = group.pages || [];
      group.pages.push(page);
      group.page_count = group.pages.length;
    }
    return page;
  }
  if (/^\/api\/watch\/pages\/[^/]+$/.test(path) && method === "DELETE") {
    const id = path.split("/").at(-1);
    previewFixtures.watchGroups.forEach((group) => {
      if (!group.pages) return;
      group.pages = group.pages.filter((page) => page.id !== id);
      group.page_count = group.pages.length;
    });
    return { ok: true };
  }
  if (path.endsWith("/diff")) {
    return {
      page: { id: "home", title: "Главная", url: "https://portal.example.test/", last_status: "changed", last_checked_at: Date.now() / 1000 - 3600 },
      current: { checked_at: Date.now() / 1000 - 3600, changed: true, error: null },
      previous: { checked_at: Date.now() / 1000 - 86400, changed: false, error: null },
      hunks: [
        { op: "eq", lines: ["Клиентский портал", "Раздел политик"] },
        { op: "del", lines: ["Срок действия пароля: 90 дней"] },
        { op: "add", lines: ["Срок действия пароля: 60 дней"] },
        { op: "eq", lines: ["Поддержка: portal@example.test"] },
      ],
    };
  }
  if (path.startsWith("/api/watch/") && method !== "GET") {
    return { status: "started", ok: true, id: `preview-${Date.now()}` };
  }
  if (path.startsWith("/api/repo/folders")) {
    return { folder_id: null, breadcrumbs: [], folders: previewFixtures.folders, documents: previewFixtures.documents };
  }
  if (path.startsWith("/api/repo/search")) {
    const query = new URL(path, location.origin).searchParams.get("q")?.toLocaleLowerCase("ru") || "";
    return { documents: previewFixtures.documents.filter((item) => item.name.toLocaleLowerCase("ru").includes(query)) };
  }
  if (path === "/api/repo/archived") {
    return { documents: [{ id: "archive-1", name: "Руководство 2025", version_count: 8, last_activity_at: Date.now() / 1000 - 2_592_000 }] };
  }
  if (/^\/api\/repo\/documents\/[^/]+$/.test(path) && method === "GET") {
    const id = path.split("/").at(-1);
    const doc = previewFixtures.documents.find((item) => item.id === id) || previewFixtures.documents[0];
    return {
      ...doc,
      versions: [
        { number: 4, filename: `${doc.name}.docx`, uploaded_by: "olga", jira: "DOC-2145", created_at: Date.now() / 1000 - 2600 },
        { number: 3, filename: `${doc.name}.docx`, uploaded_by: "ivan", jira: "DOC-2098", created_at: Date.now() / 1000 - 172800 },
        { number: 2, filename: `${doc.name}.docx`, uploaded_by: "olga", jira: "", created_at: Date.now() / 1000 - 604800 },
      ],
    };
  }
  if (path === "/api/api-specs") {
    return { specs: previewFixtures.specs };
  }
  if (path === "/api/api-spec-documents") {
    return { documents: previewFixtures.documents.map((item) => ({ id: item.id, name: item.name })) };
  }
  if (path.includes("/segments")) {
    const page = Number(new URL(path, location.origin).searchParams.get("page") || 0);
    const size = 50;
    const seed = [
      { path_str: "paths./policies/{policy_id}/actions/{action_id}.post.description", kind: "description", context: "POST /policies/{id}/actions/{id}", ru_text: "Создаёт новую политику защиты.", en_text: "Creates a new security policy.", ru_line: 28, en_line: 28 },
      { path_str: "paths./policies.get.summary", kind: "summary", context: "GET /policies", ru_text: "Получить список политик", en_text: "Get the policy list", ru_line: 12, en_line: 12 },
      { path_str: "components.schemas.Policy.properties.status.description", kind: "schema_description", context: "Policy.status", ru_text: "Состояние политики", en_text: "Policy status", ru_line: 90, en_line: 90 },
    ];
    const items = Array.from({ length: 87 }, (_, index) => seed[index] || {
      path_str: `components.schemas.Policy.properties.field_${index}.description`,
      kind: "schema_description",
      context: `Policy.field_${index}`,
      ru_text: `Описание поля ${index}`,
      en_text: `Field ${index} description`,
      ru_line: 100 + index,
      en_line: 100 + index,
    });
    const start = page * size;
    const slice = items.slice(start, start + size);
    return { items: slice, segments: slice, total: items.length, page, size, ru_version: 4, en_version: 4 };
  }
  if (path.includes("/consistency")) {
    return {
      by_text: [
        { reason: "разный регистр", count: 157, variants_total: 2, variants: [{ text: "Успешно", count: 146 }, { text: "успешно", count: 11 }] },
        { reason: "разный регистр", count: 48, variants_total: 2, variants: [{ text: "Ошибка валидации", count: 40 }, { text: "ошибка валидации", count: 8 }] },
        { reason: "разный регистр", count: 31, variants_total: 2, variants: [{ text: "Ошибка клиента", count: 27 }, { text: "ошибка клиента", count: 4 }] },
      ],
      by_name: [{ name: "status", count: 7, near: false, variants_total: 2, variants: [{ text: "Состояние политики", count: 4 }, { text: "Статус правила защиты", count: 3 }] }],
    };
  }
  if (path.includes("/diff")) {
    return {
      has_previous: true,
      changes: [
        { path_str: "paths./policies.get.summary", old_text: "Получение политик", new_text: "Получить список политик" },
        { path_str: "components.Policy.properties.mode", old_text: "", new_text: "Режим применения политики" },
      ],
    };
  }
  if (path === "/api/checks/history?limit=50&offset=0") {
    return {
      total: 3,
      items: [
        { id: 1, source: "Настройка сетевой защиты.docx", ts: Date.now() / 1000 - 3200, total: 18, errors: 3, warnings: 9, suggestions: 6, styleguide_name: "Основной Style Guide" },
        { id: 2, source: "docs.example.ru", ts: Date.now() / 1000 - 86400, total: 42, errors: 7, warnings: 23, suggestions: 12, styleguide_name: "Основной Style Guide" },
        { id: 3, source: "Релиз 4.8", ts: Date.now() / 1000 - 172800, total: 6, errors: 1, warnings: 3, suggestions: 2, styleguide_name: "Продуктовые тексты" },
      ],
    };
  }
  if (path === "/api/config") {
    return { version: "0.1.0", features: { documents: true, api: true, watch: true, screenshots: true }, oidc: false, docs: false };
  }
  if (path === "/api/checks/top-rules" || path === "/api/checks/insights") {
    return {
      users: [
        {
          user: "Редактор",
          total_hits: 31,
          distinct_rules: 3,
          rules: [
            { rule_id: "Bureaucracy", title: "Отглагольные существительные", description: "Заменяйте конструкцию прямым действием.", count: 14 },
            { rule_id: "UITerms_Click", title: "Действия в интерфейсе", description: "Используйте точные названия действий.", count: 10 },
            { rule_id: "Dash_NoSpace", title: "Пробелы рядом с тире", description: "Проверяйте пробелы вокруг знака.", count: 7 },
          ],
        },
        {
          user: "Администратор",
          total_hits: 12,
          distinct_rules: 2,
          rules: [
            { rule_id: "Quotes_LatinInQuotes", title: "Латиница без кавычек", description: "Иностранные названия пишутся без кавычек.", count: 8 },
            { rule_id: "Please", title: "Слово «пожалуйста»", description: "В интерфейсных текстах обходитесь без «пожалуйста».", count: 4 },
          ],
        },
      ],
      tokens: { total: { tokens: 1248650 }, today: { tokens: 42100 } },
    };
  }
  if (/^\/api\/checks\/history\/[^/]+$/.test(path)) {
    return demoReport();
  }
  if (path === "/api/settings" && method === "GET") {
    return {
      llm_base_url: "https://llm.internal/v1",
      llm_model: "gpt-5",
      llm_api_key_set: true,
      llm_temperature: 0.2,
      llm_concurrency: 3,
      llm_timeout: 120,
      llm_reasoning_effort: "medium",
      llm_json_mode: true,
      embedding_base_url: "https://embeddings.internal/v1",
      embedding_model: "text-embedding-3-large",
      embedding_api_key_set: true,
    };
  }
  if (path === "/api/settings" && method === "PUT") {
    const body = JSON.parse(options.body || "{}");
    return previewApi("/api/settings");
  }
  if (path === "/api/users") {
    return method === "GET" ? { users: previewFixtures.users } : { username: "Новый пользователь", password: "preview-password" };
  }
  if (path === "/api/health/full") {
    return {
      llm: { ok: true },
      embedding: { ok: true },
      disk: { total: 536_870_912_000, used: 182_536_110_080, free: 354_334_801_920 },
      tokens: { total: { tokens: 1_248_650, prompt: 932_000, completion: 316_650 }, today: { tokens: 42_100 } },
      repo: { doc_count: 28 },
      backup: { created_at: Date.now() / 1000 - 28_800 },
      audit: [{ ts: Date.now() / 1000 - 120, user: "olga", action: "login" }],
    };
  }
  if (path === "/api/screenshot-templates") {
    return method === "GET"
      ? { templates: [{ id: "docs", name: "Документация", width: 1200 }, { id: "wide", name: "Широкий экран", width: 1600 }] }
      : { id: "preview-template", name: "Шаблон", width: 1200 };
  }
  if (path === "/api/report-issues") {
    return new Blob(["Peter View preview report"], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }
  if (path.endsWith("/download")) {
    return new Blob(["openapi: 3.0.0\ninfo:\n  title: Peter View preview\n"], { type: "application/x-yaml" });
  }
  if (path.endsWith("/translate") && method === "POST") return { job_id: "preview-translate" };
  if (path.endsWith("/ai-review") && method === "POST") return { job_id: "preview-api-review" };
  if (path === "/api/jobs/preview-translate") return { status: "done" };
  if (path === "/api/jobs/preview-api-review") return { status: "done" };
  if (path === "/api/jobs/preview-translate/report") {
    return { type: "api-translate", changed: 1, translations: [{ path_str: "paths./policies.get.summary", en_text: "List policies" }] };
  }
  if (path === "/api/jobs/preview-api-review/report") {
    return { type: "api-review", changed: 1, issues: [{ path_str: "paths./policies.get.summary", severity: "warning", message: "Уточните действие в summary." }] };
  }
  if (path.endsWith("/ai-review") || path.endsWith("/translate")) {
    return { job_id: "preview-job" };
  }
  if (method !== "GET") {
    return { ok: true, id: `preview-${Date.now()}` };
  }
  return {};
}

export async function api(path, options = {}) {
  if (isPreview) return previewApi(path, options);
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: options.body instanceof FormData
      ? { ...(options.headers || {}) }
      : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.blob();
  if (!response.ok) {
    const error = new Error(data?.detail || "Не удалось выполнить запрос");
    error.status = response.status;
    throw error;
  }
  return data;
}

export function toast(title, message = "", type = "success") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.innerHTML = `<i></i><div><strong>${escapeHTML(title)}</strong>${message ? `<span>${escapeHTML(message)}</span>` : ""}</div><button type="button" aria-label="Закрыть">${icon("icon-close")}</button>`;
  item.querySelector("button").addEventListener("click", () => item.remove());
  toastRoot.append(item);
  window.setTimeout(() => item.remove(), 5000);
}

export function showError(error, fallback = "Не удалось выполнить действие") {
  const message = error?.message || fallback;
  toast("Ошибка", message, "error");
}

export function go(route) {
  window.location.hash = `#/${route}`;
}

export const THEME_KEY = "pv-theme";
export const PRODUCT_THEME_KEY = "pv-theme-product";

export function getTheme() {
  return document.documentElement.dataset.theme || "light";
}



export function applyTheme(theme, persist = true) {
  if (theme !== "light" && theme !== "dark") theme = "light";
  const previous = getTheme();
  if (persist) {
    localStorage.setItem(THEME_KEY, theme);
    localStorage.setItem(PRODUCT_THEME_KEY, theme);
  }
  if (state.themeMotionReady && previous !== theme) playThemeMotion(theme);
  const root = document.documentElement;
  if (theme === "light") root.removeAttribute("data-theme");
  else root.dataset.theme = theme;
  root.style.colorScheme = theme === "light" ? "light" : "dark";
  const scheme = document.querySelector('meta[name="color-scheme"]');
  if (scheme) scheme.content = theme === "light" ? "light" : "dark";
  const color = document.querySelector('meta[name="theme-color"]');
  if (color) color.content = theme === "dark" ? "#032e28" : "#013b32";
}

export function playThemeMotion(nextTheme) {
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.remove("theme-switching");
  void root.offsetWidth;
  root.classList.add("theme-switching");
  window.clearTimeout(playThemeMotion.timer);
  playThemeMotion.timer = window.setTimeout(() => {
    root.classList.remove("theme-switching");
  }, 480);
}

export function flipTheme() {
  applyTheme(getTheme() === "dark" ? "light" : "dark");
}

export function themeToggleLabel() {
  const theme = getTheme();
  if (theme === "light") return "Тёмная тема";
  return "Светлая тема";
}

export function currentRoute() {
  const value = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const [route, groupId, pageId] = value.split("/");
  if (route === "watch") {
    state.watch.groupId = groupId || null;
    state.watch.pageId = pageId || null;
  }
  if (FEATURE_ROUTES[route] && !state.features[FEATURE_ROUTES[route]]) {
    history.replaceState(null, "", "#/check");
    return "check";
  }
  if ((route === "settings" || route === "users" || route === "health") && state.user?.role !== "admin") {
    history.replaceState(null, "", "#/check");
    return "check";
  }
  return routeMeta[route] ? route : "check";
}

export function setBusy(button, busy, label = "Сохранение…") {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.innerHTML = button.dataset.label || button.innerHTML;
    button.disabled = false;
  }
}

export function modal({ title, description = "", body = "", wide = false, onReady }) {
  const returnFocus = document.activeElement;
  document.body.classList.add("has-modal");
  app.inert = true;
  overlayRoot.innerHTML = `
    <div class="overlay">
      <button class="overlay-backdrop" type="button" aria-label="Закрыть"></button>
      <section class="dialog ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <header class="dialog-head">
          <div><h2 id="dialog-title">${escapeHTML(title)}</h2>${description ? `<p>${escapeHTML(description)}</p>` : ""}</div>
          <button class="icon-button dialog-close" type="button" aria-label="Закрыть">${icon("icon-close")}</button>
        </header>
        ${body}
      </section>
    </div>`;
  const close = () => {
    overlayRoot.innerHTML = "";
    document.body.classList.remove("has-modal");
    app.inert = false;
    if (returnFocus?.isConnected) returnFocus.focus();
  };
  overlayRoot.querySelector(".overlay-backdrop").addEventListener("click", close);
  overlayRoot.querySelector(".dialog-close").addEventListener("click", close);
  overlayRoot.querySelector(".dialog").addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
    if (event.key === "Tab") {
      const controls = [...event.currentTarget.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')];
      if (!controls.length) return;
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  onReady?.(overlayRoot.querySelector(".dialog"), close);
  window.requestAnimationFrame(() => {
    const dialog = overlayRoot.querySelector(".dialog");
    const firstControl = dialog?.querySelector("input:not([type=hidden]), select, textarea, button:not(.dialog-close)");
    (firstControl || dialog?.querySelector(".dialog-close"))?.focus();
  });
}

export function confirmAction({ title, description, confirmLabel = "Удалить", onConfirm }) {
  modal({
    title,
    description,
    body: `<div class="dialog-actions"><button class="button secondary cancel" type="button">Отмена</button><button class="button danger confirm" type="button">${escapeHTML(confirmLabel)}</button></div>`,
    onReady(dialog, close) {
      dialog.querySelector(".cancel").addEventListener("click", close);
      dialog.querySelector(".confirm").addEventListener("click", async (event) => {
        setBusy(event.currentTarget, true, "Выполнение…");
        try {
          await onConfirm();
          close();
        } catch (error) {
          showError(error);
          setBusy(event.currentTarget, false);
        }
      });
    },
  });
}

export function prettyRuleId(id) {
  return String(id || "").replace(/^[A-Za-z]+\./, "").replaceAll("_", " ").trim() || id;
}


export function emptyInline(message) {
  return `<div class="empty-state">${icon("icon-check")}<div><h3>${escapeHTML(message)}</h3></div></div>`;
}

export function bindDropTarget(element, onFile) {
  if (!element) return;
  ["dragenter", "dragover"].forEach((type) => element.addEventListener(type, (event) => {
    event.preventDefault();
    if (event.dataTransfer?.types.includes("Files")) element.classList.add("drag-active");
  }));
  ["dragleave", "drop"].forEach((type) => element.addEventListener(type, (event) => {
    event.preventDefault();
    element.classList.remove("drag-active");
  }));
  element.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) onFile(file);
  });
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function primaryNav() {
  const items = navItems.filter(([route]) => {
    const feat = FEATURE_ROUTES[route];
    return !feat || state.features[feat];
  });
  return items.map(navLink).join("");
}

export function navLink([route, iconName, label]) {
  const count = route === "check" && state.currentReport
    ? state.currentReport.issues?.length || 0
    : route === "watch"
      ? state.watchChanged
      : 0;
  const text = t(`nav.${route}`);
  return `<a href="#/${route}" class="${state.route === route || (route === "check" && state.route === "review") ? "active" : ""}">${icon(iconName)}<span>${text === `nav.${route}` ? label : text}</span>${count ? `<b class="nav-count">${count}</b>` : ""}</a>`;
}

export function renderShell(content) {
  const title = routeMeta[state.route];
  const username = state.user?.username || "Пользователь";
  app.innerHTML = `
    <div class="app-shell">
      ${isPreview ? `<p class="preview-note" role="status">Демонстрация интерфейса. Проверка на сервере не запускается, данные заранее подготовлены.</p>` : ""}
      <aside class="sidebar">
        <a class="brand" href="#/check"><img id="brandMark" class="brand-mark" src="logo.png" width="39" height="39" alt=""><span>Peter<br>View</span></a>
        <button class="icon-button sidebar-close" type="button" aria-label="Закрыть меню">${icon("icon-close")}</button>
        <nav class="primary-nav" aria-label="Основные разделы">${primaryNav()}</nav>
        <div class="nav-divider"></div>
        ${state.user?.role === "admin" ? `<nav class="primary-nav" aria-label="Управление">${adminItems.map(navLink).join("")}</nav>${systemSignal()}` : ""}
        <button class="account-button" type="button" aria-expanded="${state.accountOpen}">
          <span class="avatar">${escapeHTML(initials(username))}</span>
          <span><strong>${escapeHTML(username)}</strong><small>Учётная запись</small></span>
          ${icon("icon-chevron")}
        </button>
      </aside>
      <section class="app-stage">
        <header class="topbar">
          <button class="icon-button mobile-menu" type="button" aria-label="Открыть меню">${icon("icon-menu")}</button>
          <div class="topbar-title"><h1>${escapeHTML(title)}</h1></div>
          ${state.route === "review" ? `<button class="button primary export-report" type="button">${icon("icon-download")}<span>Экспорт</span></button>` : ""}
        </header>
        <main id="main" class="view">${content}</main>
      </section>
    </div>
    ${state.accountOpen ? accountMenu() : ""}`;
  hooks.bindShell();
}

export function accountMenu() {
  const theme = getTheme();
  const docs = state.config?.docs ? `<a role="menuitem" href="/api/docs" target="_blank" rel="noopener">${icon("icon-code")}${t("account.apiDocs")}</a>` : "";
  const password = state.user?.source === "oidc" ? "" : `<button role="menuitem" type="button" data-account-action="password">${icon("icon-key")}${t("account.password")}</button>`;
  return `<div class="account-menu" role="menu" aria-label="${t("account.menu")}">
    <button role="menuitem" type="button" data-account-action="theme">${icon(theme === "light" ? "icon-moon" : "icon-sun")}${themeToggleLabel()}</button>
    <button role="menuitem" type="button" data-account-action="lang">${icon("icon-text")}${t("account.language")}</button>
    ${docs}
    ${isPreview ? "" : password}
    ${isPreview ? "" : `<button role="menuitem" type="button" data-account-action="logout">${icon("icon-close")}${t("account.logout")}</button>`}
  </div>`;
}


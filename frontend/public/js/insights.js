import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks, currentLocale } from "./shared.js";

function ruPlural(n, one, few, many) {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return one;
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return few;
  return many;
}

function authorsLabel(n) {
  return currentLocale() === "ru" ? ruPlural(n, "автор", "автора", "авторов") : t("insights.authors");
}

export async function renderInsights() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let data = { users: [], tokens: {} };
  try { data = await api("/api/checks/insights"); } catch (error) { showError(error); }
  if (state.route !== "insights") return;
  const users = (data.users || []).filter((user) => user.rules?.length);
  const tokens = data.tokens || {};
  const total = tokens.total || {};
  const today = tokens.today || {};
  const hits = users.reduce((sum, user) => sum + (Number(user.total_hits) || 0), 0);
  const fmt = new Intl.NumberFormat("ru-RU");
  renderShell(`
    <div class="page">
      <div class="stat-strip">
        <div class="stat"><strong>${fmt.format(total.tokens || 0)}</strong><span>${t("insights.tokensTotal")}</span></div>
        <div class="stat"><strong>${fmt.format(today.tokens || 0)}</strong><span>${t("insights.tokensToday")}</span></div>
        <div class="stat"><strong>${fmt.format(hits)}</strong><span>${t("insights.hits")}</span></div>
        <div class="stat"><strong>${fmt.format(users.length)}</strong><span>${authorsLabel(users.length)}</span></div>
      </div>
      <section class="panel insights-panel">
        ${users.length ? users.map((user) => {
          const max = Math.max(...user.rules.map((rule) => Number(rule.count) || 0), 1);
          return `<section class="frequent-user"><header><strong>${escapeHTML(user.user)}</strong><span>${user.total_hits} ${t("insights.hits")}</span></header>${user.rules.map((rule, index) => `<div class="frequent-rule" style="--share:${(Number(rule.count) || 0) / max}"><span>${index + 1}</span><div><strong>${escapeHTML(rule.title || prettyRuleId(rule.rule_id))}</strong><small>${escapeHTML(rule.description || "")}</small></div><b>${rule.count}</b></div>`).join("")}</section>`;
        }).join("") : emptyInline(t("insights.empty"))}
      </section>
    </div>`);
}


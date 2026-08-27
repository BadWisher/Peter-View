import { state, api, icon, escapeHTML, initials, toast, showError, go, modal, confirmAction, setBusy, formatDate, formatBytes, renderShell, bindDropTarget, downloadBlob, emptyInline, prettyRuleId, isPreview, previewFixtures, waitPreview, copyText, t, hooks } from "./shared.js";
export async function renderInsights() {
  renderShell(`<div class="loading-block"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  let data = { users: [], tokens: {} };
  try { data = await api("/api/checks/insights"); } catch (error) { showError(error); }
  if (state.route !== "insights") return;
  const users = (data.users || []).filter((user) => user.rules?.length);
  const tokens = data.tokens || {};
  const total = tokens.total || {};
  const today = tokens.today || {};
  renderShell(`
    <div class="page">
      <div class="stat-strip">
        <div class="stat"><strong>${new Intl.NumberFormat("ru-RU").format(total.tokens || 0)}</strong><span>${t("insights.tokensTotal")}</span></div>
        <div class="stat"><strong>${new Intl.NumberFormat("ru-RU").format(today.tokens || 0)}</strong><span>${t("insights.tokensToday")}</span></div>
        <div class="stat"><strong>${users.length}</strong><span>${t("insights.authors")}</span></div>
      </div>
      <section class="panel">
        ${users.length ? users.map((user) => `<section class="frequent-user"><header><strong>${escapeHTML(user.user)}</strong><span>${user.total_hits} ${t("insights.hits")}</span></header>${user.rules.map((rule, index) => `<div class="frequent-rule"><span>${index + 1}</span><div><strong>${escapeHTML(rule.title || prettyRuleId(rule.rule_id))}</strong><small>${escapeHTML(rule.description || "")}</small></div><b>${rule.count}</b></div>`).join("")}</section>`).join("") : emptyInline(t("insights.empty"))}
      </section>
    </div>`);
}


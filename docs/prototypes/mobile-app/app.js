const state = {
  data: null,
  view: "home",
  period: "today",
  breakdown: "machine",
  trendPoints: []
};

const elements = {
  periodLabel: document.getElementById("periodLabel"),
  periodTotal: document.getElementById("periodTotal"),
  periodMeta: document.getElementById("periodMeta"),
  inputTokens: document.getElementById("inputTokens"),
  outputTokens: document.getElementById("outputTokens"),
  cacheTokens: document.getElementById("cacheTokens"),
  trendRange: document.getElementById("trendRange"),
  usageTrend: document.getElementById("usageTrend"),
  trendTooltip: document.getElementById("trendTooltip"),
  limitsState: document.getElementById("limitsState"),
  homeLimitCards: document.getElementById("homeLimitCards"),
  healthSummary: document.getElementById("healthSummary"),
  topSources: document.getElementById("topSources"),
  sourceList: document.getElementById("sourceList"),
  sourceCount: document.getElementById("sourceCount"),
  sourceHealthScore: document.getElementById("sourceHealthScore"),
  breakdownList: document.getElementById("breakdownList"),
  breakdownTitle: document.getElementById("breakdownTitle"),
  breakdownPeriodMeta: document.getElementById("breakdownPeriodMeta"),
  detailBackdrop: document.getElementById("detailBackdrop"),
  breakdownDetailPanel: document.getElementById("breakdownDetailPanel"),
  detailClose: document.getElementById("detailClose"),
  detailKind: document.getElementById("detailKind"),
  detailTitle: document.getElementById("detailTitle"),
  detailSummary: document.getElementById("detailSummary"),
  detailInput: document.getElementById("detailInput"),
  detailOutput: document.getElementById("detailOutput"),
  detailCache: document.getElementById("detailCache"),
  detailCacheRatio: document.getElementById("detailCacheRatio"),
  detailChildList: document.getElementById("detailChildList"),
  limitList: document.getElementById("limitList"),
  limitCount: document.getElementById("limitCount"),
  limitsObservedScore: document.getElementById("limitsObservedScore"),
  limitsSummary: document.getElementById("limitsSummary"),
  limitReminderSwitch: document.getElementById("limitReminderSwitch"),
  limitReminderStatus: document.getElementById("limitReminderStatus"),
  refreshButton: document.getElementById("refreshButton")
};

function formatTokens(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(2)}M`;
  }
  if (value >= 1000) {
    return `${Math.round(value / 1000)}K`;
  }
  return String(value);
}

function statusLabel(status) {
  const labels = {
    ok: "正常",
    stale: "过期",
    command_failed: "失败",
    missing: "缺失",
    observed: "可信"
  };
  return labels[status] || status.toUpperCase();
}

function sourceMessageLabel(message) {
  if (message === "fresh") {
    return "数据新鲜";
  }
  if (message.startsWith("No push for")) {
    return message.replace("No push for", "未上报").replace("minutes", "分钟");
  }
  if (message.startsWith("Fixture parser succeeded")) {
    return "解析可用；真实读取器未配置";
  }
  return message;
}

function limitReasonLabel(reason) {
  if (!reason) {
    return "缺少可信来源。";
  }
  if (reason === "OAuth weekly usage source is not configured in this fixture.") {
    return "OAuth weekly 用量来源未配置";
  }
  return reason;
}

function resetLabel(value) {
  const labels = {
    Sunday: "周日"
  };
  return labels[value] || value || "--";
}

function renderProgressRow(item, className = "", options = {}) {
  const width = Math.max(2, Math.min(100, item.share || 0));
  const tag = options.clickable ? "button" : "div";
  const attrs = options.clickable ? ` type="button" data-detail-index="${options.index}"` : "";
  return `
    <${tag} class="bar-row" data-provenance="breakdown.row"${attrs}>
      <div class="row-top">
        <strong>${item.label}</strong>
        <span class="token-count">${formatTokens(item.tokens)}</span>
      </div>
      <div class="progress-track" aria-label="${item.label} ${width}%">
        <div class="progress-fill ${className}" style="width: ${width}%"></div>
      </div>
    </${tag}>
  `;
}

function renderPeriodMetrics(data) {
  const period = data.periods[state.period];

  elements.periodLabel.textContent = `${period.label} · ${period.range_label}`;
  elements.periodTotal.textContent = formatTokens(period.total_tokens);
  elements.periodMeta.textContent = `${period.delta_label} · Updated ${data.summary.last_updated_label}`;
  elements.inputTokens.textContent = formatTokens(period.input_tokens);
  elements.outputTokens.textContent = formatTokens(period.output_tokens);
  elements.cacheTokens.textContent = formatTokens(period.cache_tokens);
  elements.trendRange.textContent = period.range_label;
}

function renderTrend(data) {
  const rows = data.trend[state.period] || [];
  const width = 360;
  const height = 144;
  const padding = { top: 16, right: 14, bottom: 28, left: 14 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const max = Math.max(...rows.map((row) => row.tokens), 1);
  const step = rows.length > 1 ? innerWidth / (rows.length - 1) : innerWidth;
  const points = rows.map((row, index) => {
    const x = padding.left + index * step;
    const y = padding.top + innerHeight - (row.tokens / max) * innerHeight;
    return { ...row, x, y };
  });
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const area = `${path} L ${points[points.length - 1].x.toFixed(1)} ${height - padding.bottom} L ${points[0].x.toFixed(1)} ${height - padding.bottom} Z`;
  state.trendPoints = points;

  elements.usageTrend.innerHTML = `
    <path d="${area}" class="trend-area"></path>
    <path d="${path}" class="trend-line"></path>
    ${points.map((point) => `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.5" class="trend-dot"></circle>`).join("")}
    ${points.map((point, index) => `<text x="${point.x.toFixed(1)}" y="${height - 8}" text-anchor="${index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}">${point.label}</text>`).join("")}
  `;
  hideTrendTooltip();
}

function renderTrendTooltip(point) {
  elements.trendTooltip.innerHTML = `
    <strong>${point.label}</strong>
    <span>${formatTokens(point.tokens)} tokens</span>
    <em>Input ${formatTokens(point.input_tokens)} · Output ${formatTokens(point.output_tokens)}</em>
    <em>Cache ${formatTokens(point.cache_tokens)} · ${point.cache_ratio}%</em>
  `;
}

function showTrendTooltip(clientX) {
  if (!state.trendPoints.length) {
    return;
  }
  const rect = elements.usageTrend.getBoundingClientRect();
  const svgX = ((clientX - rect.left) / rect.width) * 360;
  const point = state.trendPoints.reduce((closest, candidate) => (
    Math.abs(candidate.x - svgX) < Math.abs(closest.x - svgX) ? candidate : closest
  ));
  renderTrendTooltip(point);
  elements.trendTooltip.hidden = false;
  elements.trendTooltip.style.left = `${Math.max(10, Math.min(rect.width - 120, (point.x / 360) * rect.width - 52))}px`;
  elements.trendTooltip.style.top = `${Math.max(8, (point.y / 144) * rect.height - 42)}px`;
}

function hideTrendTooltip() {
  elements.trendTooltip.hidden = true;
}

function renderLimitChip(window) {
  const title = `${window.provider} · ${window.account_label}`;
  if (window.confidence !== "observed") {
    return `
      <article class="limit-chip missing" data-provenance="limits.windows.missing">
        <div>
          <strong>${title}</strong>
          <span>${window.window} · ${statusLabel(window.confidence)}</span>
        </div>
        <em>--</em>
      </article>
    `;
  }
  return `
    <article class="limit-chip" data-provenance="limits.windows.observed">
      <div>
        <strong>${title}</strong>
        <span>${window.window} · 重置 ${resetLabel(window.reset_label)}</span>
      </div>
      <em>${window.remaining_percent}%</em>
    </article>
  `;
}

function renderHome(data) {
  const summary = data.summary;

  renderPeriodMetrics(data);
  renderTrend(data);

  elements.limitsState.textContent = `${data.limits.windows.length} 个窗口`;
  elements.healthSummary.textContent = `${summary.healthy_sources}/${summary.total_sources} fresh · ${summary.stale_sources} stale · ${summary.failed_sources} failed`;

  elements.homeLimitCards.innerHTML = data.limits.windows
    .slice(0, 4)
    .map(renderLimitChip)
    .join("");

  elements.topSources.innerHTML = data.top_sources
    .map((source) => renderProgressRow({ label: source.label, tokens: source.tokens, share: source.share }, source.agent === "Codex" ? "agent" : "date"))
    .join("");
}

function renderSources(data) {
  const summary = data.summary;
  elements.sourceCount.textContent = `${data.sources.length} 个来源`;
  elements.sourceHealthScore.textContent = `${summary.healthy_sources}/${summary.total_sources}`;
  elements.sourceList.innerHTML = data.sources
    .map((source) => `
      <article class="source-card">
        <div class="source-title">
          <strong><span class="status-dot ${source.status}" aria-hidden="true"></span>${source.machine} / ${source.os_user}</strong>
          <span class="status-pill ${source.status}">${statusLabel(source.status)}</span>
        </div>
        <div class="source-meta">
          <span>${source.source_id}</span>
          <span>${source.platform}</span>
          <span>${source.agents.join(", ")}</span>
          <span>${formatTokens(source.tokens_today)}</span>
          <span>观测 ${source.last_observed.slice(11, 16)}</span>
          <span>上报 ${source.last_pushed.slice(11, 16)}</span>
        </div>
        <p class="quiet-copy">${sourceMessageLabel(source.message)}</p>
      </article>
    `)
    .join("");
}

function renderBreakdown(data) {
  const labels = {
    machine: "按机器",
    account: "按系统账户",
    agent: "按 Agent",
    model: "按模型",
    date: "按日期"
  };
  const rows = data.breakdowns[state.period][state.breakdown] || [];
  const period = data.periods[state.period];
  elements.breakdownTitle.textContent = `${labels[state.breakdown]} · ${period.label}`;
  elements.breakdownPeriodMeta.textContent = `${period.label} · ${period.range_label} · ${formatTokens(period.total_tokens)} tokens`;
  elements.breakdownList.innerHTML = rows
    .map((row, index) => renderProgressRow(row, state.breakdown === "agent" ? "agent" : state.breakdown === "date" ? "date" : "", { clickable: true, index }))
    .join("");
}

function tokenPartsFor(row) {
  const input = row.input_tokens || Math.round(row.tokens * 0.26);
  const output = row.output_tokens || Math.round(row.tokens * 0.15);
  const cache = row.cache_tokens || Math.max(0, row.tokens - input - output);
  const cacheRatio = row.cache_ratio || Math.round((cache / Math.max(row.tokens, 1)) * 100);
  return { input, output, cache, cacheRatio };
}

function showBreakdownDetail(index) {
  const rows = state.data.breakdowns[state.period][state.breakdown] || [];
  const row = rows[index];
  if (!row) {
    return;
  }
  const detail = state.data.breakdown_detail[state.breakdown];
  const period = state.data.periods[state.period];
  const parts = tokenPartsFor(row);
  const childRows = detail.children
    .flatMap((dimension) => (state.data.breakdowns[state.period][dimension] || []).slice(0, 2).map((item) => ({
      ...item,
      label: `${detailLabel(dimension)} · ${item.label}`
    })))
    .slice(0, 5);

  elements.detailKind.textContent = `${detail.label} · ${period.label}`;
  elements.detailTitle.textContent = row.label;
  elements.detailSummary.textContent = detail.summary;
  elements.detailInput.textContent = formatTokens(parts.input);
  elements.detailOutput.textContent = formatTokens(parts.output);
  elements.detailCache.textContent = formatTokens(parts.cache);
  elements.detailCacheRatio.textContent = `Cache ratio ${parts.cacheRatio}% · ${formatTokens(row.tokens)} tokens`;
  elements.detailChildList.innerHTML = childRows
    .map((item) => renderProgressRow(item, "date"))
    .join("");
  elements.detailBackdrop.hidden = false;
  elements.breakdownDetailPanel.hidden = false;
}

function detailLabel(dimension) {
  const labels = {
    machine: "Machine",
    account: "OS User",
    agent: "Agent",
    model: "Model",
    date: "Date"
  };
  return labels[dimension] || dimension;
}

function hideBreakdownDetail() {
  elements.detailBackdrop.hidden = true;
  elements.breakdownDetailPanel.hidden = true;
}

function renderLimits(data) {
  const observedCount = data.limits.windows.filter((window) => window.confidence === "observed").length;
  elements.limitCount.textContent = `${data.limits.windows.length} 个窗口`;
  elements.limitsObservedScore.textContent = `${observedCount}/${data.limits.windows.length}`;
  elements.limitsSummary.textContent = `${observedCount} 个可信窗口 · 缺失窗口不用历史 token 推断`;
  elements.limitList.innerHTML = data.limits.windows
    .map((window) => {
      if (window.confidence !== "observed") {
        return `
          <article class="limit-window" data-provenance="limits.windows.missing">
            <div class="limit-title">
              <strong>${window.provider} · ${window.account_label}</strong>
              <span class="status-pill missing">${statusLabel(window.confidence)}</span>
            </div>
            <p class="limit-meta">${window.window} · ${limitReasonLabel(window.reason)}</p>
          </article>
        `;
      }
      return `
        <article class="limit-window" data-provenance="limits.windows.observed">
          <div class="limit-title">
            <strong>${window.provider} · ${window.account_label}</strong>
            <span class="status-pill observed">${window.window}</span>
          </div>
          <div class="progress-track" aria-label="${window.provider} ${window.used_percent}% used">
            <div class="progress-fill" style="width: ${window.used_percent}%"></div>
          </div>
          <p class="limit-meta">剩余 ${window.remaining_percent}% · 重置 ${resetLabel(window.reset_label)} · ${window.source_type}</p>
        </article>
      `;
    })
    .join("");
}

function renderAll() {
  if (!state.data) {
    return;
  }
  renderHome(state.data);
  renderSources(state.data);
  renderBreakdown(state.data);
  renderLimits(state.data);
}

function setView(nextView) {
  state.view = nextView;
  document.body.dataset.currentView = nextView;
  document.querySelectorAll("[data-view]").forEach((view) => {
    view.classList.toggle("is-active", view.dataset.view === nextView);
  });
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    if (tab.dataset.tab === nextView) {
      tab.setAttribute("aria-current", "page");
    } else {
      tab.removeAttribute("aria-current");
    }
  });
  window.scrollTo(0, 0);
}

function setPeriod(nextPeriod) {
  state.period = nextPeriod;
  document.querySelectorAll("[data-period]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.period === nextPeriod));
  });
  renderHome(state.data);
  renderBreakdown(state.data);
}

function bindInteractions() {
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.tab));
  });

  document.querySelectorAll("[data-tab-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.tabShortcut));
  });

  elements.usageTrend.addEventListener("pointermove", (event) => {
    showTrendTooltip(event.clientX);
  });
  elements.usageTrend.addEventListener("pointerleave", hideTrendTooltip);
  elements.usageTrend.addEventListener("touchmove", (event) => {
    if (event.touches.length > 0) {
      showTrendTooltip(event.touches[0].clientX);
    }
  }, { passive: true });
  elements.usageTrend.addEventListener("touchend", hideTrendTooltip);

  document.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => setPeriod(button.dataset.period));
  });

  document.querySelectorAll("[data-breakdown]").forEach((button) => {
    button.addEventListener("click", () => {
      state.breakdown = button.dataset.breakdown;
      document.querySelectorAll("[data-breakdown]").forEach((candidate) => {
        candidate.setAttribute("aria-pressed", String(candidate === button));
      });
      renderBreakdown(state.data);
    });
  });

  elements.breakdownList.addEventListener("click", (event) => {
    const row = event.target.closest("[data-detail-index]");
    if (row) {
      showBreakdownDetail(Number(row.dataset.detailIndex));
    }
  });

  elements.refreshButton.addEventListener("click", () => {
    renderAll();
  });

  elements.detailClose.addEventListener("click", hideBreakdownDetail);
  elements.detailBackdrop.addEventListener("click", hideBreakdownDetail);

  elements.limitReminderSwitch.addEventListener("change", () => {
    elements.limitReminderStatus.textContent = elements.limitReminderSwitch.checked
      ? "Prototype: observed 窗口 reset 时提醒用户；真实通知权限留到 iOS 实现。"
      : "";
  });
}

async function loadPrototype() {
  const response = await fetch("fixture.json", { cache: "no-store" });
  state.data = await response.json();
  renderAll();
}

bindInteractions();
loadPrototype().catch((error) => {
  elements.periodTotal.textContent = "Fixture error";
  elements.periodMeta.textContent = error.message;
});

const wireframeData = {
  lastServerRead: "11:05",
  periods: {
    today: {
      title: "今天",
      total: 1284600,
      range: "2026-06-03",
      input: 336200,
      output: 197800,
      cache: 750600,
      trend: [
        ["12", 9000, 2300, 1400, 5300, 59],
        ["13", 18000, 4800, 2600, 10600, 59],
        ["14", 11000, 3000, 1700, 6300, 57],
        ["15", 26000, 6900, 4100, 15000, 58],
        ["16", 42000, 11200, 6400, 24400, 58],
        ["17", 88000, 22100, 14800, 51100, 58],
        ["18", 34000, 8900, 5200, 19900, 59],
        ["19", 21000, 5700, 3300, 12000, 57],
        ["20", 48000, 12500, 7200, 28300, 59],
        ["21", 73000, 19000, 11200, 42800, 59],
        ["22", 39000, 10100, 6100, 22800, 58],
        ["23", 144000, 36100, 22500, 85400, 59],
        ["00", 12000, 3400, 2100, 6500, 54],
        ["01", 16000, 4200, 2500, 9300, 58],
        ["02", 24000, 6400, 3800, 13800, 58],
        ["03", 88000, 22100, 14800, 51100, 58],
        ["04", 56000, 14500, 8200, 33300, 59],
        ["05", 601000, 155200, 94600, 351200, 58],
        ["06", 144000, 36100, 22500, 85400, 59],
        ["07", 96000, 25100, 14800, 56100, 58],
        ["08", 132000, 34700, 20400, 76900, 58],
        ["09", 601000, 155200, 94600, 351200, 58],
        ["10", 284000, 74400, 43800, 165800, 58],
        ["11", 1284600, 336200, 197800, 750600, 58],
      ],
    },
    week: {
      title: "周",
      total: 4793100,
      range: "本周 · 6月1日 - 6月5日",
      input: 1256300,
      output: 736400,
      cache: 2800400,
      trend: [
        ["周一", 1038200, 272400, 159800, 606000, 58],
        ["周二", 1180300, 309700, 180200, 690400, 58],
        ["周三", 1284600, 336200, 197800, 750600, 58],
        ["周四", 812000, 211800, 124600, 475600, 59],
        ["周五", 478000, 126200, 74200, 277600, 58],
        ["周六", 0, 0, 0, 0, 0],
        ["周日", 0, 0, 0, 0, 0],
      ],
    },
    month: {
      title: "月",
      total: 18420600,
      range: "近 30 天 · 5月7日 - 6月5日",
      input: 4948800,
      output: 2931700,
      cache: 10540100,
      trend: [
        ["05-07", 410000, 108000, 65000, 237000, 58],
        ["05-08", 352000, 93000, 55000, 204000, 58],
        ["05-09", 468000, 123000, 73000, 272000, 58],
        ["05-10", 288000, 76000, 45000, 167000, 58],
        ["05-11", 524000, 138000, 82000, 304000, 58],
        ["05-12", 392000, 103000, 61000, 228000, 58],
        ["05-13", 620000, 163000, 97000, 360000, 58],
        ["05-14", 742000, 195000, 116000, 431000, 58],
        ["05-15", 386000, 101000, 60000, 225000, 58],
        ["05-16", 914000, 240000, 143000, 531000, 58],
        ["05-17", 478000, 126000, 75000, 277000, 58],
        ["05-18", 536000, 141000, 84000, 311000, 58],
        ["05-19", 812000, 213000, 127000, 472000, 58],
        ["05-20", 691000, 181000, 108000, 402000, 58],
        ["05-21", 1104000, 290000, 172000, 642000, 58],
        ["05-22", 589000, 155000, 92000, 342000, 58],
        ["05-23", 760000, 200000, 119000, 441000, 58],
        ["05-24", 435000, 114000, 68000, 253000, 58],
        ["05-25", 982000, 258000, 154000, 570000, 58],
        ["05-26", 612000, 161000, 96000, 355000, 58],
        ["05-27", 744000, 195000, 116000, 433000, 58],
        ["05-28", 704200, 184600, 107200, 412400, 59],
        ["05-29", 761800, 199900, 119700, 442200, 58],
        ["05-30", 721000, 188400, 111200, 421400, 58],
        ["05-31", 916400, 240100, 139900, 536400, 59],
        ["06-01", 1038200, 272400, 159800, 606000, 58],
        ["06-02", 1180300, 309700, 180200, 690400, 58],
        ["06-03", 1284600, 336200, 197800, 750600, 58],
        ["06-04", 812000, 211800, 124600, 475600, 59],
        ["06-05", 478000, 126200, 74200, 277600, 58],
      ],
    },
  },
  sources: [
    ["mac-local", "macbook-pro", "wang", "macOS", "Codex, Claude Code", "ok", 488200, "观测 10:57 · 上报 11:02"],
    ["vpn2-root", "vpn2", "root", "Linux", "Claude Code", "ok", 311900, "观测 10:51 · 上报 10:55"],
    ["win-desktop", "windows-desktop", "wang", "Windows", "Codex", "stale", 226400, "未上报 165 分钟"],
    ["linux-build", "buildbox", "wang", "Linux", "Claude Code", "ok", 164500, "观测 10:42 · 上报 10:44"],
    ["manual-antigravity", "macbook-pro", "wang", "manual import", "Antigravity", "command_failed", 93600, "真实读取器未配置"],
  ],
  breakdowns: {
    today: {
      machine: [["macbook-pro", 581800, ["mac-local", "manual-antigravity"]], ["vpn2", 311900, ["vpn2-root"]], ["windows-desktop", 226400, ["win-desktop"]], ["buildbox", 164500, ["linux-build"]]],
      user: [["wang", 972700, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 311900, ["vpn2-root"]]],
      agent: [["Codex", 714600, ["mac-local", "win-desktop"]], ["Claude Code", 476400, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 93600, ["manual-antigravity"]]],
      model: [["gpt-5-codex", 468300, ["mac-local"]], ["claude-opus-4", 322100, ["vpn2-root"]], ["gpt-5", 246300, ["win-desktop"]], ["claude-sonnet-4", 154300, ["linux-build"]], ["unknown", 93600, ["manual-antigravity"]]],
      date: [["11", 1284600, []], ["09", 601000, []], ["06", 144000, []], ["03", 88000, []], ["00", 12000, []]],
    },
    week: {
      machine: [["macbook-pro", 2863100, ["mac-local", "manual-antigravity"]], ["vpn2", 1604200, ["vpn2-root"]], ["windows-desktop", 1111800, ["win-desktop"]], ["buildbox", 821000, ["linux-build"]]],
      user: [["wang", 4820000, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 1604200, ["vpn2-root"]]],
      agent: [["Codex", 3584300, ["mac-local", "win-desktop"]], ["Claude Code", 2364700, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 475100, ["manual-antigravity"]]],
      model: [["gpt-5-codex", 2210300, ["mac-local"]], ["claude-opus-4", 1510200, ["vpn2-root"]], ["gpt-5", 1374000, ["win-desktop"]], ["claude-sonnet-4", 854500, ["linux-build"]], ["unknown", 475100, ["manual-antigravity"]]],
      date: [["06-05", 478000, []], ["06-04", 812000, []], ["06-03", 1284600, []], ["06-02", 1180300, []], ["06-01", 1038200, []], ["周日", 0, []], ["周六", 0, []]],
    },
    month: null,
  },
  limits: [
    { groupID: "claude-personal", agent: "Claude Code", accountName: "Claude 主账号", subscription: "Claude Max 5x", window: "5h", status: "observed", remaining: 28, reset: "16:40", remainingText: "28%", source: "OAuth", tone: "hot" },
    { groupID: "claude-personal", agent: "Claude Code", accountName: "Claude 主账号", subscription: "Claude Max 5x", window: "周", status: "observed", remaining: 59, reset: "周日 08:00", remainingText: "59%", source: "OAuth", tone: "calm" },
    { groupID: "claude-work", agent: "Claude Code", accountName: "Claude 备用账号", subscription: "Claude Pro", window: "5h", status: "observed", remaining: 76, reset: "19:10", remainingText: "76%", source: "OAuth", tone: "cool" },
    { groupID: "claude-work", agent: "Claude Code", accountName: "Claude 备用账号", subscription: "Claude Pro", window: "周", status: "observed", remaining: 44, reset: "周日 08:00", remainingText: "44%", source: "OAuth", tone: "warm" },
    { groupID: "codex-main", agent: "Codex", accountName: "Codex 主账号", subscription: "ChatGPT Plus", window: "5h", status: "observed", remaining: 64, reset: "18:20", remainingText: "64%", source: "WHAM", tone: "cool" },
    { groupID: "codex-main", agent: "Codex", accountName: "Codex 主账号", subscription: "ChatGPT Plus", window: "周", status: "observed", remaining: 36, reset: "周一 00:00", remainingText: "36%", source: "WHAM", tone: "warm" },
  ],
};

wireframeData.breakdowns.month = {
  machine: [["macbook-pro", 8810000, ["mac-local", "manual-antigravity"]], ["vpn2", 4620000, ["vpn2-root"]], ["windows-desktop", 3090000, ["win-desktop"]], ["buildbox", 1900600, ["linux-build"]]],
  user: [["wang", 13800600, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 4620000, ["vpn2-root"]]],
  model: [["gpt-5-codex", 5760000, ["mac-local"]], ["claude-opus-4", 4620000, ["vpn2-root"]], ["gpt-5", 3680000, ["win-desktop"]], ["claude-sonnet-4", 2340000, ["linux-build"]], ["unknown", 2020600, ["manual-antigravity"]]],
  agent: [["Codex", 9440000, ["mac-local", "win-desktop"]], ["Claude Code", 6960000, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 2020600, ["manual-antigravity"]]],
  date: wireframeData.periods.month.trend.map((row) => [row[0], row[1], []]).reverse(),
};

const state = {
  view: "home",
  period: "today",
  dimension: "date",
  trendPoints: [],
  swipeStart: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const dimensionOrder = ["date", "machine", "user", "model", "agent"];
const dimensionTitles = { date: "Date", machine: "Machine", user: "User", model: "Model", agent: "Agent" };

function deviceTimezoneLabel() {
  const offsetMinutes = -new Date().getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const hours = Math.floor(absolute / 60);
  const minutes = absolute % 60;
  if (minutes === 0) {
    return `GMT${sign}${hours}`;
  }
  return `GMT${sign}${hours}:${String(minutes).padStart(2, "0")}`;
}

function compact(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

function compactWhole(value) {
  if (value >= 1000000) return `${Math.round(value / 1000000)}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return String(Math.round(value));
}

function axisLabel(value) {
  if (value >= 1000000) {
    const millions = value / 1000000;
    return Number.isInteger(millions) ? `${millions}M` : `${millions.toFixed(1)}M`;
  }
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return String(Math.round(value));
}

function niceAxis(maxValue) {
  if (maxValue <= 0) {
    return { max: 3, step: 1 };
  }
  const roughStep = maxValue / 3;
  const power = 10 ** Math.floor(Math.log10(roughStep));
  const fraction = roughStep / power;
  let niceFraction = 10;
  if (fraction <= 1) niceFraction = 1;
  else if (fraction <= 2) niceFraction = 2;
  else if (fraction <= 2.5) niceFraction = 2.5;
  else if (fraction <= 5) niceFraction = 5;

  const step = niceFraction * power;
  return { max: step * 3, step };
}

function statusText(status) {
  return { ok: "正常", stale: "过期", command_failed: "失败", observed: "可信", missing: "缺失" }[status] || status;
}

function limitGroups() {
  const groups = [];
  for (const window of wireframeData.limits) {
    let group = groups.find((candidate) => candidate.groupID === window.groupID);
    if (!group) {
      group = {
        groupID: window.groupID,
        agent: window.agent,
        accountName: window.accountName,
        subscription: window.subscription,
        windows: [],
      };
      groups.push(group);
    }
    group.windows.push(window);
  }
  return groups;
}

function cacheHitRate(period) {
  return Math.round((period.cache / Math.max(period.input + period.output + period.cache, 1)) * 100);
}

function adjacentPeriod(direction) {
  const periods = ["today", "week", "month"];
  const current = periods.indexOf(state.period);
  const next = Math.min(Math.max(current + direction, 0), periods.length - 1);
  return periods[next];
}

function switchView(view) {
  state.view = view;
  document.body.dataset.view = view;
  $$(".screen").forEach((screen) => screen.classList.toggle("is-active", screen.dataset.view === view));
  $$("[data-tab]").forEach((tab) => {
    tab.setAttribute("aria-current", tab.dataset.tab === view ? "page" : "false");
  });
  closeDrilldown();
}

function setPeriod(period) {
  state.period = period;
  $$("[data-period]").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.period === period ? "true" : "false");
  });
  renderHome();
  renderBreakdown();
  closeDrilldown();
}

function renderBarRow(row, max, clickable = false) {
  const [label, tokens] = row;
  const width = Math.max(4, Math.round((tokens / Math.max(max, 1)) * 100));
  const tag = clickable ? "button" : "div";
  return `
    <${tag} class="bar-row" ${clickable ? `type="button" data-row="${label}"` : ""}>
      <header><strong>${label}</strong><span>${compact(tokens)}</span></header>
      <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
    </${tag}>
  `;
}

function renderHome() {
  const period = wireframeData.periods[state.period];
  const timezone = deviceTimezoneLabel();
  $("#serverReadTime").textContent = `上次读取 ${wireframeData.lastServerRead} · ${timezone}`;
  $("#heroPeriod").textContent = period.title;
  $("#heroTotal").textContent = compact(period.total);
  $("#heroRange").textContent = period.range;
  $("#inputTokens").textContent = compact(period.input);
  $("#outputTokens").textContent = compact(period.output);
  $("#cacheTokens").textContent = compact(period.cache);
  $("#cacheHitRate").textContent = `${cacheHitRate(period)}%`;
  $("#trendRange").textContent = state.period === "today" ? "过去 24h" : period.range;
  $("#homeLimitWindows").innerHTML = renderHomeLimitWindows();
  renderTrend();
}

function renderHomeLimitWindows() {
  return limitGroups().map((group) => {
    const fiveHour = group.windows.find((window) => window.window === "5h");
    const weekly = group.windows.find((window) => window.window === "周");
    return `
    <article class="home-limit-chip">
      <span>${group.agent}</span>
      <strong>${group.accountName}</strong>
      <em>${group.subscription}</em>
      <div>
        <span>周 ${weekly?.reset || "--"}</span>
        <span>5h ${fiveHour?.reset || "--"}</span>
      </div>
    </article>
  `;
  }).join("");
}

function renderTrend() {
  const canvas = $("#trendCanvas");
  const ctx = canvas.getContext("2d");
  const rows = wireframeData.periods[state.period].trend;
  const width = canvas.width;
  const height = canvas.height;
  const pad = { top: 28, right: 18, bottom: 46, left: 58 };
  const max = Math.max(...rows.map((row) => row[1]), 1);
  const axis = niceAxis(max);
  const usableWidth = width - pad.left - pad.right;
  const usableHeight = height - pad.top - pad.bottom;

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#d6dbe4";
  ctx.lineWidth = 2;
  for (let i = 0; i < 4; i += 1) {
    const y = pad.top + (usableHeight / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const tickValue = axis.max - axis.step * i;
    if (tickValue > 0) {
      ctx.fillStyle = "#687080";
      ctx.font = "18px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText(axisLabel(tickValue), 6, y - 3);
    }
  }

  state.trendPoints = rows.map((row, index) => {
    const x = pad.left + (usableWidth / Math.max(rows.length, 1)) * (index + 0.5);
    const y = pad.top + usableHeight - (row[1] / axis.max) * usableHeight;
    return { label: row[0], tokens: row[1], input: row[2], output: row[3], cache: row[4], cacheRatio: row[5], x, y };
  });

  const barWidth = Math.max(5, Math.min(58, usableWidth / Math.max(rows.length, 1) * 0.58));
  ctx.fillStyle = "#2865c7";
  state.trendPoints.forEach((point) => {
    const barHeight = Math.max(5, height - pad.bottom - point.y);
    const x = point.x - barWidth / 2;
    const y = height - pad.bottom - barHeight;
    ctx.fillRect(x, y, barWidth, barHeight);
    point.bar = { x, y, width: barWidth, height: barHeight };
  });

  ctx.fillStyle = "#687080";
  ctx.font = "22px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "center";
  state.trendPoints.forEach((point, index) => {
    if (rows.length <= 8) {
      ctx.fillText(point.label, point.x, height - 14);
      return;
    }
    if (rows.length > 12 && index !== 0 && index !== 6 && index !== 12 && index !== 18 && index !== rows.length - 1) return;
    if (rows.length > 4 && rows.length <= 12 && index !== 0 && index !== Math.floor(rows.length / 2) && index !== rows.length - 1) return;
    ctx.fillText(point.label, point.x, height - 14);
  });
}

function showTrendTip(clientX) {
  const canvas = $("#trendCanvas");
  const tip = $("#trendTip");
  const rect = canvas.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * canvas.width;
  const point = state.trendPoints.reduce((best, next) => Math.abs(next.x - x) < Math.abs(best.x - x) ? next : best);
  tip.hidden = false;
  tip.style.left = `${Math.max(8, Math.min(rect.width - 190, (point.x / canvas.width) * rect.width - 64))}px`;
  tip.innerHTML = `<strong>${point.label} · ${compact(point.tokens)}</strong><br>Input ${compact(point.input)} · Output ${compact(point.output)}<br>Cache ${compact(point.cache)} · ${point.cacheRatio}%`;
}

function wirePeriodSwipe() {
  const phone = $(".phone");
  phone.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".chart-wrap")) return;
    state.swipeStart = {
      x: event.clientX,
      y: event.clientY,
      period: state.period,
    };
  });
  phone.addEventListener("pointerup", (event) => {
    if (!state.swipeStart || event.target.closest(".chart-wrap")) {
      state.swipeStart = null;
      return;
    }
    const dx = event.clientX - state.swipeStart.x;
    const dy = event.clientY - state.swipeStart.y;
    state.swipeStart = null;
    if (Math.abs(dx) < 54 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
    const targetPeriod = adjacentPeriod(dx < 0 ? 1 : -1);
    if (targetPeriod !== state.period) {
      setPeriod(targetPeriod);
    }
  });
}

function renderSources() {
  const healthy = wireframeData.sources.filter((source) => source[5] === "ok").length;
  $("#sourceScore").textContent = `${healthy}/${wireframeData.sources.length}`;
  $("#sourceCount").textContent = `${wireframeData.sources.length} 个来源`;
  $("#sourceList").innerHTML = wireframeData.sources.map((source) => `
    <article class="source-card">
      <div class="source-title">
        <strong>${source[1]} / ${source[2]}</strong>
        <span class="pill ${source[5]}">${statusText(source[5])}</span>
      </div>
      <p class="meta">${source[0]} · ${source[3]} · ${source[4]} · ${compact(source[6])}</p>
      <p class="meta">${source[7]}</p>
    </article>
  `).join("");
}

function setDimension(dimension) {
  state.dimension = dimension;
  $$("[data-dimension]").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.dimension === dimension ? "true" : "false");
  });
  renderBreakdown();
  closeDrilldown();
}

function renderBreakdown() {
  const rows = wireframeData.breakdowns[state.period][state.dimension] || [];
  const title = dimensionTitles[state.dimension];
  const max = Math.max(...rows.map((row) => row[1]), 1);
  $("#breakdownTitle").textContent = title;
  $("#breakdownList").innerHTML = rows.map((row) => renderBarRow(row, max, true)).join("");
}

function openDrilldown(label) {
  const rows = wireframeData.breakdowns[state.period][state.dimension] || [];
  const row = rows.find((candidate) => candidate[0] === label);
  if (!row) return;
  $("#breakdownIndex").hidden = true;
  $("#drilldownView").hidden = false;
  $("#drilldownKind").textContent = dimensionTitles[state.dimension];
  $("#drilldownTitle").textContent = row[0];
  $("#drilldownMeta").textContent = `${(row[2] || []).length || "当前"} 个来源 · 当前周期下钻`;
  $("#drilldownTotal").textContent = compact(row[1]);

  const sourceIDs = new Set(row[2] || []);
  const dimensions = dimensionOrder.filter((item) => item !== state.dimension);
  $("#drilldownSections").innerHTML = dimensions.map((dimension) => {
    const sectionRows = (wireframeData.breakdowns[state.period][dimension] || [])
      .filter((candidate) => !sourceIDs.size || (candidate[2] || []).some((id) => sourceIDs.has(id)))
      .slice(0, 4);
    if (!sectionRows.length) return "";
    const max = Math.max(...sectionRows.map((candidate) => candidate[1]), 1);
    const title = dimensionTitles[dimension];
    return `<section class="wire-card drill-card"><div class="section-head"><h2>${title}</h2><span>${sectionRows.length}</span></div>${sectionRows.map((candidate) => renderBarRow(candidate, max)).join("")}</section>`;
  }).join("");
}

function closeDrilldown() {
  $("#breakdownIndex").hidden = false;
  $("#drilldownView").hidden = true;
}

function renderLimits() {
  renderLimitVariant();
}

function renderLimitVariant() {
  const panel = $("#limitVariantPanel");
  const groups = limitGroups();
  panel.innerHTML = `
    <section class="potion-layout" aria-label="红蓝药瓶额度">
      ${groups.map((group) => {
        const fiveHour = group.windows.find((window) => window.window === "5h");
        const weekly = group.windows.find((window) => window.window === "周");
        return `
          <article class="potion-agent-card">
            <header>
              <div class="agent-title">
                <span class="agentLogo agent-logo">${group.agent === "Claude Code" ? "C" : "X"}</span>
                <div>
                  <strong>${group.accountName}</strong>
                  <em class="subscription-name">${group.subscription}</em>
                </div>
              </div>
              <span>统计时间：6月5日 ${wireframeData.lastServerRead} ${deviceTimezoneLabel()}</span>
            </header>
            <div class="potion-pair">
              <div class="potion-stat">
                <div class="potionGauge potion-gauge red-potion" style="--fill:${weekly?.remaining || 0}%">
                  <i></i>
                </div>
                <div class="potionMeta potion-meta">
                  <strong>周额度</strong>
                  <span>剩余 ${weekly?.remainingText || "--"}</span>
                  <em>刷新 ${weekly?.reset || "--"}</em>
                </div>
              </div>
              <div class="potion-stat">
                <div class="potionGauge potion-gauge blue-potion" style="--fill:${fiveHour?.remaining || 0}%">
                  <i></i>
                </div>
                <div class="potionMeta potion-meta">
                  <strong>5 小时</strong>
                  <span>剩余 ${fiveHour?.remainingText || "--"}</span>
                  <em>刷新 ${fiveHour?.reset || "--"}</em>
                </div>
              </div>
            </div>
          </article>
        `;
      }).join("")}
    </section>
  `;
}

function wireEvents() {
  wirePeriodSwipe();
  $$("[data-tab]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.tab)));
  $$("[data-shortcut]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.shortcut)));
  $$("[data-period]").forEach((button) => button.addEventListener("click", () => setPeriod(button.dataset.period)));
  $$("[data-dimension]").forEach((button) => button.addEventListener("click", () => setDimension(button.dataset.dimension)));
  $("#breakdownList").addEventListener("click", (event) => {
    const row = event.target.closest("[data-row]");
    if (row) openDrilldown(row.dataset.row);
  });
  $("#backToBreakdown").addEventListener("click", closeDrilldown);
  $("#trendCanvas").addEventListener("pointerdown", (event) => showTrendTip(event.clientX));
  $("#trendCanvas").addEventListener("pointermove", (event) => {
    if (event.buttons || event.pointerType === "touch") showTrendTip(event.clientX);
  });
  $("#trendCanvas").addEventListener("pointerleave", () => { $("#trendTip").hidden = true; });
  $("#limitReminder").addEventListener("change", (event) => {
    $("#reminderCopy").textContent = event.target.checked ? "已开启；窗口 reset 时通知" : "窗口 reset 时通知";
  });
  $("#refreshButton").addEventListener("click", () => {
    $("#refreshButton").textContent = "✓";
    window.setTimeout(() => { $("#refreshButton").textContent = "↻"; }, 500);
  });
}

function init() {
  wireEvents();
  renderHome();
  renderSources();
  renderBreakdown();
  renderLimits();
}

init();

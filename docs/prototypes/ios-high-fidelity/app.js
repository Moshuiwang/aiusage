const hifiData = {
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
  limits: [
    { groupID: "claude-main", agent: "Claude Code", logo: "C", accountName: "Claude 主账号", subscription: "Claude Max 5x", window: "5h", remaining: 28, reset: "16:40", source: "OAuth" },
    { groupID: "claude-main", agent: "Claude Code", logo: "C", accountName: "Claude 主账号", subscription: "Claude Max 5x", window: "周", remaining: 59, reset: "周日 08:00", source: "OAuth" },
    { groupID: "claude-backup", agent: "Claude Code", logo: "C", accountName: "Claude 备用账号", subscription: "Claude Pro", window: "5h", remaining: 76, reset: "19:10", source: "OAuth" },
    { groupID: "claude-backup", agent: "Claude Code", logo: "C", accountName: "Claude 备用账号", subscription: "Claude Pro", window: "周", remaining: 44, reset: "周日 08:00", source: "OAuth" },
    { groupID: "codex-main", agent: "Codex", logo: "X", accountName: "Codex 主账号", subscription: "ChatGPT Plus", window: "5h", remaining: 64, reset: "18:20", source: "WHAM" },
    { groupID: "codex-main", agent: "Codex", logo: "X", accountName: "Codex 主账号", subscription: "ChatGPT Plus", window: "周", remaining: 36, reset: "周一 00:00", source: "WHAM" },
  ],
  sources: [
    ["mac-local", "macbook-pro", "wang", "macOS", "Codex, Claude Code", "ok", 488200, "观测 10:57 · 上报 11:02"],
    ["vpn2-root", "vpn2", "root", "Linux", "Claude Code", "ok", 311900, "观测 10:51 · 上报 10:55"],
    ["win-desktop", "windows-desktop", "wang", "Windows", "Codex", "stale", 226400, "未上报 165 分钟"],
    ["linux-build", "buildbox", "wang", "Linux", "Claude Code", "ok", 164500, "观测 10:42 · 上报 10:44"],
    ["manual-antigravity", "macbook-pro", "wang", "manual import", "Antigravity", "command_failed", 93600, "真实读取器未配置"],
  ],
};

hifiData.breakdowns = {
  today: {
    date: [["11", 1284600, []], ["09", 601000, []], ["06", 144000, []], ["03", 88000, []], ["00", 12000, []]],
    machine: [["macbook-pro", 581800, ["mac-local", "manual-antigravity"]], ["vpn2", 311900, ["vpn2-root"]], ["windows-desktop", 226400, ["win-desktop"]], ["buildbox", 164500, ["linux-build"]]],
    user: [["wang", 972700, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 311900, ["vpn2-root"]]],
    model: [["gpt-5-codex", 468300, ["mac-local"]], ["claude-opus-4", 322100, ["vpn2-root"]], ["gpt-5", 246300, ["win-desktop"]], ["claude-sonnet-4", 154300, ["linux-build"]], ["unknown", 93600, ["manual-antigravity"]]],
    agent: [["Codex", 714600, ["mac-local", "win-desktop"]], ["Claude Code", 476400, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 93600, ["manual-antigravity"]]],
  },
  week: {
    date: [["06-05", 478000, []], ["06-04", 812000, []], ["06-03", 1284600, []], ["06-02", 1180300, []], ["06-01", 1038200, []], ["周日", 0, []], ["周六", 0, []]],
    machine: [["macbook-pro", 2863100, ["mac-local", "manual-antigravity"]], ["vpn2", 1604200, ["vpn2-root"]], ["windows-desktop", 1111800, ["win-desktop"]], ["buildbox", 821000, ["linux-build"]]],
    user: [["wang", 4820000, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 1604200, ["vpn2-root"]]],
    model: [["gpt-5-codex", 2210300, ["mac-local"]], ["claude-opus-4", 1510200, ["vpn2-root"]], ["gpt-5", 1374000, ["win-desktop"]], ["claude-sonnet-4", 854500, ["linux-build"]], ["unknown", 475100, ["manual-antigravity"]]],
    agent: [["Codex", 3584300, ["mac-local", "win-desktop"]], ["Claude Code", 2364700, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 475100, ["manual-antigravity"]]],
  },
  month: {
    date: hifiData.periods.month.trend.map((row) => [row[0], row[1], []]).reverse(),
    machine: [["macbook-pro", 8810000, ["mac-local", "manual-antigravity"]], ["vpn2", 4620000, ["vpn2-root"]], ["windows-desktop", 3090000, ["win-desktop"]], ["buildbox", 1900600, ["linux-build"]]],
    user: [["wang", 13800600, ["mac-local", "win-desktop", "linux-build", "manual-antigravity"]], ["root", 4620000, ["vpn2-root"]]],
    model: [["gpt-5-codex", 5760000, ["mac-local"]], ["claude-opus-4", 4620000, ["vpn2-root"]], ["gpt-5", 3680000, ["win-desktop"]], ["claude-sonnet-4", 2340000, ["linux-build"]], ["unknown", 2020600, ["manual-antigravity"]]],
    agent: [["Codex", 9440000, ["mac-local", "win-desktop"]], ["Claude Code", 6960000, ["mac-local", "vpn2-root", "linux-build"]], ["Antigravity", 2020600, ["manual-antigravity"]]],
  },
};

window.hifiData = hifiData;

const state = {
  view: "home",
  period: "today",
  dimension: "date",
  trendPoints: [],
  swipeStart: null,
};

const dimensionTitles = { date: "Date", machine: "Machine", user: "User", model: "Model", agent: "Agent" };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function brandIcon(agent) {
  if (agent.includes("Claude")) {
    return `
      <svg class="brand-icon claude" viewBox="0 0 24 24" aria-hidden="true">
        <path clip-rule="evenodd" d="M20.998 10.949H24v3.102h-3v3.028h-1.487V20H18v-2.921h-1.487V20H15v-2.921H9V20H7.488v-2.921H6V20H4.487v-2.921H3V14.05H0V10.95h3V5h17.998v5.949zM6 10.949h1.488V8.102H6v2.847zm10.51 0H18V8.102h-1.49v2.847z" fill-rule="evenodd"/>
      </svg>
    `;
  }
  if (agent.includes("Codex")) {
    return `
      <svg class="brand-icon codex" viewBox="0 0 24 24" aria-hidden="true">
        <path clip-rule="evenodd" d="M8.086.457a6.105 6.105 0 013.046-.415c1.333.153 2.521.72 3.564 1.7a.117.117 0 00.107.029c1.408-.346 2.762-.224 4.061.366l.063.03.154.076c1.357.703 2.33 1.77 2.918 3.198.278.679.418 1.388.421 2.126a5.655 5.655 0 01-.18 1.631.167.167 0 00.04.155 5.982 5.982 0 011.578 2.891c.385 1.901-.01 3.615-1.183 5.14l-.182.22a6.063 6.063 0 01-2.934 1.851.162.162 0 00-.108.102c-.255.736-.511 1.364-.987 1.992-1.199 1.582-2.962 2.462-4.948 2.451-1.583-.008-2.986-.587-4.21-1.736a.145.145 0 00-.14-.032c-.518.167-1.04.191-1.604.185a5.924 5.924 0 01-2.595-.622 6.058 6.058 0 01-2.146-1.781c-.203-.269-.404-.522-.551-.821a7.74 7.74 0 01-.495-1.283 6.11 6.11 0 01-.017-3.064.166.166 0 00.008-.074.115.115 0 00-.037-.064 5.958 5.958 0 01-1.38-2.202 5.196 5.196 0 01-.333-1.589 6.915 6.915 0 01.188-2.132c.45-1.484 1.309-2.648 2.577-3.493.282-.188.55-.334.802-.438.286-.12.573-.22.861-.304a.129.129 0 00.087-.087A6.016 6.016 0 015.635 2.31C6.315 1.464 7.132.846 8.086.457zm-.804 7.85a.848.848 0 00-1.473.842l1.694 2.965-1.688 2.848a.849.849 0 001.46.864l1.94-3.272a.849.849 0 00.007-.854l-1.94-3.393zm5.446 6.24a.849.849 0 000 1.695h4.848a.849.849 0 000-1.696h-4.848z" fill-rule="evenodd"/>
      </svg>
    `;
  }
  return `
    <svg class="brand-icon generic" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 4.5a11.5 11.5 0 1 0 0 23 11.5 11.5 0 0 0 0-23Z"/>
      <path d="M16 10v12M10 16h12"/>
    </svg>
  `;
}

function compact(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

function axisLabel(value) {
  if (value >= 1000000) {
    const millions = value / 1000000;
    return Number.isInteger(millions) ? `${millions}M` : `${millions.toFixed(1)}M`;
  }
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return `${Math.round(value)}`;
}

function cacheHitRate(period) {
  return Math.round((period.cache / Math.max(period.input + period.output + period.cache, 1)) * 100);
}

function timezoneLabel() {
  const offset = -new Date().getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hours = Math.floor(Math.abs(offset) / 60);
  const minutes = Math.abs(offset) % 60;
  return minutes ? `GMT${sign}${hours}:${String(minutes).padStart(2, "0")}` : `GMT${sign}${hours}`;
}

function niceAxis(maxValue) {
  if (maxValue <= 0) return { max: 3, step: 1 };
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

function limitGroups() {
  const groups = [];
  for (const item of hifiData.limits) {
    let group = groups.find((candidate) => candidate.groupID === item.groupID);
    if (!group) {
      group = { ...item, windows: [] };
      groups.push(group);
    }
    group.windows.push(item);
  }
  return groups;
}

function switchView(view) {
  state.view = view;
  document.body.dataset.view = view;
  $$(".screen").forEach((screen) => screen.classList.toggle("is-active", screen.dataset.view === view));
  $$("[data-tab]").forEach((tab) => tab.setAttribute("aria-current", tab.dataset.tab === view ? "page" : "false"));
  $("#drilldownView").hidden = true;
}

function setPeriod(period) {
  state.period = period;
  $$("[data-period]").forEach((button) => button.setAttribute("aria-pressed", button.dataset.period === period ? "true" : "false"));
  renderHome();
  renderBreakdown();
}

function setDimension(dimension) {
  state.dimension = dimension;
  $$("[data-dimension]").forEach((button) => button.setAttribute("aria-pressed", button.dataset.dimension === dimension ? "true" : "false"));
  renderBreakdown();
}

function renderHome() {
  const period = hifiData.periods[state.period];
  $("#serverReadTime").textContent = `上次读取 ${hifiData.lastServerRead} · ${timezoneLabel()}`;
  $("#heroPeriod").textContent = period.title;
  $("#heroTotal").textContent = compact(period.total);
  $("#heroRange").textContent = period.range;
  $("#inputTokens").textContent = compact(period.input);
  $("#outputTokens").textContent = compact(period.output);
  $("#cacheTokens").textContent = compact(period.cache);
  $("#cacheHitRate").textContent = `${cacheHitRate(period)}%`;
  $("#trendRange").textContent = state.period === "today" ? "过去 24h" : period.range;
  $("#homeLimitWindows").innerHTML = renderRefreshCards();
  drawTrend();
}

function renderRefreshCards() {
  return limitGroups().map((group) => {
    const weekly = group.windows.find((item) => item.window === "周");
    const fiveHour = group.windows.find((item) => item.window === "5h");
    return `
      <article class="refresh-card">
        <div>
          <span>${group.agent}</span>
          <strong>${group.accountName}</strong>
          <em>${group.subscription}</em>
        </div>
        <div class="refresh-times">
          <b>周 ${weekly?.reset || "--"}</b>
          <b>5h ${fiveHour?.reset || "--"}</b>
        </div>
      </article>
    `;
  }).join("");
}

function drawTrend() {
  const canvas = $("#trendCanvas");
  const ctx = canvas.getContext("2d");
  const rows = hifiData.periods[state.period].trend;
  const width = canvas.width;
  const height = canvas.height;
  const pad = { top: 24, right: 18, bottom: 42, left: 58 };
  const axis = niceAxis(Math.max(...rows.map((row) => row[1]), 1));
  const usableWidth = width - pad.left - pad.right;
  const usableHeight = height - pad.top - pad.bottom;

  ctx.clearRect(0, 0, width, height);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(102,112,133,0.18)";
  for (let index = 0; index < 4; index += 1) {
    const y = pad.top + (usableHeight / 3) * index;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const value = axis.max - axis.step * index;
    if (value > 0) {
      ctx.fillStyle = "#667085";
      ctx.font = "18px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText(axisLabel(value), 8, y - 4);
    }
  }

  state.trendPoints = rows.map((row, index) => {
    const x = pad.left + (usableWidth / rows.length) * (index + 0.5);
    const y = pad.top + usableHeight - (row[1] / axis.max) * usableHeight;
    return { label: row[0], tokens: row[1], input: row[2], output: row[3], cache: row[4], cacheRatio: row[5], x, y };
  });

  const barWidth = Math.max(5, Math.min(52, (usableWidth / rows.length) * 0.62));
  const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
  gradient.addColorStop(0, "#58a6ff");
  gradient.addColorStop(1, "#2563d9");
  ctx.fillStyle = gradient;
  state.trendPoints.forEach((point) => {
    const barHeight = Math.max(5, height - pad.bottom - point.y);
    const x = point.x - barWidth / 2;
    const y = height - pad.bottom - barHeight;
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barHeight, 4);
    ctx.fill();
  });

  ctx.fillStyle = "#667085";
  ctx.font = "18px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "center";
  state.trendPoints.forEach((point, index) => {
    if (rows.length <= 8 || index === 0 || index === 6 || index === 12 || index === 18 || index === rows.length - 1) {
      ctx.fillText(point.label, point.x, height - 13);
    }
  });
}

function showTrendTip(clientX) {
  const canvas = $("#trendCanvas");
  const tip = $("#trendTip");
  const rect = canvas.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * canvas.width;
  const point = state.trendPoints.reduce((best, next) => Math.abs(next.x - x) < Math.abs(best.x - x) ? next : best);
  tip.hidden = false;
  tip.style.left = `${Math.max(8, Math.min(rect.width - 154, (point.x / canvas.width) * rect.width - 72))}px`;
  tip.innerHTML = `<strong>${point.label} · ${compact(point.tokens)}</strong><br>Input ${compact(point.input)} · Output ${compact(point.output)}<br>Cache ${compact(point.cache)} · ${point.cacheRatio}%`;
}

function renderLimits() {
  $("#limitList").innerHTML = limitGroups().map((group) => {
    const weekly = group.windows.find((item) => item.window === "周");
    const fiveHour = group.windows.find((item) => item.window === "5h");
    return `
      <article class="quota-card">
        <div class="quota-top">
          <div class="agent-lockup">
            <span class="agent-logo">${brandIcon(group.agent)}</span>
            <div class="quota-copy">
              <strong>${group.accountName}</strong>
              <p>${group.agent} · ${group.subscription}</p>
            </div>
          </div>
          <span class="stat-time">统计 ${hifiData.lastServerRead} · ${timezoneLabel()}</span>
        </div>
        <div class="quota-pair">
          ${renderQuotaStat("周额度", weekly)}
          ${renderQuotaStat("5 小时", fiveHour)}
        </div>
      </article>
    `;
  }).join("");
}

function quotaTone(remaining) {
  if (remaining < 35) return "danger";
  if (remaining < 60) return "warning";
  return "healthy";
}

function renderQuotaStat(label, item) {
  const remaining = item?.remaining || 0;
  const tone = quotaTone(remaining);
  return `
    <div class="quota-stat ${tone}">
      <div class="quota-gauge" style="--value:${remaining}">
        <span>${remaining}%</span>
      </div>
      <div class="quota-meta">
        <div>
          <strong>${label}</strong>
          <em>刷新 ${item?.reset || "--"}</em>
        </div>
        <div class="quota-progress" style="--value:${remaining}%">
          <i></i>
        </div>
      </div>
    </div>
  `;
}

function renderBarRow(row, max) {
  const [label, value] = row;
  const width = Math.max(3, Math.round((value / Math.max(max, 1)) * 100));
  return `
    <button class="bar-row" type="button" data-row="${label}">
      <header><strong>${label}</strong><span>${compact(value)}</span></header>
      <div class="track"><div class="fill" style="width:${width}%"></div></div>
    </button>
  `;
}

function renderBreakdown() {
  const rows = hifiData.breakdowns[state.period][state.dimension] || [];
  const max = Math.max(...rows.map((row) => row[1]), 1);
  $("#breakdownTitle").textContent = dimensionTitles[state.dimension];
  $("#breakdownCaption").textContent = state.dimension === "date" ? "最近的日期在最上" : "Tokens";
  $("#breakdownList").innerHTML = rows.map((row) => renderBarRow(row, max)).join("");
}

function openDrilldown(label) {
  const rows = hifiData.breakdowns[state.period][state.dimension] || [];
  const row = rows.find((candidate) => candidate[0] === label);
  if (!row) return;
  $("#drilldownKind").textContent = dimensionTitles[state.dimension];
  $("#drilldownTitle").textContent = row[0];
  $("#drilldownTotal").textContent = compact(row[1]);
  $("#drilldownMeta").textContent = `${state.period} · ${state.dimension} · 当前筛选`;
  $("#drilldownView").hidden = false;
}

function statusText(status) {
  return { ok: "正常", stale: "过期", command_failed: "失败" }[status] || status;
}

function sourceBrandIcons(agentNames) {
  return agentNames.split(",").map((agent) => brandIcon(agent.trim())).join("");
}

function renderSources() {
  const ok = hifiData.sources.filter((source) => source[5] === "ok").length;
  $("#sourceScore").textContent = `${ok}/${hifiData.sources.length}`;
  $("#sourceCount").textContent = `${hifiData.sources.length} 个来源`;
  $("#sourceList").innerHTML = hifiData.sources.map((source) => `
    <article class="source-card">
      <div class="source-title">
        <div class="source-name">
          <span class="source-icons">${sourceBrandIcons(source[4])}</span>
          <strong>${source[1]} / ${source[2]}</strong>
        </div>
        <span class="pill ${source[5]}">${statusText(source[5])}</span>
      </div>
      <p>${source[0]} · ${source[3]} · ${source[4]} · ${compact(source[6])}</p>
      <p>${source[7]}</p>
    </article>
  `).join("");
}

function wireEvents() {
  $$("[data-tab]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.tab)));
  $$("[data-shortcut]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.shortcut)));
  $$("[data-period]").forEach((button) => button.addEventListener("click", () => setPeriod(button.dataset.period)));
  $$("[data-dimension]").forEach((button) => button.addEventListener("click", () => setDimension(button.dataset.dimension)));
  $("#breakdownList").addEventListener("click", (event) => {
    const row = event.target.closest("[data-row]");
    if (row) openDrilldown(row.dataset.row);
  });
  $("#backToBreakdown").addEventListener("click", () => { $("#drilldownView").hidden = true; });
  $("#trendCanvas").addEventListener("pointerdown", (event) => showTrendTip(event.clientX));
  $("#trendCanvas").addEventListener("pointermove", (event) => {
    if (event.buttons || event.pointerType === "touch") showTrendTip(event.clientX);
  });
  $("#trendCanvas").addEventListener("pointerleave", () => { $("#trendTip").hidden = true; });
  $("#limitReminder").addEventListener("change", (event) => {
    $("#reminderCopy").textContent = event.target.checked ? "已开启；窗口刷新时通知" : "窗口刷新时通知";
  });
  $("#refreshButton").addEventListener("click", () => {
    $("#refreshButton").classList.add("is-done");
    window.setTimeout(() => $("#refreshButton").classList.remove("is-done"), 450);
  });
}

function init() {
  wireEvents();
  renderHome();
  renderLimits();
  renderBreakdown();
  renderSources();
}

init();

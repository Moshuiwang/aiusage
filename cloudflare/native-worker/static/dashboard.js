(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PERIODS = [
    { id: "today", label: "今天", axis: ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00", "23:59"], buckets: 24 },
    { id: "week", label: "本周", axis: ["Mon", "Wed", "Fri", "Sun"], buckets: 7 },
    { id: "month", label: "本月", axis: ["06-01", "06-10", "06-20", "now"], buckets: 30 },
    { id: "all", label: "全部", axis: ["Jan", "Apr", "Jul", "Oct"], buckets: 12 },
  ];
  const PROVIDER_COLORS = {
    claude: { outer: "#DA7756", inner: "#EAA882", label: "Claude" },
    codex: { outer: "#0a84ff", inner: "#5ac8fa", label: "OpenAI" },
    openai: { outer: "#0a84ff", inner: "#5ac8fa", label: "OpenAI" },
    gemini: { outer: "#34c759", inner: "#86efac", label: "Gemini" },
    deepseek: { outer: "#5ac8fa", inner: "#93dcfc", label: "DeepSeek" },
    unknown: { outer: "#8e8e93", inner: "#aeaeb2", label: "Unknown" },
  };
  const HOST_COLORS = ["#34c759", "#0a84ff", "#DA7756", "#5ac8fa", "#EAA882"];

  let periodId = "today";
  let latestSnapshot = null;
  let activeFilter = readFilterFromLocation();
  let countFrom = 0;
  let countRaf = 0;

  const el = {
    periodSelector: document.getElementById("periodSelector"),
    themeToggle: document.getElementById("themeToggle"),
    clearUserFilter: document.getElementById("clearUserFilter"),
    syncChip: document.getElementById("syncChip"),
    periodEyebrow: document.getElementById("periodEyebrow"),
    scopeLabel: document.getElementById("scopeLabel"),
    totalTokens: document.getElementById("totalTokens"),
    heroDelta: document.getElementById("heroDelta"),
    inputTokens: document.getElementById("inputTokens"),
    outputTokens: document.getElementById("outputTokens"),
    cacheTokensCompact: document.getElementById("cacheTokensCompact"),
    cacheHitLabel: document.getElementById("cacheHitLabel"),
    streamChart: document.getElementById("streamChart"),
    streamTooltip: document.getElementById("streamTooltip"),
    axisRow: document.getElementById("axisRow"),
    emptyState: document.getElementById("emptyState"),
    dashboardContent: document.getElementById("dashboardContent"),
    limitsSection: document.getElementById("limitsSection"),
    limitsGrid: document.getElementById("limitsGrid"),
    limitsCount: document.getElementById("limitsCount"),
    sourceCards: document.getElementById("sourceCards"),
    byAgentList: document.getElementById("byAgentList"),
    modelList: document.getElementById("modelList"),
    machineCount: document.getElementById("machineCount"),
    hostDonut: document.getElementById("hostDonut"),
    hostTooltip: document.getElementById("hostTooltip"),
    hostLegend: document.getElementById("hostLegend"),
    onlineCount: document.getElementById("onlineCount"),
    healthGrid: document.getElementById("healthGrid"),
    errorCard: document.getElementById("errorCard"),
    errorMsg: document.getElementById("errorMsg"),
  };

  function fmt(n) {
    const value = Number(n || 0);
    if (value >= 1e9) return `${trimFixed(value / 1e9, 2)}B`;
    if (value >= 1e6) return `${trimFixed(value / 1e6, value >= 1e7 ? 1 : 2)}M`;
    if (value >= 1e3) return `${trimFixed(value / 1e3, value >= 1e5 ? 0 : 1)}k`;
    return String(Math.round(value));
  }

  function fmtHero(n) {
    const value = Number(n || 0);
    if (value >= 1e9) return `${trimFixed(value / 1e9, 2)}B`;
    if (value >= 1e6) return `${trimFixed(value / 1e6, 1)}M`;
    if (value >= 1e3) return `${trimFixed(value / 1e3, 1)}k`;
    return String(Math.round(value));
  }

  function trimFixed(value, digits) {
    return value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  }

  function todayString() {
    const d = new Date();
    const tzOffset = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - tzOffset).toISOString().slice(0, 10);
  }

  async function loadSummary() {
    const params = new URLSearchParams({ date: todayString(), period: periodId });
    if (activeFilter.machine) params.set("machine", activeFilter.machine);
    if (activeFilter.account) params.set("account", activeFilter.account);
    const response = await fetch(`/api/summary?${params.toString()}`, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    latestSnapshot = await response.json();
    render();
  }

  function buildData(snapshot) {
    const summary = snapshot.summary || {};
    const period = PERIODS.find((p) => p.id === periodId) || PERIODS[0];
    const total = Number(summary.total_tokens || 0);
    const input = Number(summary.input_tokens || 0);
    const output = Number(summary.output_tokens || 0);
    const cache = Number(summary.cache_read_tokens || 0);
    const cachePct = total > 0 ? cache / total : 0;
    const hosts = normalizeGroups(snapshot.groups && snapshot.groups.by_machine, total, "host");
    const agents = normalizeGroups(snapshot.groups && snapshot.groups.by_agent, total, "agent");
    const trend = normalizeTrend(snapshot.trend, period);
    const agentTrend = buildAgentTrend(snapshot.trend, trend.points);
    return { period: { ...period, axis: trend.axis }, total, input, output, cache, cachePct, hosts, agents, trend, agentTrend };
  }

  /** 从 trend.by_agent 构建按 agent 分组的每柱 token 数据。 */
  function buildAgentTrend(rawTrend, points) {
    const bucketCount = points.length;
    const byAgent = (rawTrend && rawTrend.by_agent) || [];
    if (!byAgent.length) return { agents: [], agentOrder: [] };
    const agents = {};
    const agentOrder = [];
    byAgent.forEach((entry) => {
      const key = agentKey(entry.agent || entry.name || "unknown");
      const label = displayAgent(entry.agent || entry.name || "unknown");
      const color = colorForAgent(entry.agent || entry.name || "unknown");
      const values = entry.values || [];
      if (!agents[key]) {
        agents[key] = { key, label, color, values: new Array(bucketCount).fill(0) };
        agentOrder.push(key);
      }
      for (let i = 0; i < bucketCount; i++) {
        agents[key].values[i] += Number(values[i] || 0);
      }
    });
    return { agents, agentOrder };
  }


  function normalizeGroups(groups, total, type) {
    return (groups || [])
      .map((item, index) => {
        const name = item.name || item.source_id || "unknown";
        const account = item.account || "";
        const tokens = Number(item.total_tokens || 0);
        const displayName = item.display_name || (account ? `${name} · ${account}` : name);
        return {
          name,
          account,
          displayName,
          users: normalizeMachineUsers(item.users || [], name, total),
          kind: type === "host" ? hostKind(name, account) : displayAgent(name),
          tokens,
          share: total > 0 ? tokens / total : 0,
          color: type === "host" ? HOST_COLORS[index % HOST_COLORS.length] : colorForAgent(name),
        };
      })
      .filter((item) => item.tokens > 0);
  }

  function normalizeMachineUsers(users, machine, total) {
    return users.map((user) => {
      const tokens = Number(user.total_tokens || 0);
      return {
        machine: user.machine || machine,
        account: user.account || "unknown",
        displayName: user.display_name || `${user.machine || machine} · ${user.account || "unknown"}`,
        tokens,
        share: total > 0 ? tokens / total : 0,
      };
    }).sort((a, b) => b.tokens - a.tokens);
  }

  function agentKey(name) {
    const raw = String(name || "").toLowerCase();
    if (raw.includes("claude")) return "claude";
    if (raw.includes("codex") || raw.includes("openai") || raw.includes("gpt")) return "codex";
    if (raw.includes("gemini")) return "gemini";
    if (raw.includes("deepseek")) return "deepseek";
    return "unknown";
  }

  function displayAgent(name) {
    const key = agentKey(name);
    if (key === "claude") return "Claude";
    if (key === "codex") return "OpenAI";
    if (key === "gemini") return "Gemini";
    if (key === "deepseek") return "DeepSeek";
    return String(name || "Unknown");
  }

  function colorForAgent(name) {
    const key = agentKey(name);
    if (key === "claude") return "#DA7756";
    if (key === "codex") return "#0a84ff";
    if (key === "gemini") return "#34c759";
    if (key === "deepseek") return "#5ac8fa";
    return "#8e8e93";
  }

  function hostKind(name, account) {
    const raw = String(name || "").toLowerCase();
    if (raw.includes("mac")) return "macOS · live";
    if (raw.includes("ubuntu")) return account ? `Linux · ${account}` : "Linux";
    if (raw.includes("gpu")) return account ? `Linux GPU · ${account}` : "Linux GPU";
    return account ? `Source · ${account}` : "Source";
  }

  function normalizeTrend(trend, period) {
    if (trend && Array.isArray(trend.points) && trend.points.length) {
      const points = trend.points.map((point) => ({
        label: shortDateLabel(point.date || point.hour || point.bucket || point.label, trend.granularity),
        tokens: Number(point.total_tokens ?? point.tokens ?? 0),
        inputTokens: Number(point.input_tokens || 0),
        outputTokens: Number(point.output_tokens || 0),
        cacheTokens: Number(point.cache_tokens || point.cache_read_tokens || 0),
      }));
      return { points, axis: axisForPoints(points, period.axis) };
    }
    if (trend && Array.isArray(trend.axis) && Array.isArray(trend.by_token_type)) {
      const totals = [];
      trend.by_token_type.forEach((row) => {
        (row.values || []).forEach((value, index) => {
          totals[index] = (totals[index] || 0) + Number(value || 0);
        });
      });
      const points = totals.map((tokens, index) => ({
        label: shortDateLabel(trend.axis[index], trend.granularity),
        tokens,
        inputTokens: 0,
        outputTokens: 0,
        cacheTokens: 0,
      }));
      return { points, axis: axisForPoints(points, period.axis) };
    }
    return {
      axis: period.axis,
      points: Array.from({ length: period.buckets }, (_, index) => ({ label: "", tokens: 0, inputTokens: 0, outputTokens: 0, cacheTokens: 0 })),
    };
  }

  function axisForPoints(points, fallback) {
    if (!points.length) return fallback;
    if (points.length <= 4) return points.map((point) => point.label || "");
    const indexes = [0, Math.floor(points.length / 4), Math.floor(points.length / 2), Math.floor((points.length * 3) / 4), points.length - 1];
    return indexes.map((index) => points[Math.min(points.length - 1, index)].label || "");
  }

  function shortDateLabel(value, granularity) {
    const text = String(value || "");
    if (granularity === "hour" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) return text.slice(11, 16);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text.slice(5);
    if (/^\d{2}:\d{2}/.test(text)) return text.slice(0, 5);
    return text;
  }

  function render() {
    if (!latestSnapshot) return;
    const data = buildData(latestSnapshot);
    const hasUsage = data.total > 0;
    const periodLabel = data.period.label;

    el.periodEyebrow.textContent = periodLabel;
    animateTotal(data.total);
    el.scopeLabel.textContent = `Input ${fmt(data.input)} · Output ${fmt(data.output)} · Cache ${fmt(data.cache)}`;
    el.inputTokens.textContent = fmt(data.input);
    el.outputTokens.textContent = fmt(data.output);
    el.cacheTokensCompact.textContent = fmt(data.cache);
    el.cacheHitLabel.textContent = `Cache Hit ${Math.round(data.cachePct * 100)}%`;
    renderDelta(latestSnapshot.generated_at);
    updateSyncChip(latestSnapshot.generated_at);
    renderScope(latestSnapshot.summary || {});

    el.emptyState.hidden = hasUsage;
    el.dashboardContent.hidden = false;

    renderBarTrend(data.trend.points, data.period.axis, data.agentTrend);
    renderLimits(latestSnapshot.limits || []);
    renderSourceCards(data.hosts, latestSnapshot.source_status || []);
    renderBreakdown(el.byAgentList, data.agents, data.total);
    renderSources(latestSnapshot.source_status || []);
  }

  function renderDelta(generatedAt) {
    if (generatedAt) {
      el.heroDelta.textContent = "Live";
      el.heroDelta.classList.add("neutral");
      el.heroDelta.classList.remove("up", "down");
      return;
    }
    el.heroDelta.textContent = "No sync";
    el.heroDelta.classList.add("neutral");
    el.heroDelta.classList.remove("up", "down");
  }

  function animateTotal(target) {
    const from = countFrom;
    const start = performance.now();
    cancelAnimationFrame(countRaf);
    function tick(now) {
      const t = Math.min(1, (now - start) / 500);
      const eased = 1 - Math.pow(1 - t, 3);
      el.totalTokens.textContent = fmtHero(from + (target - from) * eased);
      if (t < 1) {
        countRaf = requestAnimationFrame(tick);
      } else {
        countFrom = target;
      }
    }
    countRaf = requestAnimationFrame(tick);
  }

  function renderBarTrend(points, axis, agentTrend) {
    const width = 720;
    const height = 134;
    const plotTop = 10;
    const plotBottom = 24;
    const plotHeight = height - plotTop - plotBottom;
    const values = (points || []).map((point) => Math.max(0, Number(point.tokens || 0)));
    const rawMax = Math.max(...values, 0);
    const yTicks = niceChartTicks(rawMax);
    const max = yTicks[0].value || 1;
    const barGap = 4;
    const barWidth = Math.max(4, (width - barGap * Math.max(0, values.length - 1)) / Math.max(1, values.length));

    const hasAgentData = agentTrend && agentTrend.agentOrder && agentTrend.agentOrder.length > 0;

    el.streamChart.replaceChildren();
    el.streamChart.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const refY = plotTop;
    el.streamChart.append(
      svg("line", { x1: 0, y1: refY, x2: width, y2: refY, stroke: "var(--ref-line)", "stroke-dasharray": "4 4", "stroke-width": 1 }),
      svg("text", { x: width, y: refY - 3, "text-anchor": "end", fill: "currentColor", "font-size": 10, "font-weight": 600, opacity: 0.45 }, formatAxisTick(max))
    );

    if (hasAgentData) {
      // 堆叠柱形图：按 agent 分色，从底部向上堆叠
      const order = agentTrend.agentOrder;
      values.forEach((totalValue, index) => {
        const x = index * (barWidth + barGap);
        let yOffset = 0; // 从底部累计
        // 逆序绘制：先画最底层的 agent，再依次往上
        for (let a = order.length - 1; a >= 0; a--) {
          const agentInfo = agentTrend.agents[order[a]];
          if (!agentInfo) continue;
          const segValue = agentInfo.values[index] || 0;
          if (segValue <= 0) continue;
          const segHeight = Math.max(1, (segValue / max) * plotHeight);
          const y = plotTop + plotHeight - yOffset - segHeight;
          const isBottom = yOffset === 0;
          const isTop = (yOffset + segValue) >= totalValue - 0.5;
          const rx = (isBottom && isTop) ? 3 : isTop ? 3 : isBottom ? 1 : 0;
          const rect = svg("rect", {
            x,
            y,
            width: Math.max(2, barWidth),
            height: segHeight,
            rx,
            fill: agentInfo.color,
            opacity: 0.86,
          });
          rect.addEventListener("mousemove", (event) => showStreamTooltip(index, event, points, agentTrend));
          rect.addEventListener("mouseleave", () => { el.streamTooltip.hidden = true; });
          el.streamChart.appendChild(rect);
          yOffset += segHeight;
        }
        // 如有零高度柱，画一个最小柱占位
        if (yOffset === 0 && totalValue > 0) {
          const barHeight = Math.max(3, (totalValue / max) * plotHeight);
          const rect = svg("rect", {
            x,
            y: plotTop + plotHeight - barHeight,
            width: Math.max(2, barWidth),
            height: barHeight,
            rx: 3,
            fill: "#8e8e93",
            opacity: 0.86,
          });
          rect.addEventListener("mousemove", (event) => showStreamTooltip(index, event, points, agentTrend));
          rect.addEventListener("mouseleave", () => { el.streamTooltip.hidden = true; });
          el.streamChart.appendChild(rect);
        }
      });
    } else {
      // 无 agent 分组时回退为单色柱
      const defs = svg("defs");
      const gradient = svg("linearGradient", { id: "barGradient", x1: "0", y1: "0", x2: "0", y2: "1" });
      gradient.append(
        svg("stop", { offset: "0%", "stop-color": "#4a9eff" }),
        svg("stop", { offset: "100%", "stop-color": "#007aff" })
      );
      defs.appendChild(gradient);
      el.streamChart.appendChild(defs);

      values.forEach((value, index) => {
        const barHeight = Math.max(3, (value / max) * plotHeight);
        const x = index * (barWidth + barGap);
        const y = plotTop + plotHeight - barHeight;
        const rect = svg("rect", {
          x, y,
          width: Math.max(2, barWidth),
          height: barHeight,
          rx: 3,
          fill: "url(#barGradient)",
          opacity: 0.86,
        });
        rect.addEventListener("mousemove", (event) => showStreamTooltip(index, event, points, null));
        rect.addEventListener("mouseleave", () => { el.streamTooltip.hidden = true; });
        el.streamChart.appendChild(rect);
      });
    }

    el.axisRow.replaceChildren();
    (axis || []).forEach((label) => {
      const node = document.createElement("span");
      node.textContent = label;
      el.axisRow.appendChild(node);
    });

    // 渲染图例
    renderChartLegend(hasAgentData ? agentTrend : null);
  }

  /** 在柱形图下方渲染 agent 图例 */
  function renderChartLegend(agentTrend) {
    let legendRow = document.getElementById("chartLegend");
    if (!legendRow) {
      legendRow = document.createElement("div");
      legendRow.id = "chartLegend";
      legendRow.className = "chart-legend";
      // 插入到 axisRow 之后
      el.axisRow.parentNode.insertBefore(legendRow, el.axisRow.nextSibling);
    }
    legendRow.replaceChildren();

    if (!agentTrend || !agentTrend.agentOrder || !agentTrend.agentOrder.length) return;

    // 去重：agentOrder 可能有重复 key（如 codex 和 openai 合并为同一 key）
    const seen = new Set();
    agentTrend.agentOrder.forEach((key) => {
      if (seen.has(key)) return;
      seen.add(key);
      const info = agentTrend.agents[key];
      if (!info) return;
      const item = document.createElement("span");
      item.className = "chart-legend-item";
      const dot = document.createElement("span");
      dot.className = "chart-legend-dot";
      dot.style.background = info.color;
      const label = document.createElement("span");
      label.textContent = info.label;
      item.append(dot, label);
      legendRow.appendChild(item);
    });
  }

  function showStreamTooltip(index, event, points, agentTrend) {
    const point = points[index] || {};
    let agentLines = "";
    if (agentTrend && agentTrend.agentOrder) {
      const seen = new Set();
      agentTrend.agentOrder.forEach((key) => {
        if (seen.has(key)) return;
        seen.add(key);
        const info = agentTrend.agents[key];
        if (!info) return;
        const val = info.values[index] || 0;
        if (val <= 0) return;
        agentLines += `<div><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${escapeHtml(info.color)};margin-right:4px;vertical-align:middle"></span>${escapeHtml(info.label)} <b>${fmt(val)}</b></div>`;
      });
    }
    el.streamTooltip.innerHTML = `
      <strong>${escapeHtml(point.label || "当前点")}</strong>
      <div>Total <b>${fmt(point.tokens || 0)}</b></div>
      ${agentLines}
      <div style="margin-top:2px;border-top:0.5px solid var(--border);padding-top:2px">Input <b>${fmt(point.inputTokens || 0)}</b> · Output <b>${fmt(point.outputTokens || 0)}</b></div>
      <div>Cache <b>${fmt(point.cacheTokens || 0)}</b></div>
    `;
    el.streamTooltip.hidden = false;
    const tipRect = el.streamTooltip.getBoundingClientRect();
    const x = event.clientX + 14 + tipRect.width <= window.innerWidth
      ? event.clientX + 14
      : event.clientX - tipRect.width - 14;
    const y = event.clientY + 14 + tipRect.height <= window.innerHeight
      ? event.clientY + 14
      : event.clientY - tipRect.height - 14;
    el.streamTooltip.style.left = `${Math.max(10, x)}px`;
    el.streamTooltip.style.top = `${Math.max(10, y)}px`;
  }

  function renderLimits(limits) {
    const groups = normalizeLimitRows(limits);
    renderQuotaCards(groups);
  }

  function renderQuotaCards(groups) {
    el.limitsSection.hidden = false;
    el.limitsGrid.replaceChildren();
    const rows = groups.flatMap((group) => group.rows);
    const lastUpdated = rows.reduce((latest, row) => maxIso(latest, row.observed_at), "");
    el.limitsCount.textContent = rows.length
      ? `最近更新 ${formatDateTime(lastUpdated)} · ${rows.length} windows`
      : "暂无可信额度";

    const claude = groups.find((group) => group.provider === "claude") || emptyLimitGroup("claude");
    const openai = groups.find((group) => group.provider === "codex" || group.provider === "openai") || emptyLimitGroup("codex");
    el.limitsGrid.append(renderLimitGroup(claude), renderLimitGroup(openai));
  }

  function normalizeLimitRows(limits) {
    const rows = (limits || [])
      .filter((limit) => {
        const provider = normalizedProvider(limit.provider);
        return (provider === "claude" || provider === "codex" || provider === "openai") && isObservedLimit(limit) && !isExpiredLimit(limit);
      })
      .sort((a, b) => {
        const observedDiff = Date.parse(b.observed_at || 0) - Date.parse(a.observed_at || 0);
        if (observedDiff) return observedDiff;
        const sourceDiff = String(a.source_id || "").localeCompare(String(b.source_id || ""));
        if (sourceDiff) return sourceDiff;
        return windowRank(a.window) - windowRank(b.window);
      });

    const groups = new Map();
    rows.forEach((limit) => {
      const provider = normalizedProvider(limit.provider);
      const group = groups.get(provider) || { provider, source_id: limit.source_id || provider, observed_at: "", rows: [] };
      group.source_id = group.source_id || limit.source_id || provider;
      group.observed_at = maxIso(group.observed_at, limit.observed_at);
      group.rows.push(limit);
      groups.set(provider, group);
    });

    return Array.from(groups.values()).sort((a, b) => providerRank(a.provider) - providerRank(b.provider));
  }

  function renderLimitGroup(group) {
    const colors = PROVIDER_COLORS[group.provider] || PROVIDER_COLORS.codex;
    const session = bestLimit(group.rows, "session");
    const week = bestLimit(group.rows, "week");
    const node = document.createElement("div");
    node.className = "quota-item limit-group";
    node.appendChild(quotaRing(colors, session, week));

    const meta = document.createElement("div");
    meta.className = "quota-meta";
    meta.append(
      quotaMetaRow("5h", session, colors.outer),
      quotaMetaRow("7d", week, colors.inner)
    );
    node.appendChild(meta);
    return node;
  }

  function quotaRing(colors, session, week) {
    const outerUsed = Number(session?.used_percent ?? 0);
    const innerUsed = Number(week?.used_percent ?? 0);
    const outerDash = `${(outerUsed / 100) * 251.3} 251.3`;
    const innerDash = `${(innerUsed / 100) * 163.4} 163.4`;
    const ring = svg("svg", { class: "quota-ring", viewBox: "0 0 100 100" });
    ring.append(
      svg("circle", { cx: 50, cy: 50, r: 40, fill: "none", stroke: "var(--ring-track)", "stroke-width": 10 }),
      svg("circle", { cx: 50, cy: 50, r: 26, fill: "none", stroke: "var(--ring-track)", "stroke-width": 9 }),
      svg("circle", { cx: 50, cy: 50, r: 40, fill: "none", stroke: colors.outer, "stroke-width": 10, "stroke-dasharray": outerDash, "stroke-linecap": "round", transform: "rotate(-90 50 50)" }),
      svg("circle", { cx: 50, cy: 50, r: 26, fill: "none", stroke: colors.inner, "stroke-width": 9, "stroke-dasharray": innerDash, "stroke-linecap": "round", transform: "rotate(-90 50 50)" }),
      svg("text", { x: 50, y: 53, "text-anchor": "middle" }, colors.label)
    );
    return ring;
  }

  function quotaMetaRow(label, limit, color) {
    const row = document.createElement("div");
    row.className = "quota-row";
    const key = document.createElement("span");
    key.textContent = label;
    key.style.color = color;
    const pct = document.createElement("strong");
    pct.textContent = limit ? `${Math.round(Number(limit.used_percent || 0))}%` : "--";
    pct.style.color = color;
    const rem = document.createElement("span");
    rem.textContent = limit ? remainingText(limit) : "无可信数据";
    row.append(key, pct, rem);
    return row;
  }

  function bestLimit(rows, windowKind) {
    const candidates = (rows || []).filter((row) => {
      const rank = windowRank(row.window);
      return windowKind === "session" ? rank === 1 : rank === 2;
    });
    return candidates[0] || null;
  }

  function emptyLimitGroup(provider) {
    return { provider, source_id: provider, observed_at: "", rows: [] };
  }

  function normalizedProvider(provider) {
    const raw = String(provider || "").toLowerCase();
    if (raw.includes("claude")) return "claude";
    if (raw.includes("openai")) return "openai";
    if (raw.includes("codex")) return "codex";
    return raw;
  }

  function providerRank(provider) {
    if (provider === "claude") return 0;
    if (provider === "codex" || provider === "openai") return 1;
    return 9;
  }

  function isObservedLimit(limit) {
    return limit.official === true && limit.confidence === "observed" && limit.status === "ok";
  }

  function isExpiredLimit(limit) {
    if (!limit.reset_at) return false;
    const reset = Date.parse(limit.reset_at);
    return Number.isFinite(reset) && reset <= Date.now();
  }

  function windowRank(value) {
    const raw = String(value || "").toLowerCase();
    if (raw === "session" || raw === "5h") return 1;
    if (raw === "week" || raw === "weekly" || raw === "7d") return 2;
    return 9;
  }

  function remainingText(limit) {
    if (!limit.reset_at) return "等待刷新";
    const reset = Date.parse(limit.reset_at);
    if (!Number.isFinite(reset)) return formatDateTime(limit.reset_at);
    const minutes = Math.max(0, Math.round((reset - Date.now()) / 60000));
    if (minutes >= 1440) return `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`;
    if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}min`;
    return `${minutes}min`;
  }

  function renderSourceCards(hosts, sources) {
    el.sourceCards.replaceChildren();
    const cards = mergeSourceCards(hosts, sources);
    if (!cards.length) {
      const empty = document.createElement("div");
      empty.className = "source-card";
      empty.textContent = "暂无来源数据";
      el.sourceCards.appendChild(empty);
      return;
    }
    cards.forEach((host) => {
      const hasUserTarget = host.users && host.users[0];
      const card = document.createElement(hasUserTarget ? "button" : "div");
      if (hasUserTarget) card.type = "button";
      card.className = `source-card${host.statusOnly ? " source-card--status" : ""}`;
      card.title = `${host.displayName}: ${fmt(host.tokens)}`;
      if (hasUserTarget) {
        card.addEventListener("click", () => {
          const user = host.users && host.users[0];
          if (user) selectUser(user.machine, user.account);
        });
      }
      const dot = document.createElement("span");
      dot.className = "source-dot";
      dot.style.background = host.color;
      const copy = document.createElement("div");
      copy.className = "source-copy";
      const name = document.createElement("strong");
      name.textContent = host.displayName || host.name;
      const meta = document.createElement("span");
      meta.textContent = host.kind;
      copy.append(name, meta);
      const value = document.createElement("span");
      value.className = "source-value";
      value.textContent = host.statusOnly ? statusLabel(host.status) : fmt(host.tokens);
      card.append(dot, copy, value);
      el.sourceCards.appendChild(card);
    });
  }

  function mergeSourceCards(hosts, sources) {
    const usageCards = (hosts || []).map((host) => ({
      ...host,
      status: "ok",
      statusOnly: false,
      key: sourceKey(host.name, host.account),
    }));
    const seen = new Set(usageCards.map((host) => host.key));
    const statusCards = sortSourcesForDisplay(sources)
      .filter((source) => source.status !== "ok")
      .filter((source) => !seen.has(sourceKey(source.machine || source.host || source.source_id, source.os_user || source.account)))
      .map((source) => ({
        name: source.source_id || source.machine || source.host || "unknown",
        account: source.os_user || source.account || "",
        displayName: formatSourceIdentity(source),
        users: [],
        kind: [
          statusLabel(source.status),
          formatDateTime(source.observed_at || source.last_observed_at || source.last_pushed_at),
        ].filter(Boolean).join(" · "),
        tokens: 0,
        share: 0,
        color: statusColor(source.status),
        status: source.status,
        statusOnly: true,
        key: sourceKey(source.machine || source.host || source.source_id, source.os_user || source.account),
      }));
    const maxCards = 4;
    const statusBudget = Math.min(2, statusCards.length, maxCards);
    return statusCards.slice(0, statusBudget).concat(usageCards).slice(0, maxCards);
  }

  function sourceKey(machine, account) {
    return `${String(machine || "").toLowerCase()}|${String(account || "").toLowerCase()}`;
  }

  function renderBreakdown(target, rows, total) {
    if (!target) return;
    target.replaceChildren();
    rows.forEach((row) => {
      const node = document.createElement("div");
      node.textContent = `${row.displayName || row.name} ${fmt(row.tokens)} ${total ? Math.round(row.share * 100) : 0}%`;
      target.appendChild(node);
    });
  }

  function renderSources(sources) {
    if (!el.healthGrid) return;
    el.healthGrid.replaceChildren();
    const sorted = sortSourcesForDisplay(sources);
    const online = sorted.filter((source) => source.status === "ok").length;
    if (el.onlineCount) el.onlineCount.textContent = `${online}/${sorted.length} 在线`;
    sorted.forEach((source) => {
      const row = document.createElement("div");
      row.textContent = `${formatSourceIdentity(source)} · ${statusLabel(source.status)}`;
      el.healthGrid.appendChild(row);
    });
  }

  function sortSourcesForDisplay(sources) {
    return (sources || []).slice().sort((a, b) => {
      const rankDiff = statusRank(a.status) - statusRank(b.status);
      if (rankDiff) return rankDiff;
      const timeDiff = Date.parse(b.observed_at || b.last_observed_at || 0) - Date.parse(a.observed_at || a.last_observed_at || 0);
      if (timeDiff) return timeDiff;
      return formatSourceIdentity(a).localeCompare(formatSourceIdentity(b));
    });
  }

  function statusRank(status) {
    if (status === "ok") return 0;
    if (status === "stale") return 1;
    if (status === "command_failed") return 2;
    if (status === "never_seen") return 3;
    return 4;
  }

  function formatSourceIdentity(source) {
    const host = source.host || source.machine || source.source_id || "unknown-host";
    const account = source.os_user || source.account || "unknown";
    return `${account}@${host}`;
  }

  function statusLabel(status) {
    if (status === "ok") return "在线";
    if (status === "stale") return "静默";
    if (status === "command_failed") return "失败";
    if (status === "never_seen") return "未上报";
    return "静默";
  }

  function statusColor(status) {
    if (status === "ok") return "#34c759";
    if (status === "stale") return "#ff9f0a";
    if (status === "command_failed") return "#ff3b30";
    if (status === "never_seen") return "#8e8e93";
    return "#ff9f0a";
  }

  function renderScope(summary) {
    const machine = summary.machine || activeFilter.machine;
    const account = summary.account || activeFilter.account;
    const isFiltered = Boolean(machine || account);
    if (el.clearUserFilter) el.clearUserFilter.hidden = !isFiltered;
  }

  function updateSyncChip(value) {
    el.syncChip.textContent = value ? formatTime(value) : "--";
  }

  function maxIso(left, right) {
    if (!left) return right || "";
    if (!right) return left || "";
    return Date.parse(right) > Date.parse(left) ? right : left;
  }

  function formatTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatDateTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function niceChartTicks(maxValue) {
    const top = niceCeil(maxValue);
    return [
      { value: top },
      { value: Math.ceil(top / 2) },
      { value: 0 },
    ];
  }

  function niceCeil(value) {
    const raw = Math.max(1, Number(value || 0));
    const exponent = Math.floor(Math.log10(raw));
    const base = Math.pow(10, exponent);
    const scaled = raw / base;
    const step = scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
    return Math.ceil(step * base);
  }

  function formatAxisTick(value) {
    const rounded = Math.ceil(Number(value || 0));
    if (rounded >= 1e9) return `${trimFixed(rounded / 1e9, 1)}B`;
    if (rounded >= 1e6) return `${Math.round(rounded / 1e6)}M`;
    if (rounded >= 1e3) return `${Math.round(rounded / 1e3)}k`;
    return String(rounded);
  }

  function readFilterFromLocation() {
    const params = new URLSearchParams(window.location.search);
    return {
      machine: params.get("machine") || "",
      account: params.get("account") || "",
    };
  }

  function selectUser(machine, account) {
    if (!machine && !account) return;
    activeFilter = { machine: machine || "", account: account || "" };
    countFrom = 0;
    writeFilterToLocation();
    loadSummary().catch(showLoadError);
  }

  function clearUserFilter() {
    activeFilter = { machine: "", account: "" };
    countFrom = 0;
    writeFilterToLocation();
    loadSummary().catch(showLoadError);
  }

  function writeFilterToLocation() {
    const params = new URLSearchParams(window.location.search);
    if (activeFilter.machine) params.set("machine", activeFilter.machine);
    else params.delete("machine");
    if (activeFilter.account) params.set("account", activeFilter.account);
    else params.delete("account");
    const query = params.toString();
    window.history.pushState({ filter: activeFilter }, "", query ? `?${query}` : window.location.pathname);
  }

  function showLoadError(error) {
    if (el.errorCard) el.errorCard.hidden = false;
    if (el.errorMsg) el.errorMsg.textContent = sanitizeErrorMessage(error.message);
  }

  function sanitizeErrorMessage(message) {
    return String(message || "")
      .replace(/\/Users\/[a-zA-Z0-9_.-]+\//g, "/Users/<user>/")
      .replace(/\/home\/[a-zA-Z0-9_.-]+\//g, "/home/<user>/")
      .replace(/token[a-zA-Z0-9_.\s-]*?[:=\s]\s*[a-zA-Z0-9_.-]+/gi, "token=***")
      .replace(/bearer\s+[a-zA-Z0-9_.-]+/gi, "bearer ***");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function svg(name, attrs, text) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      node.setAttribute(key, String(value));
    });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  el.periodSelector.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-period]");
    if (!button) return;
    periodId = button.dataset.period;
    el.periodSelector.querySelectorAll("button").forEach((node) => {
      node.setAttribute("aria-selected", String(node === button));
    });
    loadSummary().catch(showLoadError);
  });

  el.themeToggle.addEventListener("click", () => {
    document.body.toggleAttribute("data-dark");
    document.body.toggleAttribute("data-force-light", !document.body.hasAttribute("data-dark"));
    el.themeToggle.textContent = document.body.hasAttribute("data-dark") ? "☀" : "☾";
  });

  if (el.clearUserFilter) el.clearUserFilter.addEventListener("click", clearUserFilter);
  window.addEventListener("popstate", () => {
    activeFilter = readFilterFromLocation();
    countFrom = 0;
    loadSummary().catch(showLoadError);
  });

  loadSummary().catch(showLoadError);
})();

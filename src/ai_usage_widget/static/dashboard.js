(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PERIODS = [
    { id: "today", label: "今天", axis: ["00:00", "08:00", "16:00", "now"], buckets: 24 },
    { id: "week", label: "本周", axis: ["Mon", "Wed", "Fri", "Sun"], buckets: 7 },
    { id: "month", label: "本月", axis: ["06-01", "06-10", "06-20", "now"], buckets: 30 },
    { id: "all", label: "全部", axis: ["Jan", "Apr", "Jul", "Oct"], buckets: 12 },
  ];
  const AGENT_COLORS = {
    claude: "#E08855",
    codex: "#2A6FDB",
    gemini: "#18B59E",
    deepseek: "#9558D9",
    unknown: "#5FA8F5",
  };
  const TOKEN_TYPE_COLORS = {
    input: "#7FB0FF",
    output: "#B89BFF",
    cache: "#5FE0D0",
  };
  const HOST_COLORS = ["#E08855", "#2A6FDB", "#18B59E", "#9558D9", "#5FA8F5", "#5FE0B5"];

  let periodId = "today";
  let latestSnapshot = null;
  let activeFilter = readFilterFromLocation();
  let countFrom = 0;
  let countRaf = 0;

  const el = {
    scopeLabel: document.getElementById("scopeLabel"),
    clearUserFilter: document.getElementById("clearUserFilter"),
    periodSelector: document.getElementById("periodSelector"),
    syncChip: document.getElementById("syncChip"),
    periodEyebrow: document.getElementById("periodEyebrow"),
    totalTokens: document.getElementById("totalTokens"),
    inputTokens: document.getElementById("inputTokens"),
    outputTokens: document.getElementById("outputTokens"),
    cacheTokensCompact: document.getElementById("cacheTokensCompact"),
    cacheHitLabel: document.getElementById("cacheHitLabel"),
    streamChart: document.getElementById("streamChart"),
    streamTooltip: document.getElementById("streamTooltip"),
    axisRow: document.getElementById("axisRow"),
    emptyState: document.getElementById("emptyState"),
    dashboardContent: document.getElementById("dashboardContent"),
    byAgentList: document.getElementById("byAgentList"),
    modelList: document.getElementById("modelList"),
    cacheReadTokensVal: document.getElementById("cacheReadTokensVal"),
    cacheReadProgress: document.getElementById("cacheReadProgress"),
    machineCount: document.getElementById("machineCount"),
    hostDonut: document.getElementById("hostDonut"),
    hostTooltip: document.getElementById("hostTooltip"),
    hostLegend: document.getElementById("hostLegend"),
    onlineCount: document.getElementById("onlineCount"),
    healthGrid: document.getElementById("healthGrid"),
    errorCard: document.getElementById("errorCard"),
    errorMsg: document.getElementById("errorMsg"),
  };
  if (el.streamTooltip && el.streamTooltip.parentElement !== document.body) {
    document.body.appendChild(el.streamTooltip);
  }
  if (el.hostTooltip && el.hostTooltip.parentElement !== document.body) {
    document.body.appendChild(el.hostTooltip);
  }

  function fmt(n) {
    const value = Number(n || 0);
    if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(value >= 1e7 ? 1 : 2)}M`;
    if (value >= 1e3) return `${(value / 1e3).toFixed(value >= 1e5 ? 0 : 1)}k`;
    return String(Math.round(value));
  }

  function fmtFull(n) {
    return Math.round(Number(n || 0)).toLocaleString("en-US");
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

  function agentKey(name) {
    const raw = String(name || "").toLowerCase();
    if (raw.includes("claude")) return "claude";
    if (raw.includes("codex") || raw.includes("openai") || raw.includes("gpt")) return "codex";
    if (raw.includes("gemini")) return "gemini";
    if (raw.includes("deepseek")) return "deepseek";
    return "unknown";
  }

  function colorForAgent(name) {
    return AGENT_COLORS[agentKey(name)] || AGENT_COLORS.unknown;
  }

  function withAlpha(hex, alpha) {
    const h = hex.replace("#", "");
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
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

    const agents = normalizeGroups(snapshot.groups && snapshot.groups.by_agent, total, "agent");
    const hosts = normalizeGroups(snapshot.groups && snapshot.groups.by_machine, total, "host");
    const models = collectModels(snapshot.items || [], total);
    const trend = normalizeTrend(snapshot.trend, period);
    const layers = trend.layers;

    return { period: { ...period, axis: trend.axis }, total, input, output, cache, cachePct, agents, hosts, models, layers, trendPoints: trend.points };
  }

  function normalizeGroups(groups, total, type) {
    return (groups || []).map((item, index) => {
      const name = item.name || item.source_id || "unknown";
      const account = item.account || "";
      const displayName = item.display_name || (account ? `${name} · ${account}` : name);
      const users = normalizeMachineUsers(item.users || [], name, total);
      const tokens = Number(item.total_tokens || 0);
      return {
        name,
        account,
        displayName,
        users,
        short: type === "agent" ? displayAgent(name) : displayName,
        kind: type === "host" ? hostKind(name, account) : "",
        tokens,
        share: total > 0 ? tokens / total : 0,
        color: type === "agent" ? colorForAgent(name) : HOST_COLORS[index % HOST_COLORS.length],
      };
    }).filter((item) => item.tokens > 0);
  }

  function displayAgent(name) {
    const key = agentKey(name);
    if (key === "claude") return "Claude";
    if (key === "codex") return "Codex";
    if (key === "gemini") return "Gemini";
    if (key === "deepseek") return "DeepSeek";
    return name;
  }

  function hostKind(name, account) {
    const raw = String(name || "").toLowerCase();
    const suffix = account ? ` · ${account}` : "";
    if (raw.includes("mac")) return "Mac · 本地";
    if (raw.includes("ubuntu")) return `Linux · CI${suffix}`;
    if (raw.includes("wang")) return `Linux · Dev${suffix}`;
    if (raw.includes("gpu")) return `Linux · GPU${suffix}`;
    return account ? `Source · ${account}` : "Source";
  }

  function collectModels(items, total) {
    const map = new Map();
    items.forEach((item) => {
      (item.model_breakdowns || []).forEach((model) => {
        const name = model.model_name || "unknown-model";
        const key = `${name}::${item.agent || "unknown"}`;
        const prev = map.get(key) || {
          name,
          agent: item.agent || "unknown",
          tokens: 0,
          cacheRead: 0,
          color: colorForAgent(item.agent),
        };
        prev.tokens += Number(model.total_tokens || 0);
        prev.cacheRead += Number(model.cache_read_tokens || 0);
        map.set(key, prev);
      });
    });
    return Array.from(map.values())
      .sort((a, b) => b.tokens - a.tokens)
      .map((item) => ({
        ...item,
        share: total > 0 ? item.tokens / total : 0,
        cachePctText: item.tokens > 0 ? `${Math.round((item.cacheRead / item.tokens) * 100)}%` : "0%",
      }));
  }

  function normalizeTrend(trend, period) {
    if (trend && Array.isArray(trend.axis) && Array.isArray(trend.by_token_type)) {
      const axis = trend.axis.map((value) => shortDateLabel(value, trend.granularity));
      const layers = trend.by_token_type.map((row) => ({
        key: row.type,
        label: row.label || row.type,
        color: TOKEN_TYPE_COLORS[row.type] || "#5FA8F5",
        values: (row.values || []).map((value) => Math.max(0.0001, Number(value || 0))),
      }));
      return {
        axis,
        points: Array.isArray(trend.points) ? trend.points : [],
        layers: layers.length ? layers : emptyLayers(axis.length || 1),
      };
    }
    return { axis: period.axis, points: [], layers: emptyLayers(period.buckets) };
  }

  function emptyLayers(buckets) {
    return [{ key: "empty", color: "#5FA8F5", values: Array.from({ length: buckets }, () => 0.0001) }];
  }

  function shortDateLabel(value, granularity) {
    const text = String(value || "");
    if (granularity === "hour" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) return text.slice(11, 16);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text.slice(5);
    return text;
  }

  function render() {
    if (!latestSnapshot) return;
    const data = buildData(latestSnapshot);
    const hasUsage = data.total > 0;
    renderScope(latestSnapshot.summary || {});

    el.periodEyebrow.textContent = `${data.period.label}总消耗 · TOKENS`;
    animateTotal(data.total);
    el.inputTokens.textContent = fmt(data.input);
    el.outputTokens.textContent = fmt(data.output);
    el.cacheTokensCompact.textContent = fmt(data.cache);
    el.cacheHitLabel.textContent = `Cache Hit ${Math.round(data.cachePct * 100)}%`;
    if (el.cacheReadTokensVal) el.cacheReadTokensVal.textContent = `${fmt(data.cache)} · ${Math.round(data.cachePct * 100)}%`;
    if (el.cacheReadProgress) el.cacheReadProgress.style.width = `${Math.max(0, Math.min(100, data.cachePct * 100))}%`;
    updateSyncChip(latestSnapshot.generated_at);

    el.emptyState.hidden = hasUsage;
    el.dashboardContent.hidden = false;

    renderBreakdown(el.byAgentList, data.agents, data.total);
    renderBreakdown(el.modelList, normalizeModelShares(data.models), data.total, true);
    renderStream(data.layers, data.period.axis, data.trendPoints);
    renderDonut(data.hosts);
    renderSources(latestSnapshot.source_status || []);
  }

  function animateTotal(target) {
    const from = countFrom;
    const start = performance.now();
    cancelAnimationFrame(countRaf);
    function tick(now) {
      const t = Math.min(1, (now - start) / 650);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = from + (target - from) * eased;
      el.totalTokens.textContent = fmtHero(current);
      if (t < 1) {
        countRaf = requestAnimationFrame(tick);
      } else {
        countFrom = target;
      }
    }
    countRaf = requestAnimationFrame(tick);
  }

  function normalizeModelShares(models) {
    const maxShare = Math.max(...models.map((m) => m.share), 0);
    return models.map((model) => ({ ...model, share: maxShare > 0 ? model.share / maxShare : 0 }));
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

  function renderScope(summary) {
    const machine = summary.machine || activeFilter.machine;
    const account = summary.account || activeFilter.account;
    const isFiltered = Boolean(machine || account);
    if (el.scopeLabel) {
      el.scopeLabel.textContent = isFiltered
        ? `${machine || "全部机器"} · ${account || "全部用户"} 的 AI coding 用量与健康状态`
        : "多设备 · 多 OS · AI coding 用量与健康状态统一观测";
    }
    if (el.clearUserFilter) el.clearUserFilter.hidden = !isFiltered;
  }

  function renderBreakdown(target, rows, total, compactModels) {
    target.replaceChildren();
    if (!rows.length) {
      target.appendChild(emptyLine(compactModels ? "暂无模型明细" : "暂无用量明细"));
      return;
    }
    rows.forEach((row) => {
      const item = document.createElement("div");
      item.className = "breakdown-row";
      item.style.color = row.color;

      const name = document.createElement("div");
      name.className = "breakdown-name";
      const dot = document.createElement("span");
      dot.className = "dot";
      const strong = document.createElement("strong");
      strong.textContent = row.short || row.name;
      name.append(dot, strong);

      const track = document.createElement("div");
      track.className = "bar-track";
      const fill = document.createElement("i");
      fill.style.background = `linear-gradient(90deg, ${withAlpha(row.color, 0.9)}, ${row.color})`;
      fill.style.width = `${Math.max(2, Math.min(100, row.share * 100))}%`;
      track.appendChild(fill);

      const value = document.createElement("span");
      value.className = "breakdown-value";
      if (row.cachePctText) {
        const main = document.createElement("span");
        main.textContent = fmt(row.tokens);
        const cachePct = document.createElement("span");
        cachePct.className = "cache-pct";
        cachePct.textContent = row.cachePctText;
        cachePct.title = `Cache Read ${row.cachePctText}`;
        value.append(main, cachePct);
      } else {
        value.classList.add("single-value");
        value.textContent = fmt(row.tokens);
      }
      value.title = total ? `${Math.round((row.tokens / total) * 100)}%` : "0%";

      item.append(name, track, value);
      target.appendChild(item);
    });
  }

  function emptyLine(text) {
    const node = document.createElement("div");
    node.className = "source-row";
    const copy = document.createElement("div");
    copy.className = "source-copy";
    const span = document.createElement("span");
    span.textContent = text;
    copy.appendChild(span);
    node.appendChild(copy);
    return node;
  }

  function smoothLine(points, tension) {
    if (points.length < 2) return "";
    let d = `M ${points[0][0]},${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1[0] + ((p2[0] - p0[0]) / 6) * tension * 2;
      const c1y = p1[1] + ((p2[1] - p0[1]) / 6) * tension * 2;
      const c2x = p2[0] - ((p3[0] - p1[0]) / 6) * tension * 2;
      const c2y = p2[1] - ((p3[1] - p1[1]) / 6) * tension * 2;
      d += ` C ${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
    }
    return d;
  }

  function straightLine(points) {
    if (!points.length) return "";
    return `M ${points.map((p) => `${p[0]},${p[1]}`).join(" L ")}`;
  }

  function renderStream(layers, axis, points) {
    const rect = el.streamChart.getBoundingClientRect();
    const width = Math.max(420, Math.round(rect.width || 420));
    const height = 112;
    const gutterLeft = 44;
    const gutterBottom = 18;
    const plotTop = 4;
    const plotWidth = width - gutterLeft;
    const plotHeight = height - gutterBottom - plotTop;
    const n = layers[0] ? layers[0].values.length : 1;
    const totals = Array.from({ length: n }, (_, i) => layers.reduce((sum, layer) => sum + layer.values[i], 0));
    const max = Math.max(...totals, 0.001) * 1.08;
    const xAt = (i) => gutterLeft + (n === 1 ? plotWidth / 2 : (i / (n - 1)) * plotWidth);
    const yAt = (v) => plotTop + plotHeight - (v / max) * plotHeight;
    const cum = Array.from({ length: n }, () => 0);

    el.streamChart.replaceChildren();
    el.streamChart.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const defs = svg("defs");
    const yTicks = [
      { label: fmt(max), value: max },
      { label: fmt(max / 2), value: max / 2 },
      { label: "0", value: 0 },
    ];
    const grid = svg("g", { class: "stream-grid" });
    yTicks.forEach((tick) => {
      const y = yAt(tick.value);
      grid.append(
        svg("line", { x1: gutterLeft, y1: y, x2: width, y2: y, stroke: "rgba(255,255,255,0.055)", "stroke-width": 1 }),
        svg("text", { x: gutterLeft - 8, y: y + 3, "text-anchor": "end", fill: "rgba(244,244,246,0.34)", "font-size": 9.2, "font-family": "ui-monospace, Menlo, Monaco, Consolas, monospace", "font-stretch": "normal" }, tick.label)
      );
    });
    const base = svg("line", { x1: gutterLeft, y1: yAt(0), x2: width, y2: yAt(0), stroke: "rgba(255,255,255,0.05)", "stroke-width": 1 });
    el.streamChart.append(defs, grid, base);

    layers.forEach((layer, index) => {
      const gradientId = `stream-${index}-${periodId}`;
      const gradient = svg("linearGradient", { id: gradientId, x1: "0", y1: "0", x2: "0", y2: "1" });
      gradient.append(
        svg("stop", { offset: "0%", "stop-color": withAlpha(layer.color, 0.62) }),
        svg("stop", { offset: "100%", "stop-color": withAlpha(layer.color, 0.14) })
      );
      defs.appendChild(gradient);

      const lower = cum.map((c) => c);
      const upper = cum.map((c, i) => c + layer.values[i]);
      for (let i = 0; i < n; i += 1) cum[i] = upper[i];

      const topPoints = upper.map((v, i) => [xAt(i), yAt(v)]);
      const bottomPoints = lower.map((v, i) => [xAt(i), yAt(v)]).reverse();
      const fillPath = `${straightLine(topPoints)} L ${bottomPoints.map((p) => `${p[0]},${p[1]}`).join(" L ")} Z`;
      const linePath = straightLine(topPoints);

      const group = svg("g", { class: "stream-band" });
      group.style.animationDelay = `${index * 0.06}s`;
      group.append(
        svg("path", { d: fillPath, fill: `url(#${gradientId})` }),
        svg("path", { d: linePath, fill: "none", stroke: withAlpha(layer.color, 0.95), "stroke-width": 1.6, "stroke-linejoin": "round", "stroke-linecap": "round" })
      );
      el.streamChart.appendChild(group);
    });

    const hover = svg("g", { class: "stream-hover" });
    const hoverLine = svg("line", { x1: gutterLeft, y1: plotTop, x2: gutterLeft, y2: plotTop + plotHeight, stroke: "rgba(255,255,255,0.36)", "stroke-width": 1, visibility: "hidden" });
    const hoverDot = svg("circle", { cx: gutterLeft, cy: yAt(0), r: 3.2, fill: "#F4F4F6", stroke: "rgba(0,0,0,0.45)", "stroke-width": 1, visibility: "hidden" });
    hover.append(hoverLine, hoverDot);
    el.streamChart.appendChild(hover);

    el.streamChart.onmousemove = (event) => {
      if (!n) return;
      const rect = el.streamChart.getBoundingClientRect();
      const svgX = ((event.clientX - rect.left) / rect.width) * width;
      const clamped = Math.max(gutterLeft, Math.min(width, svgX));
      const ratio = plotWidth <= 0 ? 0 : (clamped - gutterLeft) / plotWidth;
      const index = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
      const x = xAt(index);
      const total = totals[index] || 0;
      hoverLine.setAttribute("x1", String(clamped));
      hoverLine.setAttribute("x2", String(clamped));
      hoverLine.setAttribute("visibility", "visible");
      hoverDot.setAttribute("cx", String(x));
      hoverDot.setAttribute("cy", String(yAt(total)));
      hoverDot.setAttribute("visibility", "visible");
      showStreamTooltip(index, event, points, layers, totals);
    };
    el.streamChart.onmouseleave = () => {
      hoverLine.setAttribute("visibility", "hidden");
      hoverDot.setAttribute("visibility", "hidden");
      el.streamTooltip.hidden = true;
    };

    el.axisRow.replaceChildren();
    el.axisRow.style.paddingLeft = `${(gutterLeft / width) * 100}%`;
    const visibleLabels = visibleAxisLabels(axis, plotWidth);
    axis.forEach((label, index) => {
      const node = document.createElement("span");
      node.textContent = label;
      node.style.visibility = visibleLabels.has(index) ? "visible" : "hidden";
      el.axisRow.appendChild(node);
    });
  }

  function visibleAxisLabels(axis, plotWidth) {
    const length = axis.length;
    const visible = new Set();
    if (!length) return visible;
    if (length === 1) return visible.add(0);
    const minGap = Math.max(52, Math.min(86, longestAxisLabel(axis) * 7 + 18));
    const xAt = (index) => (index / (length - 1)) * plotWidth;
    const lastIndex = length - 1;
    visible.add(lastIndex);

    let lastVisibleX = -Infinity;
    for (let index = 0; index < lastIndex; index += 1) {
      const x = xAt(index);
      const enoughFromPrevious = x - lastVisibleX >= minGap;
      const enoughFromLast = xAt(lastIndex) - x >= minGap;
      if (enoughFromPrevious && enoughFromLast) {
        visible.add(index);
        lastVisibleX = x;
      }
    }
    return visible;
  }

  function longestAxisLabel(axis) {
    return axis.reduce((max, label) => Math.max(max, String(label || "").length), 0);
  }

  function showStreamTooltip(index, event, points, layers, totals) {
    const point = points[index] || {};
    const layerValues = Object.fromEntries(layers.map((layer) => [layer.key, layer.values[index] || 0]));
    el.streamTooltip.innerHTML = `
      <strong>${escapeHtml(formatPointLabel(point.date || point.hour || "当前点"))}</strong>
      <span>Total <b>${fmt(totals[index] || point.total_tokens || 0)}</b></span>
      <span>Input <b>${fmt(point.input_tokens ?? layerValues.input ?? 0)}</b></span>
      <span>Output <b>${fmt(point.output_tokens ?? layerValues.output ?? 0)}</b></span>
      <span>Cache <b>${fmt(point.cache_tokens ?? layerValues.cache ?? 0)}</b></span>
    `;
    el.streamTooltip.hidden = false;
    const tipRect = el.streamTooltip.getBoundingClientRect();
    const rightX = event.clientX + 14;
    const leftX = event.clientX - tipRect.width - 14;
    const belowY = event.clientY + 14;
    const aboveY = event.clientY - tipRect.height - 14;
    const x = rightX + tipRect.width <= window.innerWidth ? rightX : leftX;
    const y = belowY + tipRect.height <= window.innerHeight ? belowY : aboveY;
    el.streamTooltip.style.left = `${Math.max(10, Math.min(window.innerWidth - tipRect.width - 10, x))}px`;
    el.streamTooltip.style.top = `${Math.max(10, Math.min(window.innerHeight - tipRect.height - 10, y))}px`;
  }

  function renderDonut(hosts) {
    el.hostDonut.replaceChildren();
    el.hostLegend.replaceChildren();
    el.machineCount.textContent = `${hosts.length} machines`;

    const size = 150;
    const thickness = 30;
    const r = (size - thickness) / 2;
    const c = 2 * Math.PI * r;
    const cx = size / 2;
    const cy = size / 2;
    let acc = 0;
    const total = hosts.reduce((sum, h) => sum + h.tokens, 0) || 1;

    el.hostDonut.appendChild(svg("circle", { cx, cy, r, fill: "none", stroke: "rgba(255,255,255,0.07)", "stroke-width": thickness }));
    const group = svg("g", { transform: `rotate(-90 ${cx} ${cy})` });
    hosts.forEach((host, index) => {
      const frac = host.tokens / total;
      const overlap = hosts.length > 1 ? 1.2 : 0;
      const dash = Math.min(c, frac * c + overlap);
      const offset = -acc * c - overlap / 2;
      acc += frac;
      const circle = svg("circle", {
        class: "donut-segment",
        cx,
        cy,
        r,
        fill: "none",
        stroke: host.color,
        "stroke-width": thickness,
        "stroke-dasharray": `${dash} ${c - dash}`,
        "stroke-dashoffset": offset,
      });
      circle.addEventListener("mousemove", (event) => showHostTooltip(event, host, total));
      circle.addEventListener("mouseleave", () => {
        if (el.hostTooltip) el.hostTooltip.hidden = true;
      });
      circle.style.setProperty("--dash-full", `${dash} ${c - dash}`);
      circle.style.animationDelay = `${index * 0.08}s`;
      group.appendChild(circle);
    });
    el.hostDonut.appendChild(group);
    el.hostDonut.append(
      svg("text", { x: cx, y: cy - 2, "text-anchor": "middle", fill: "#F4F4F6", "font-size": 28, "font-family": "SF Mono, ui-monospace, Menlo, monospace", "font-weight": 700 }, String(hosts.length)),
      svg("text", { x: cx, y: cy + 21, "text-anchor": "middle", fill: "rgba(244,244,246,0.34)", "font-size": 12, "font-family": "SF Mono, ui-monospace, Menlo, monospace" }, "SOURCES")
    );

    if (!hosts.length) {
      el.hostLegend.appendChild(emptyLine("暂无设备用量"));
      return;
    }
    hosts.forEach((host) => {
      const row = document.createElement("div");
      row.className = "host-row";
      const dot = document.createElement("span");
      dot.className = "host-dot";
      dot.style.background = host.color;
      const name = document.createElement("strong");
      name.textContent = host.displayName || host.name;
      const kind = document.createElement("small");
      kind.textContent = host.kind;
      const pct = document.createElement("em");
      pct.textContent = `${Math.round(host.share * 100)}%`;
      row.title = `${host.displayName || host.name}: ${fmt(host.tokens)} · ${Math.round(host.share * 100)}%`;
      row.append(dot, name, kind, pct);
      el.hostLegend.appendChild(row);
      if (host.users && host.users.length) {
        const users = document.createElement("div");
        users.className = "machine-users";
        host.users.forEach((user) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "machine-user-button";
          button.dataset.machine = user.machine;
          button.dataset.account = user.account;
          button.title = `${user.displayName}: ${fmt(user.tokens)}`;
          const label = document.createElement("span");
          label.textContent = user.account;
          const value = document.createElement("em");
          value.textContent = fmt(user.tokens);
          button.append(label, value);
          button.addEventListener("click", () => selectUser(user.machine, user.account));
          users.appendChild(button);
        });
        el.hostLegend.appendChild(users);
      }
    });
  }

  function showHostTooltip(event, host, total) {
    if (!el.hostTooltip) return;
    const pct = total > 0 ? Math.round((host.tokens / total) * 100) : 0;
    el.hostTooltip.innerHTML = `
      <strong>${escapeHtml(host.displayName || host.name)}</strong>
      <span>Usage <b>${fmt(host.tokens)}</b></span>
      <span>Share <b>${pct}%</b></span>
      <span>Account <b>${escapeHtml(host.account || "-")}</b></span>
    `;
    el.hostTooltip.hidden = false;
    const width = 190;
    const height = 106;
    const left = Math.max(10, Math.min(window.innerWidth - width - 10, event.clientX + 14));
    const top = Math.max(10, Math.min(window.innerHeight - height - 10, event.clientY - height / 2));
    el.hostTooltip.style.left = `${left}px`;
    el.hostTooltip.style.top = `${top}px`;
    el.hostTooltip.hidden = false;
  }

  function renderSources(sources) {
    el.healthGrid.replaceChildren();
    const online = sources.filter((s) => s.status === "ok").length;
    el.onlineCount.textContent = `${online}/${sources.length} 在线`;

    if (!sources.length) {
      el.healthGrid.appendChild(emptyLine("未连接任何数据源"));
      el.errorCard.hidden = true;
      return;
    }

    const failed = [];
    sources.forEach((source) => {
      const isOnline = source.status === "ok";
      const row = document.createElement("div");
      row.className = "source-row";
      const dot = document.createElement("span");
      dot.className = `status-dot${isOnline ? " online" : ""}`;

      const copy = document.createElement("div");
      copy.className = "source-copy";
      const name = document.createElement("strong");
      name.textContent = source.display_name || source.source_id || "unknown-source";
      name.title = source.source_id || "";
      const meta = document.createElement("span");
      meta.textContent = `${sourceKind(source)} · 最后活动 ${formatTime(source.observed_at)}`;
      copy.append(name, meta);

      if (source.error_message) {
        const message = document.createElement("small");
        message.textContent = truncate(sanitizeErrorMessage(source.error_message), 80);
        copy.appendChild(message);
        failed.push(source);
      }

      const pill = document.createElement("span");
      pill.className = `status-pill${isOnline ? " online" : ""}`;
      pill.textContent = isOnline ? "在线" : statusLabel(source.status);
      row.append(dot, copy, pill);
      el.healthGrid.appendChild(row);
    });

    el.errorCard.hidden = failed.length === 0;
    el.errorMsg.textContent = failed
      .map((source) => `${source.source_id}: ${truncate(sanitizeErrorMessage(source.error_message), 150)}`)
      .join("\n");
  }

  function statusLabel(status) {
    if (status === "stale") return "静默";
    if (status === "command_failed") return "失败";
    if (status === "never_seen") return "未上报";
    return "静默";
  }

  function sourceKind(source) {
    const host = source.host || source.source_id;
    const account = source.os_user || source.account || "";
    const platform = String(source.platform || "").toLowerCase();
    if (platform === "macos" || platform === "mac") return account ? `Mac · ${account}` : "Mac";
    if (platform === "linux") return account ? `Linux · ${account}` : "Linux";
    return hostKind(host, account);
  }

  function updateSyncChip(value) {
    if (!value) {
      el.syncChip.lastChild.textContent = " --";
      return;
    }
    el.syncChip.lastChild.textContent = ` ${formatTime(value)}`;
  }

  function formatTime(value) {
    if (!value) return "从未上报";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatPointLabel(value) {
    const text = String(value || "");
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) return `${text.slice(5, 10)} ${text.slice(11, 16)}`;
    return text;
  }

  function sanitizeErrorMessage(message) {
    return String(message || "")
      .replace(/\/Users\/[a-zA-Z0-9_.-]+\//g, "/Users/<user>/")
      .replace(/\/home\/[a-zA-Z0-9_.-]+\//g, "/home/<user>/")
      .replace(/token[a-zA-Z0-9_.\s-]*?[:=\s]\s*[a-zA-Z0-9_.-]+/gi, "token=***")
      .replace(/bearer\s+[a-zA-Z0-9_.-]+/gi, "bearer ***");
  }

  function truncate(value, limit) {
    const text = String(value || "");
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function readFilterFromLocation() {
    const params = new URLSearchParams(window.location.search);
    return {
      machine: params.get("machine") || "",
      account: params.get("account") || "",
    };
  }

  function selectUser(machine, account) {
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
    el.errorCard.hidden = false;
    el.errorMsg.textContent = error.message;
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
    loadSummary().catch((error) => {
      showLoadError(error);
    });
  });

  if (el.clearUserFilter) el.clearUserFilter.addEventListener("click", clearUserFilter);
  window.addEventListener("popstate", () => {
    activeFilter = readFilterFromLocation();
    countFrom = 0;
    loadSummary().catch(showLoadError);
  });

  loadSummary().catch(showLoadError);
})();

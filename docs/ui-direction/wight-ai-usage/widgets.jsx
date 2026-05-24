/* global React */
const { useMemo, useState, useEffect } = React;

// ─────────────────────────────────────────────────────────────
// Agent palette · Codex = blue (per user request), Claude = amber
// ─────────────────────────────────────────────────────────────
const AGENT_COLORS = {
  claude:   '#E08855', // amber
  codex:    '#2A6FDB', // blue
  gemini:   '#18B59E', // teal
  deepseek: '#9558D9', // purple
};

// ─────────────────────────────────────────────────────────────
// Synced data snapshot (timestamps are absolute, mock)
// ─────────────────────────────────────────────────────────────
const NOW_LABEL = '12:34';              // last data sync clock
const NOW_DATE  = 'Mon · May 24';       // long-form sync (used on Large)

const AGENTS = [
  {
    id: 'claude', name: 'Claude Code', short: 'Claude',
    color: AGENT_COLORS.claude,
    w5h:  { used: 1_842_000, quota: 2_500_000, resetAt: '17:00',  resetAtLong: 'Today 17:00'  },
    week: { used: 8_400_000, quota:20_000_000, resetAt: 'Mon 00:00', resetAtDate: '06-01', resetAtLong: 'Mon · 06-01 00:00' },
    io: { input: { cached: 5_200_000, uncached: 1_420_000 }, output: 1_840_000 },
    hosts: [
      { id: 'mbp-m3',  label: 'mbp-m3',      kind: 'Mac · 本地',    share: 0.56 },
      { id: 'gpu-01',  label: 'gpu-01',      kind: 'Linux · Dev',   share: 0.38 },
      { id: 'runner',  label: 'runner-pool', kind: 'GitHub Actions',share: 0.06 },
    ],
  },
  {
    id: 'codex', name: 'Codex CLI', short: 'Codex',
    color: AGENT_COLORS.codex,
    w5h:  { used:   312_000, quota: 1_500_000, resetAt: '15:42',   resetAtLong: 'Today 15:42'   },
    week: { used: 2_100_000, quota: 8_000_000, resetAt: 'Mon 00:00', resetAtDate: '06-01', resetAtLong: 'Mon · 06-01 00:00' },
    io: { input: { cached: 980_000, uncached: 420_000 }, output: 320_000 },
    hosts: [
      { id: 'mbp-m3',  label: 'mbp-m3',  kind: 'Mac · 本地',  share: 0.72 },
      { id: 'tk-edge', label: 'tk-edge', kind: 'VPS · Tokyo', share: 0.28 },
    ],
  },
  {
    id: 'gemini', name: 'Gemini CLI', short: 'Gemini',
    color: AGENT_COLORS.gemini,
    w5h:  { used: 920_000, quota: 2_000_000, resetAt: '16:20' },
    week: { used: 4_200_000, quota: 12_000_000, resetAt: 'Mon 00:00', resetAtDate: '06-01' },
    io: { input: { cached: 2_400_000, uncached: 580_000 }, output: 920_000 },
    hosts: [
      { id: 'mbp-m3', label: 'mbp-m3',      kind: 'Mac · 本地',     share: 0.64 },
      { id: 'runner', label: 'runner-pool', kind: 'GitHub Actions', share: 0.24 },
      { id: 'gpu-01', label: 'gpu-01',      kind: 'Linux · Dev',    share: 0.12 },
    ],
  },
  {
    id: 'deepseek', name: 'DeepSeek', short: 'DeepSeek',
    color: AGENT_COLORS.deepseek,
    w5h:  { used: 180_000, quota: 1_000_000, resetAt: '19:14' },
    week: { used: 1_400_000, quota: 6_000_000, resetAt: 'Mon 00:00', resetAtDate: '06-01' },
    io: { input: { cached: 600_000, uncached: 240_000 }, output: 180_000 },
    hosts: [
      { id: 'gpu-01', label: 'gpu-01', kind: 'Linux · Dev', share: 0.88 },
      { id: 'mbp-m3', label: 'mbp-m3', kind: 'Mac · 本地',   share: 0.12 },
    ],
  },
];

// Small widget only has room for 2 — keep the heaviest users
const PRIMARY_AGENTS = AGENTS.slice(0, 2);

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
const fmt = (n) => {
  if (n >= 1e6) return (n/1e6).toFixed(n >= 1e7 ? 0 : 2) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(n >= 1e5 ? 0 : 1) + 'k';
  return String(n);
};
const pct = (n) => Math.round(n * 100);

// ─────────────────────────────────────────────────────────────
// Time-series mocks
// ─────────────────────────────────────────────────────────────
function makeCurve(buckets, base, vary, seed) {
  const arr = []; let s = seed;
  for (let i = 0; i < buckets; i++) {
    s = (s * 9301 + 49297) % 233280;
    const r = s / 233280;
    arr.push(Math.max(0.05, base + (r - 0.5) * vary + Math.sin(i * 0.7) * vary * 0.4));
  }
  return arr;
}

const PERIODS = [
  { id: '60m', label: '60m', buckets: 12, axis: ['-60m','-30m','now'] },
  { id: '1d',  label: '1d',  buckets: 24, axis: ['00:00','12:00','now'] },
  { id: '7d',  label: '7d',  buckets:  7, axis: ['Mon','Thu','Sun'] },
  { id: '30d', label: '30d', buckets: 30, axis: ['-30d','-15d','now'] },
];

// Per-host palette (distinct from agent palette so host pies read clearly)
const HOST_COLORS = {
  'mbp-m3':      '#F5A85F', // warm   · Mac · local
  'gpu-01':      '#5FA8F5', // cool   · Linux · Dev
  'tk-edge':     '#5FE0B5', // teal   · VPS · Tokyo
  'runner-pool': '#A89BFF', // lavender · GitHub Actions
};

// Aggregated host distribution per selected period (mock)
const HOSTS_BY_PERIOD = {
  '60m': [
    { label: 'mbp-m3',      kind: 'Mac · 本地',     share: 0.82 },
    { label: 'gpu-01',      kind: 'Linux · Dev',    share: 0.14 },
    { label: 'runner-pool', kind: 'GitHub Actions', share: 0.04 },
  ],
  '1d': [
    { label: 'mbp-m3',      kind: 'Mac · 本地',     share: 0.58 },
    { label: 'gpu-01',      kind: 'Linux · Dev',    share: 0.24 },
    { label: 'tk-edge',     kind: 'VPS · Tokyo',    share: 0.11 },
    { label: 'runner-pool', kind: 'GitHub Actions', share: 0.07 },
  ],
  '7d': [
    { label: 'gpu-01',      kind: 'Linux · Dev',    share: 0.38 },
    { label: 'mbp-m3',      kind: 'Mac · 本地',     share: 0.34 },
    { label: 'runner-pool', kind: 'GitHub Actions', share: 0.18 },
    { label: 'tk-edge',     kind: 'VPS · Tokyo',    share: 0.10 },
  ],
  '30d': [
    { label: 'gpu-01',      kind: 'Linux · Dev',    share: 0.42 },
    { label: 'runner-pool', kind: 'GitHub Actions', share: 0.28 },
    { label: 'mbp-m3',      kind: 'Mac · 本地',     share: 0.22 },
    { label: 'tk-edge',     kind: 'VPS · Tokyo',    share: 0.08 },
  ],
};

function seriesFor(periodId) {
  const p = PERIODS.find(x => x.id === periodId);
  return {
    period: p,
    cached:   makeCurve(p.buckets, 0.55, 0.35, 11 + p.buckets),
    uncached: makeCurve(p.buckets, 0.22, 0.20, 47 + p.buckets),
    output:   makeCurve(p.buckets, 0.18, 0.16, 83 + p.buckets),
  };
}

// Per-agent series, stacked by provider (Claude / Codex / Gemini / DeepSeek)
function seriesByAgent(periodId) {
  const p = PERIODS.find(x => x.id === periodId);
  const seedFor = (id) => id.split('').reduce((s, c) => (s * 31 + c.charCodeAt(0)) % 9973, 17);
  // weight each agent so Claude dominates and DeepSeek is smallest — reflects PRIMARY data
  const weights = { claude: 1.0, codex: 0.45, gemini: 0.55, deepseek: 0.22 };
  return {
    period: p,
    layers: AGENTS.map(a => ({
      id: a.id,
      color: a.color,
      values: makeCurve(p.buckets, 0.35 * weights[a.id], 0.25 * weights[a.id], seedFor(a.id) + p.buckets * 13),
    })),
  };
}

// ─────────────────────────────────────────────────────────────
// Theme · Apple's 4 widget states
// ─────────────────────────────────────────────────────────────
function makeTheme(mode, state) {
  const dark = mode === 'dark';
  const dim  = state === 'bg';

  if (dark) {
    return {
      mode, state, dim,
      surface:      dim ? 'rgba(28,28,32,0.55)' : 'rgba(28,28,32,0.92)',
      surfaceInner: 'rgba(255,255,255,0.04)',
      hairline:     dim ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.09)',
      text:         dim ? 'rgba(242,242,244,0.50)' : '#F2F2F4',
      textDim:      dim ? 'rgba(242,242,244,0.32)' : 'rgba(242,242,244,0.55)',
      textFaint:    dim ? 'rgba(242,242,244,0.22)' : 'rgba(242,242,244,0.36)',
      track:        dim ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.09)',
      accentMul:    dim ? 0.55 : 1.0,
      shadow:       dim ? 'none' : '0 14px 30px rgba(0,0,0,0.45), inset 0 0 0 0.5px rgba(255,255,255,0.05)',
    };
  }
  return {
    mode, state, dim,
    surface:      dim ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.96)',
    surfaceInner: 'rgba(0,0,0,0.025)',
    hairline:     dim ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.08)',
    text:         dim ? 'rgba(20,20,24,0.55)' : '#141418',
    textDim:      dim ? 'rgba(20,20,24,0.38)' : 'rgba(20,20,24,0.55)',
    textFaint:    dim ? 'rgba(20,20,24,0.26)' : 'rgba(20,20,24,0.38)',
    track:        dim ? 'rgba(0,0,0,0.05)' : 'rgba(0,0,0,0.08)',
    accentMul:    dim ? 0.55 : 1.0,
    shadow:       dim ? 'none' : '0 14px 30px rgba(0,0,0,0.18), inset 0 0 0 0.5px rgba(255,255,255,0.4)',
  };
}

function tint(color, mul) {
  if (mul >= 0.99) return color;
  return color + Math.round(mul * 255).toString(16).padStart(2,'0');
}

const fontStack = `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif`;
const monoStack = `"SF Mono", ui-monospace, Menlo, monospace`;

// ─────────────────────────────────────────────────────────────
// Primitives
// ─────────────────────────────────────────────────────────────
function Dot({ color, size = 6, glow = true }) {
  return <span style={{
    width:size, height:size, borderRadius:99, background:color, display:'inline-block',
    boxShadow: glow ? `0 0 8px ${color}66` : 'none', flexShrink:0,
  }}/>;
}

// SyncButton — clickable refresh control; spins icon and updates timestamp
function SyncButton({ theme, compact, initialTime = NOW_LABEL }) {
  const [time, setTime] = useState(initialTime);
  const [spinning, setSpinning] = useState(false);

  const refresh = (e) => {
    e.stopPropagation();
    if (spinning) return;
    setSpinning(true);
    setTimeout(() => {
      const d = new Date();
      setTime(`${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`);
      setSpinning(false);
    }, 650);
  };

  return (
    <button onClick={refresh} aria-label="Refresh"
      style={{
        display:'inline-flex', alignItems:'center', gap:4,
        padding: compact ? '2px 5px' : '3px 7px',
        border: 'none', background: theme.surfaceInner,
        borderRadius: 99, cursor: 'pointer',
        color: theme.textDim, fontSize: compact ? 9 : 9.5,
        fontFamily: monoStack, fontVariantNumeric: 'tabular-nums',
        letterSpacing:'0.02em', userSelect:'none',
      }}>
      <svg width="9" height="9" viewBox="0 0 12 12" style={{
        display:'block',
        animation: spinning ? 'wightSpin 0.65s linear' : 'none',
        transformOrigin: '50% 50%',
      }}>
        {/* refresh / circular arrow glyph */}
        <path d="M10 6 A4 4 0 1 1 6 2 V0.5 L8.6 2.3 L6 4.2 V2.6"
              stroke="currentColor" strokeWidth="1.3" fill="none"
              strokeLinejoin="round" strokeLinecap="round"/>
      </svg>
      {time}
    </button>
  );
}

// Backwards-compatible alias (some callers may still reference SyncBadge)
const SyncBadge = SyncButton;

// One usage bar with label + percent + (optional) reset chip
function BarRow({ label, value, color, theme, reset, compact = false }) {
  const labelW = compact ? 14 : 16;
  return (
    <div style={{ display:'flex', alignItems:'center', gap: compact ? 4 : 5, minWidth:0 }}>
      <span style={{
        fontSize: compact ? 9 : 9.5, fontFamily: monoStack,
        color: theme.textFaint, letterSpacing:'0.04em', width: labelW,
      }}>{label}</span>
      <div style={{
        flex:1, minWidth: 0, height: compact ? 4 : 5,
        background: theme.track, borderRadius: 99, overflow:'hidden',
      }}>
        <div style={{
          width: `${Math.min(100, value*100)}%`, height:'100%',
          background: color, borderRadius: 99,
        }}/>
      </div>
      <span style={{
        fontSize: compact ? 9.5 : 10, fontWeight: 700, fontFamily: monoStack,
        color: theme.text, width: compact ? 26 : 30, textAlign:'right', fontVariantNumeric:'tabular-nums',
      }}>{pct(value)}%</span>
      {reset && (
        <span style={{
          fontSize: 9, fontFamily: monoStack, color: theme.textFaint,
          minWidth: compact ? 48 : 56, textAlign:'right',
          whiteSpace:'nowrap', fontVariantNumeric:'tabular-nums',
        }}>{reset}</span>
      )}
    </div>
  );
}

// AgentBlock — name + 5H bar + WK bar (used by all three sizes)
function AgentBlock({ agent, theme, showReset = false, compact = false }) {
  const c = tint(agent.color, theme.accentMul);
  // On compact (Small) layouts the WK row shows the calendar date (MM-DD) instead
  // of the day-of-week + time — it tells the user *which Monday* the quota resets on.
  const wkReset = compact ? agent.week.resetAtDate : agent.week.resetAt;
  return (
    <div style={{ display:'flex', flexDirection:'column', gap: compact ? 3 : 4, minWidth:0 }}>
      <div style={{ display:'flex', alignItems:'center', gap:5 }}>
        <Dot color={c} size={compact ? 5 : 6} glow={!theme.dim}/>
        <span style={{
          fontSize: compact ? 10.5 : 11.5, fontWeight: 700,
          color: theme.text, letterSpacing:'-0.01em',
        }}>{agent.short}</span>
        {!compact && (
          <span style={{
            marginLeft:'auto', fontSize: 9, fontFamily: monoStack,
            color: theme.textFaint, fontVariantNumeric:'tabular-nums',
          }}>
            {fmt(agent.w5h.used + agent.week.used)}
          </span>
        )}
      </div>
      <BarRow label="5H" value={agent.w5h.used/agent.w5h.quota}
              color={c} theme={theme} compact={compact}
              reset={showReset ? agent.w5h.resetAt : null}/>
      <BarRow label="WK" value={agent.week.used/agent.week.quota}
              color={c} theme={theme} compact={compact}
              reset={showReset ? wkReset : null}/>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Pie chart (donut) — used for host distribution on Large
// ─────────────────────────────────────────────────────────────
function Pie({ size, segments, agentColor, theme, hole = 0.42 }) {
  const cx = size/2, cy = size/2, r = size/2;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let acc = 0;

  // host shading: same agent hue at descending opacity
  const opacities = segments.length === 1 ? [1]
    : segments.length === 2 ? [1, 0.55]
    : [1, 0.62, 0.34];

  return (
    <svg width={size} height={size}>
      {segments.map((seg, i) => {
        const start = acc / total;
        acc += seg.value;
        const end = acc / total;
        const sa = start * 2 * Math.PI - Math.PI/2;
        const ea = end   * 2 * Math.PI - Math.PI/2;
        const large = (end - start) > 0.5 ? 1 : 0;
        const x1 = cx + r * Math.cos(sa);
        const y1 = cy + r * Math.sin(sa);
        const x2 = cx + r * Math.cos(ea);
        const y2 = cy + r * Math.sin(ea);
        // full-circle single segment guard
        const d = (segments.length === 1)
          ? `M ${cx-r} ${cy} a ${r} ${r} 0 1 0 ${2*r} 0 a ${r} ${r} 0 1 0 ${-2*r} 0 Z`
          : `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
        return <path key={i} d={d} fill={agentColor} opacity={opacities[i] ?? 0.3}/>;
      })}
      {hole > 0 && (
        <circle cx={cx} cy={cy} r={r * hole}
                fill={theme.mode === 'dark' ? '#1c1c20' : '#ffffff'}
                opacity={theme.dim ? 0.75 : 1}/>
      )}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// Stacked bars chart (input HIT / MISS / OUT)
// ─────────────────────────────────────────────────────────────
function StackedBars({ series, width, height, theme, agentColor }) {
  const { cached, uncached, output } = series;
  const n = cached.length;
  const totals = cached.map((_, i) => cached[i] + uncached[i] + output[i]);
  const max = Math.max(...totals, 1);
  const barGap = n > 20 ? 2 : 3;
  const bw = (width - barGap * (n - 1)) / n;
  return (
    <svg width={width} height={height} style={{display:'block'}}>
      {cached.map((_, i) => {
        const x = i * (bw + barGap);
        const cH = (cached[i]   / max) * height;
        const uH = (uncached[i] / max) * height;
        const oH = (output[i]   / max) * height;
        let y = height;
        const items = [];
        items.push(<rect key="o" x={x} y={y - oH} width={bw} height={oH}
          fill={agentColor} opacity={theme.dim ? 0.5 : 0.95}/>);
        y -= oH;
        items.push(<rect key="u" x={x} y={y - uH} width={bw} height={uH}
          fill={agentColor} opacity={theme.dim ? 0.32 : 0.60}/>);
        y -= uH;
        items.push(<rect key="c" x={x} y={y - cH} width={bw} height={cH}
          fill={agentColor} opacity={theme.dim ? 0.18 : 0.32}/>);
        return <g key={i}>{items}</g>;
      })}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// Provider-stacked bars chart — each layer is one agent (its own hue)
// ─────────────────────────────────────────────────────────────
function StackedBarsByLayer({ layers, width, height, theme }) {
  if (!layers.length) return null;
  const n = layers[0].values.length;
  const totals = Array.from({length: n}, (_, i) =>
    layers.reduce((s, l) => s + l.values[i], 0)
  );
  const max = Math.max(...totals, 1);
  const barGap = n > 20 ? 2 : 3;
  const bw = (width - barGap * (n - 1)) / n;
  return (
    <svg width={width} height={height} style={{display:'block'}}>
      {Array.from({length: n}).map((_, i) => {
        const x = i * (bw + barGap);
        let y = height;
        const items = layers.map(l => {
          const h = (l.values[i] / max) * height;
          y -= h;
          return <rect key={l.id} x={x} y={y} width={bw} height={h}
                       fill={tint(l.color, theme.accentMul)}
                       opacity={theme.dim ? 0.6 : 0.95}/>;
        });
        return <g key={i}>{items}</g>;
      })}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// HostPie — donut with per-segment color (host-by-host)
// ─────────────────────────────────────────────────────────────
function HostPie({ size, segments, theme, hole = 0.42 }) {
  const cx = size/2, cy = size/2, r = size/2;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let acc = 0;
  return (
    <svg width={size} height={size}>
      {segments.map((seg, i) => {
        const start = acc / total;
        acc += seg.value;
        const end = acc / total;
        const sa = start * 2 * Math.PI - Math.PI/2;
        const ea = end   * 2 * Math.PI - Math.PI/2;
        const large = (end - start) > 0.5 ? 1 : 0;
        const x1 = cx + r * Math.cos(sa);
        const y1 = cy + r * Math.sin(sa);
        const x2 = cx + r * Math.cos(ea);
        const y2 = cy + r * Math.sin(ea);
        const d = (segments.length === 1)
          ? `M ${cx-r} ${cy} a ${r} ${r} 0 1 0 ${2*r} 0 a ${r} ${r} 0 1 0 ${-2*r} 0 Z`
          : `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
        return <path key={i} d={d} fill={tint(seg.color, theme.accentMul)}
                     opacity={theme.dim ? 0.75 : 1}/>;
      })}
      {hole > 0 && (
        <circle cx={cx} cy={cy} r={r * hole}
                fill={theme.mode === 'dark' ? '#1c1c20' : '#ffffff'}
                opacity={theme.dim ? 0.75 : 1}/>
      )}
    </svg>
  );
}
const SIZES = {
  small:  { w: 170, h: 170, r: 22, pad: 14 },
  medium: { w: 364, h: 170, r: 22, pad: 14 },
  large:  { w: 364, h: 382, r: 28, pad: 16 },
};

function WidgetShell({ size, theme, children }) {
  const d = SIZES[size];
  return (
    <div style={{
      width: d.w, height: d.h, borderRadius: d.r, padding: d.pad,
      background: theme.surface,
      backdropFilter: 'blur(40px) saturate(150%)',
      WebkitBackdropFilter: 'blur(40px) saturate(150%)',
      boxShadow: theme.shadow,
      color: theme.text, fontFamily: fontStack,
      letterSpacing:'-0.01em', position:'relative', overflow:'hidden',
    }}>{children}</div>
  );
}

function WidgetHeader({ theme, title, right, compact = false, showDots = false }) {
  return (
    <div style={{
      display:'flex', alignItems:'center', justifyContent:'space-between',
      marginBottom: compact ? 6 : 8, gap: 6, minWidth:0,
    }}>
      <div style={{ display:'flex', alignItems:'center', gap:4, minWidth:0 }}>
        {showDots && <Dot color={tint(AGENTS[0].color, theme.accentMul)} size={6} glow={!theme.dim}/>}
        {showDots && <Dot color={tint(AGENTS[1].color, theme.accentMul)} size={6} glow={!theme.dim}/>}
        <span style={{
          fontSize: compact ? 10 : 10.5, fontWeight: 700,
          color: theme.textDim, letterSpacing:'0.08em', marginLeft: showDots ? 2 : 0,
          whiteSpace:'nowrap',
        }}>{title}</span>
      </div>
      {right}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SMALL — 2 agents × (5H + WK) bars; resets in footer
// ─────────────────────────────────────────────────────────────
function SmallWidget({ theme }) {
  return (
    <WidgetShell size="small" theme={theme}>
      <div style={{ display:'flex', flexDirection:'column', height:'100%' }}>
        <WidgetHeader theme={theme} title="AI USAGE" compact
          right={<SyncButton theme={theme} compact/>} />

        <div style={{ display:'flex', flexDirection:'column', gap:14, flex:1, justifyContent:'center' }}>
          {PRIMARY_AGENTS.map(a => (
            <AgentBlock key={a.id} agent={a} theme={theme} compact showReset />
          ))}
        </div>
      </div>
    </WidgetShell>
  );
}

// ─────────────────────────────────────────────────────────────
// MEDIUM — 2 agent panes side-by-side, each with bars + resets
// ─────────────────────────────────────────────────────────────
function MediumWidget({ theme }) {
  return (
    <WidgetShell size="medium" theme={theme}>
      <div style={{ display:'flex', flexDirection:'column', height:'100%' }}>
        <WidgetHeader theme={theme} title="AI USAGE"
          right={<SyncButton theme={theme}/>} />

        <div style={{
          display:'grid', gridTemplateColumns:'1fr 1fr', gap:8,
          flex:1, minHeight:0,
        }}>
          {AGENTS.map(a => {
            const c = tint(a.color, theme.accentMul);
            return (
              <div key={a.id} style={{
                minWidth:0,
                background: theme.surfaceInner,
                borderRadius: 12, padding: '6px 10px',
                display:'flex', flexDirection:'column', justifyContent:'space-between', gap:3,
              }}>
                <div style={{ display:'flex', alignItems:'center', gap:5 }}>
                  <Dot color={c} size={6} glow={!theme.dim}/>
                  <span style={{ fontSize:11, fontWeight:700, color:theme.text }}>{a.short}</span>
                  <span style={{ marginLeft:'auto', fontSize:9, fontFamily:monoStack, color:theme.textFaint, fontVariantNumeric:'tabular-nums' }}>
                    {fmt(a.w5h.used + a.week.used)}
                  </span>
                </div>
                <BarRow label="5H" value={a.w5h.used/a.w5h.quota}
                  color={c} theme={theme} compact reset={a.w5h.resetAt}/>
                <BarRow label="WK" value={a.week.used/a.week.quota}
                  color={c} theme={theme} compact reset={a.week.resetAtDate}/>
              </div>
            );
          })}
        </div>
      </div>
    </WidgetShell>
  );
}

// ─────────────────────────────────────────────────────────────
// LARGE — Layer 1 (bars + resets) + Layer 2 (chart) + hosts pies
// ─────────────────────────────────────────────────────────────
function LargeWidget({ theme, periodId = '1d' }) {
  const period = useMemo(() => PERIODS.find(p => p.id === periodId), [periodId]);
  const byAgent = useMemo(() => seriesByAgent(periodId), [periodId]);
  const hosts   = HOSTS_BY_PERIOD[periodId] || HOSTS_BY_PERIOD['1d'];

  return (
    <WidgetShell size="large" theme={theme}>
      <div style={{ display:'flex', flexDirection:'column', height:'100%', gap:10 }}>
        <WidgetHeader theme={theme} title="AI USAGE"
          right={
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              <SyncButton theme={theme}/>
              <div style={{
                display:'flex', gap:1, padding:2,
                background: theme.surfaceInner, borderRadius: 99,
              }}>
                {PERIODS.map(p => (
                  <span key={p.id} style={{
                    fontSize: 10, fontWeight: 600,
                    padding: '2px 7px', borderRadius: 99,
                    background: p.id === periodId
                      ? (theme.mode === 'dark' ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.07)')
                      : 'transparent',
                    color: p.id === periodId ? theme.text : theme.textDim,
                  }}>{p.label}</span>
                ))}
              </div>
            </div>
          } />

        {/* Provider-stacked time-series chart */}
        <div style={{
          background: theme.surfaceInner,
          borderRadius: 14, padding: '12px 14px 10px',
          display:'flex', flexDirection:'column', gap:8,
        }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline' }}>
            <span style={{ fontSize:10, fontFamily:monoStack, color:theme.textFaint, letterSpacing:'0.08em' }}>
              USAGE BY PROVIDER
            </span>
            <div style={{ display:'flex', gap:9, fontSize:9.5, fontFamily:fontStack, color:theme.textDim }}>
              {AGENTS.map(a => (
                <span key={a.id} style={{ display:'inline-flex', alignItems:'center', gap:3 }}>
                  <span style={{
                    display:'inline-block', width:8, height:8, borderRadius:2,
                    background: tint(a.color, theme.accentMul),
                  }}/>
                  {a.short}
                </span>
              ))}
            </div>
          </div>
          <StackedBarsByLayer layers={byAgent.layers} width={304} height={100} theme={theme}/>
          <div style={{ display:'flex', justifyContent:'space-between' }}>
            {period.axis.map(a => (
              <span key={a} style={{ fontSize:9.5, color:theme.textFaint, fontFamily:monoStack }}>{a}</span>
            ))}
          </div>
        </div>

        {/* Hosts panel · one pie + legend, time-window aware */}
        <div style={{
          background: theme.surfaceInner,
          borderRadius: 14, padding: '12px 14px',
          flex: 1, display:'flex', flexDirection:'column', gap:8, minHeight:0,
        }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline' }}>
            <span style={{ fontSize:10, fontFamily:monoStack, color:theme.textFaint, letterSpacing:'0.08em' }}>
              HOSTS · 数据采集来源
            </span>
            <span style={{ fontSize:9.5, fontFamily:monoStack, color:theme.textFaint }}>
              {hosts.length} sources
            </span>
          </div>
          <div style={{ display:'flex', gap:14, alignItems:'center', flex:1, minHeight:0 }}>
            <HostPie size={96} theme={theme}
              segments={hosts.map(h => ({ value: h.share, color: HOST_COLORS[h.label] || theme.text }))}/>
            <div style={{ flex:1, display:'flex', flexDirection:'column', gap:5, minWidth:0 }}>
              {hosts.map(h => {
                const color = HOST_COLORS[h.label] || theme.text;
                return (
                  <div key={h.label} style={{ display:'flex', alignItems:'center', gap:7, minWidth:0 }}>
                    <span style={{
                      width:9, height:9, borderRadius:3,
                      background: tint(color, theme.accentMul),
                      flexShrink:0,
                    }}/>
                    <span style={{
                      fontSize:11, fontWeight:600, color:theme.text,
                      whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
                    }}>{h.label}</span>
                    <span style={{
                      fontSize:9.5, color:theme.textFaint, fontFamily:monoStack,
                      whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis', minWidth:0,
                    }}>{h.kind}</span>
                    <span style={{
                      marginLeft:'auto', fontSize:11, fontWeight:700,
                      color:theme.text, fontFamily:monoStack,
                      fontVariantNumeric:'tabular-nums',
                    }}>{Math.round(h.share*100)}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </WidgetShell>
  );
}

// ─────────────────────────────────────────────────────────────
// Wallpaper backdrop for screenshot realism
// ─────────────────────────────────────────────────────────────
function Wallpaper({ mode, state, children, w, h, pad = 26 }) {
  const dark = mode === 'dark';
  const dim  = state === 'bg';
  const lightBg = `
    radial-gradient(120% 90% at 15% 10%, #f7d6c1 0%, transparent 55%),
    radial-gradient(110% 80% at 95% 25%, #d9d6f0 0%, transparent 55%),
    radial-gradient(120% 100% at 60% 100%, #bfd9e8 0%, transparent 60%),
    linear-gradient(180deg, #f1efe9 0%, #e6e1d6 100%)`;
  const darkBg = `
    radial-gradient(120% 80% at 20% 10%, #4a3a6e 0%, transparent 55%),
    radial-gradient(100% 80% at 90% 30%, #6b4a4a 0%, transparent 55%),
    radial-gradient(120% 100% at 60% 100%, #2a3a5e 0%, transparent 60%),
    linear-gradient(180deg, #14121d 0%, #0a0a12 100%)`;
  return (
    <div style={{
      width: w, height: h, borderRadius: 28,
      background: dark ? darkBg : lightBg,
      display:'flex', alignItems:'center', justifyContent:'center', padding: pad,
      boxShadow: dark ? 'inset 0 0 80px rgba(0,0,0,0.5)' : 'inset 0 0 80px rgba(0,0,0,0.06)',
      position:'relative', overflow:'hidden',
    }}>
      {dim && (
        <div style={{
          position:'absolute', inset:0, pointerEvents:'none',
          background: dark ? 'rgba(0,0,0,0.35)' : 'rgba(255,255,255,0.40)',
        }}/>
      )}
      <div style={{ position:'relative' }}>{children}</div>
    </div>
  );
}

function Stage({ mode, state, size, w, h, pad }) {
  const theme = makeTheme(mode, state);
  const W = { small: SmallWidget, medium: MediumWidget, large: LargeWidget }[size];
  return (
    <Wallpaper mode={mode} state={state} w={w} h={h} pad={pad}>
      <W theme={theme}/>
    </Wallpaper>
  );
}

Object.assign(window, {
  AGENTS, AGENT_COLORS, PERIODS,
  makeTheme, Wallpaper, Stage,
  SmallWidget, MediumWidget, LargeWidget,
  fontStack, monoStack,
});

type AnyRecord = Record<string, unknown>;

export function buildMobileSummary(snapshot: AnyRecord): AnyRecord {
  const summary = dict(snapshot.summary);
  const trend = dict(snapshot.trend);
  const sourceStatus = list<AnyRecord>(snapshot.source_status);
  const groups = dict(snapshot.groups);
  const items = list<AnyRecord>(snapshot.items);
  const limits = list<AnyRecord>(snapshot.limits);
  const generatedAt = parseDate(str(snapshot.generated_at));
  const cacheTokens = int(summary.cache_creation_tokens) + int(summary.cache_read_tokens);
  const totalTokens = int(summary.total_tokens);
  const accountContext = accountContextFrom(snapshot.account_hourly, snapshot.ai_accounts);
  const windows = limits
    .map((row) => limitWindow(row, accountContext))
    .filter((window) => effectiveLimitWindow(window))
    .filter((window) => !expiredShortWindow(window, generatedAt));
  const byMachine = groupRows(list<AnyRecord>(groups.by_machine));
  const visibleSourceIds = new Set(byMachine.flatMap((row) => list<string>(row.source_ids).map(String)));
  const healthSourceIds = new Set(
    sourceStatus
      .filter((row) => isHealthIssueSource(row))
      .map((row) => str(row.source_id))
      .filter(Boolean),
  );
  const mobileSourceIds = new Set([...visibleSourceIds, ...healthSourceIds]);
  return {
    schema_version: 1,
    client: "ios",
    generated_at: snapshot.generated_at,
    timezone: snapshot.timezone,
    period: {
      id: summary.period || "today",
      date: summary.date,
      start_date: summary.start_date,
      end_date: summary.end_date,
      total_tokens: totalTokens,
      input_tokens: int(summary.input_tokens),
      output_tokens: int(summary.output_tokens),
      cache_tokens: cacheTokens,
      cache_ratio: ratio(cacheTokens, totalTokens),
      machine: summary.machine ?? null,
      account: summary.account ?? null,
    },
    trend: mobileTrend(trend),
    sources: sourceStatus
      .filter((row) => mobileSourceIds.has(str(row.source_id)))
      .map((row) => mobileSource(row)),
    breakdown: {
      by_machine: byMachine,
      by_os_user: osUserRows(list<AnyRecord>(groups.by_machine), items),
      by_agent: agentRows(items),
      by_model: modelRows(items),
      by_date: dateRows(items),
    },
    limits: {
      observed_count: windows.filter((row) => row.confidence === "observed" && row.official === true && row.status === "ok").length,
      total_count: windows.length,
      windows,
    },
    metadata: mobileMetadata(snapshot, windows),
  };
}

function mobileTrend(trend: AnyRecord): AnyRecord {
  const points = list<AnyRecord>(trend.points).map((row) => {
    const bucket = row.hour || row.date;
    const totalTokens = int(row.total_tokens);
    const cacheTokens = int(row.cache_tokens);
    return {
      bucket,
      label: trendLabel(bucket, trend.granularity),
      tokens: totalTokens,
      input_tokens: int(row.input_tokens),
      output_tokens: int(row.output_tokens),
      cache_tokens: cacheTokens,
      cache_ratio: ratio(cacheTokens, totalTokens),
    };
  });
  return {
    period: trend.period,
    granularity: trend.granularity,
    start_date: trend.start_date,
    end_date: trend.end_date,
    points,
  };
}

function mobileSource(row: AnyRecord): AnyRecord {
  const machine = row.machine || row.host || row.source_id;
  const osUser = row.os_user || row.account;
  const observedAt = row.observed_at;
  return {
    source_id: row.source_id,
    machine,
    os_user: osUser,
    platform: row.platform,
    display_name: row.display_name || displayName(machine, osUser),
    status: row.status || "unknown",
    last_observed_at: observedAt,
    last_pushed_at: observedAt,
    error_message: row.error_message,
  };
}

function limitWindow(row: AnyRecord, accountContext: Record<string, AnyRecord>): AnyRecord {
  const provider = str(row.provider);
  const providerContext = accountContext[provider.toLowerCase()] || {};
  const accountLabel = safeAccountLabel(row.account_email || row.account_label || providerContext.label || providerContext.display_name);
  const planLabel = safePlanLabel(
    provider,
    row.account_plan_label || row.account_plan || row.subscription || providerContext.subscription,
  );
  const result: AnyRecord = {
    source_id: row.source_id,
    provider,
    window: row.window,
    used_percent: number(row.used_percent),
    remaining_percent: number(row.remaining_percent),
    reset_at: row.reset_at,
    window_duration_minutes: int(row.window_duration_minutes),
    observed_at: row.observed_at,
    source_type: row.source_type,
    confidence: row.confidence || "unknown",
    status: row.status || "unknown",
    official: Boolean(row.official),
  };
  if (accountLabel) result.account_label = accountLabel;
  if (planLabel) result.account_plan_label = planLabel;
  return result;
}

function effectiveLimitWindow(window: AnyRecord): boolean {
  return window.official === true &&
    window.confidence === "observed" &&
    window.status === "ok" &&
    window.source_type !== "active_limits_cache";
}

function mobileMetadata(snapshot: AnyRecord, windows: AnyRecord[]): AnyRecord {
  const metadata = dict(snapshot.metadata);
  const observed = windows.map((window) => str(window.observed_at)).filter(Boolean).sort();
  return {
    backend_mode: metadata.backend_mode || "native_d1_staging",
    canonical_store: metadata.canonical_store || "cloudflare_d1",
    read_model_generated_at: metadata.read_model_generated_at || snapshot.generated_at,
    freshness_status: metadata.freshness_status || (windows.length ? "ok" : "unknown"),
    limits_observed_at: metadata.limits_observed_at || (observed.length ? observed[observed.length - 1] : null),
  };
}

function groupRows(rows: AnyRecord[]): AnyRecord[] {
  const result: AnyRecord[] = [];
  for (const row of rows) {
    const label = row.display_name || row.name;
    const totalTokens = int(row.total_tokens);
    if (totalTokens <= 0) continue;
    const sourceIds = new Set(list<unknown>(row.source_ids).map(String));
    const contributions: Record<string, number> = {};
    for (const user of list<AnyRecord>(row.users)) {
      for (const sourceId of list<unknown>(user.source_ids)) sourceIds.add(String(sourceId));
      addContribution(contributions, list<unknown>(user.source_ids), int(user.total_tokens));
    }
    if (!Object.keys(contributions).length) addContribution(contributions, list<unknown>(row.source_ids), totalTokens);
    result.push({
      id: row.name || label,
      label,
      tokens: totalTokens,
      source_ids: Array.from(sourceIds).sort(),
      contributions: contributionRows(contributions),
    });
  }
  return sortRows(result);
}

function osUserRows(machineRows: AnyRecord[], items: AnyRecord[]): AnyRecord[] {
  const rows = new Map<string, { id: unknown; label: unknown; tokens: number; source_ids: Set<string>; contributions: Record<string, number> }>();
  for (const machine of machineRows) {
    for (const user of list<AnyRecord>(machine.users)) {
      const totalTokens = int(user.total_tokens);
      if (totalTokens <= 0) continue;
      const label = user.account || "unknown";
      const key = str(label);
      const entry = rows.get(key) || { id: label, label, tokens: 0, source_ids: new Set(), contributions: {} };
      entry.tokens += totalTokens;
      for (const sourceId of list<unknown>(user.source_ids)) entry.source_ids.add(String(sourceId));
      addContribution(entry.contributions, list<unknown>(user.source_ids), totalTokens);
      rows.set(key, entry);
    }
  }
  if (!rows.size) {
    for (const item of items) {
      const totalTokens = int(item.total_tokens);
      if (totalTokens <= 0) continue;
      const label = item.account || "unknown";
      const key = str(label);
      const entry = rows.get(key) || { id: label, label, tokens: 0, source_ids: new Set(), contributions: {} };
      entry.tokens += totalTokens;
      if (item.source_id) {
        entry.source_ids.add(str(item.source_id));
        addContribution(entry.contributions, [item.source_id], totalTokens);
      }
      rows.set(key, entry);
    }
  }
  return sortRows(Array.from(rows.values()).filter((row) => row.tokens > 0).map((row) => ({
    id: row.id,
    label: row.label,
    tokens: row.tokens,
    source_ids: Array.from(row.source_ids).sort(),
    contributions: contributionRows(row.contributions),
  })));
}

function agentRows(items: AnyRecord[]): AnyRecord[] {
  const rows = new Map<string, { id: string; label: string; tokens: number; source_ids: Set<string>; contributions: Record<string, number> }>();
  for (const item of items) {
    const label = str(item.agent || "unknown");
    const entry = rows.get(label) || { id: label, label, tokens: 0, source_ids: new Set(), contributions: {} };
    const tokens = int(item.total_tokens);
    entry.tokens += tokens;
    if (item.source_id) {
      entry.source_ids.add(str(item.source_id));
      addContribution(entry.contributions, [item.source_id], tokens);
    }
    rows.set(label, entry);
  }
  return sortRows(Array.from(rows.values()).map((row) => ({
    id: row.id,
    label: row.label,
    tokens: row.tokens,
    source_ids: Array.from(row.source_ids).sort(),
    contributions: contributionRows(row.contributions),
  })));
}

function modelRows(items: AnyRecord[]): AnyRecord[] {
  const rows = new Map<string, { id: unknown; label: unknown; tokens: number; source_ids: Set<string>; contributions: Record<string, number> }>();
  for (const item of items) {
    for (const model of list<AnyRecord>(item.model_breakdowns)) {
      const label = model.model_name || "unknown";
      const key = str(label);
      const entry = rows.get(key) || { id: label, label, tokens: 0, source_ids: new Set(), contributions: {} };
      const tokens = int(model.total_tokens);
      entry.tokens += tokens;
      if (item.source_id) {
        entry.source_ids.add(str(item.source_id));
        addContribution(entry.contributions, [item.source_id], tokens);
      }
      rows.set(key, entry);
    }
  }
  return sortRows(Array.from(rows.values()).map((row) => ({
    id: str(row.id),
    label: str(row.label),
    tokens: row.tokens,
    source_ids: Array.from(row.source_ids).sort(),
    contributions: contributionRows(row.contributions),
  })));
}

function dateRows(items: AnyRecord[]): AnyRecord[] {
  const rows = new Map<string, { id: unknown; label: unknown; tokens: number; source_ids: Set<string>; contributions: Record<string, number> }>();
  for (const item of items) {
    const label = item.date || "unknown";
    const key = str(label);
    const entry = rows.get(key) || { id: label, label, tokens: 0, source_ids: new Set(), contributions: {} };
    const tokens = int(item.total_tokens);
    entry.tokens += tokens;
    if (item.source_id) {
      entry.source_ids.add(str(item.source_id));
      addContribution(entry.contributions, [item.source_id], tokens);
    }
    rows.set(key, entry);
  }
  return Array.from(rows.values()).map((row) => ({
    id: str(row.id),
    label: str(row.label),
    tokens: row.tokens,
    source_ids: Array.from(row.source_ids).sort(),
    contributions: contributionRows(row.contributions),
  })).sort((lhs, rhs) => lhs.label.localeCompare(rhs.label));
}

function accountContextFrom(accountHourly: unknown, aiAccounts: unknown): Record<string, AnyRecord> {
  const rows = [...list<AnyRecord>(dict(accountHourly).by_ai_account), ...list<AnyRecord>(aiAccounts)];
  const grouped: Record<string, Record<string, AnyRecord>> = {};
  rows.forEach((row, index) => {
    const provider = providerContextKey(row.provider);
    const context = accountContextRow(row);
    if (!provider || !Object.keys(context).length) return;
    const key = accountContextKey(context, index);
    grouped[provider] ||= {};
    if (grouped[provider][key]) mergeAccountContext(grouped[provider][key], context);
    else grouped[provider][key] = context;
  });
  const result: Record<string, AnyRecord> = {};
  for (const [provider, accounts] of Object.entries(grouped)) {
    const values = Object.values(accounts);
    if (values.length === 1) result[provider] = values[0];
  }
  return result;
}

function accountContextRow(row: AnyRecord): AnyRecord {
  const result: AnyRecord = {
    account_id: str(row.account_id || row.ai_account_id || "").trim(),
    label: safeAccountLabel(row.label || row.account_label || row.account_email),
    display_name: safeAccountLabel(row.display_name),
    subscription: row.subscription || row.account_plan || row.account_plan_label,
  };
  return Object.fromEntries(Object.entries(result).filter(([, value]) => value !== null && value !== ""));
}

function accountContextKey(context: AnyRecord, index: number): string {
  for (const key of ["account_id", "label", "display_name"]) {
    if (context[key]) return `${key}:${context[key]}`;
  }
  return `row:${index}`;
}

function mergeAccountContext(target: AnyRecord, source: AnyRecord): void {
  for (const [key, value] of Object.entries(source)) {
    if ((target[key] === null || target[key] === "" || target[key] === undefined) && value !== null && value !== "") {
      target[key] = value;
    }
  }
}

function providerContextKey(value: unknown): string {
  const provider = str(value).toLowerCase();
  if (provider === "openai") return "codex";
  if (provider === "anthropic") return "claude";
  return provider;
}

function safeAccountLabel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  const lowered = text.toLowerCase();
  const unsafe = ["token", "bearer ", "authorization", "auth.json", ".codex", ".claude", "/users/", "/home/", "\\users\\"];
  if (lowered.startsWith("sk-") || lowered.startsWith("sess-") || lowered.startsWith("eyj")) return null;
  if (unsafe.some((fragment) => lowered.includes(fragment))) return null;
  if (text.length > 120) return null;
  return text;
}

function safePlanLabel(provider: string, value: unknown): string | null {
  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!raw) return null;
  const normalized = raw.toLowerCase().replace(/[_-]/g, " ").split(/\s+/).join(" ");
  const providerKey = provider.toLowerCase();
  if (providerKey.includes("codex") || providerKey.includes("openai")) {
    if (normalized === "pro") return "Pro 20x";
    if (normalized === "prolite" || normalized === "pro lite") return "Pro 5x";
  }
  if ((providerKey.includes("claude") || providerKey.includes("anthropic")) && (normalized === "pro" || normalized === "claude pro")) return "Pro";
  if (raw.length <= 32 && /^[A-Za-z0-9 .+_-]+$/.test(raw)) {
    return raw.replace(/[_-]/g, " ").split(/\s+/).map(titlePlanPart).join(" ");
  }
  return null;
}

function titlePlanPart(value: string): string {
  if (value.toLowerCase().endsWith("x") && /\d/.test(value)) return value.toLowerCase();
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

function isHealthIssueSource(row: AnyRecord): boolean {
  const status = str(row.status).toLowerCase();
  return !["", "ok", "disabled"].includes(status);
}

function expiredShortWindow(window: AnyRecord, generatedAt: Date | null): boolean {
  if (!generatedAt || !isShortWindow(window)) return false;
  const resetAt = parseDate(str(window.reset_at));
  return !!resetAt && resetAt.getTime() <= generatedAt.getTime();
}

function isShortWindow(window: AnyRecord): boolean {
  const name = str(window.window).toLowerCase();
  const duration = int(window.window_duration_minutes);
  return name.includes("5h") || name.includes("session") || (duration > 0 && duration <= 360);
}

function addContribution(contributions: Record<string, number>, sourceIds: unknown[], tokens: number): void {
  const normalized = sourceIds.map(String).filter(Boolean);
  if (!normalized.length) return;
  if (normalized.length === 1) {
    contributions[normalized[0]] = (contributions[normalized[0]] || 0) + tokens;
    return;
  }
  for (const sourceId of normalized) contributions[sourceId] = (contributions[sourceId] || 0) + tokens;
}

function contributionRows(contributions: Record<string, number>): AnyRecord[] {
  return Object.entries(contributions).sort(([left], [right]) => left.localeCompare(right)).map(([source_id, tokens]) => ({ source_id, tokens }));
}

function sortRows(rows: AnyRecord[]): AnyRecord[] {
  return rows.sort((lhs, rhs) => int(rhs.tokens) - int(lhs.tokens) || str(lhs.label).localeCompare(str(rhs.label)));
}

function trendLabel(bucket: unknown, granularity: unknown): string {
  if (typeof bucket !== "string") return "";
  if (granularity === "hour" && bucket.includes("T")) return bucket.split("T", 2)[1].slice(0, 5);
  return bucket;
}

function displayName(machine: unknown, osUser: unknown): string {
  if (machine && osUser) return `${machine} · ${osUser}`;
  return str(machine || osUser || "unknown-source");
}

function ratio(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((part / total) * 100);
}

function int(value: unknown): number {
  if (typeof value === "boolean") return 0;
  if (typeof value === "number") return Math.round(value);
  return 0;
}

function number(value: unknown): number {
  if (typeof value === "boolean") return 0;
  if (typeof value === "number") return value;
  return 0;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function dict(value: unknown): AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function parseDate(value: string): Date | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

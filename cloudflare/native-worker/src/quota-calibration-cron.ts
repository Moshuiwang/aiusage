/**
 * #183-b：每日 cron 里接线计算内核（`src/calibration/`）。
 *
 * 内核本身是纯函数、不摸 D1；这个模块只做三件事：
 * 1. SQL 侧把 28 天窗口内的官方读数、以及「小时 × 模型 × token 类型」聚合好的用量读出来
 *    （SUM 在 SQL 里做，不把逐行 usage_hourly_models 搬到 JS 里再聚合）；
 * 2. 在 JS 里把模型名映射到族（复用 `calibration/constants.ts` 的 `familyForModel`，
 *    跟 fixture 导出脚本、内核本身用同一套映射规则）、补齐 unattributed 完整性差额；
 * 3. 调 `calibrate()`，整表覆盖写 `quota_calibration`。
 *
 * 账户冲突（v1 口径：每个 provider 一个账户）：最近 28 天 `account_observations` 里
 * 同一 provider 出现 >1 个指纹，说明这段时间账户被切换过、系数会把两个账户的用量混在一起
 * 拟合，整个 provider 直接降级成 none，不尝试"哪一段该丢"这种更复杂的判断（v1 简化）。
 *
 * 任何一个 provider 算失败都只 `console.error`，不能让一个账户的异常拖垮其它账户的
 * 计算，也不能影响 cron 里在它之前已经跑完的维护步骤（调用方负责 try/catch 包这个函数）。
 *
 * ## 部署前审查（Must 1）：每次 cron 只算一个 provider，按日轮换
 *
 * 冷启动（新 isolate，没有 JIT 预热）实测三账户合计一次算完是 10.26–10.40ms，超过
 * Cloudflare Free 单次调用 10ms 的 CPU 预算（`calibration-cpu-budget.test.ts` 用同一个热
 * 进程反复跑测出的 P95 2.2ms 会低估——workerd 每个请求/cron 调用都是新鲜（或至少长时间
 * 空闲复用）的 isolate，JIT 没机会预热，`scripts/measure_calibration_cold_cpu.mjs` 用
 * 单进程单次冷跑测的数字才是真门槛）。改成每次只算一个 provider：按 `scheduledTime` 在
 * Asia/Shanghai 的日历日序号取模轮换，3 天一轮，跟 `isStale` 的 4 天过期门槛留出 1 天缓冲
 * （轮换周期 3 天 < 过期门槛 4 天，正常情况下永远不会因为轮换节奏本身触发过期降级）。
 */
import { calibrate, FORMULA_VERSION, UNATTRIBUTED_FAMILY } from "./calibration";
import { localEstimateSourceTypes } from "./read-model/shared";
import type { CalibrationResult, HourlyFamilyFact, LimitObservation } from "./calibration";
import { familyForModel, KNOWN_FAMILIES } from "./calibration/constants";
import type { Provider } from "./calibration/constants";

const PROVIDERS: Provider[] = ["claude", "codex", "antigravity"];
const WINDOW_DAYS = 28;
/** 官方额度读数只用「周」窗口的口径——设计校准分析全程用的是这个窗口（session 窗口太短、
 * 噪音主导 ΔU，不参与拟合）。 */
const CALIBRATION_LIMIT_WINDOW = "week";

/** `scheduledTime` 在 Asia/Shanghai 的日历日序号（从 UNIX epoch 起的整数天数）。 */
function shanghaiDayOrdinal(now: Date): number {
  const shanghaiDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now); // "YYYY-MM-DD"
  return Math.floor(Date.parse(`${shanghaiDate}T00:00:00Z`) / (24 * 60 * 60 * 1000));
}

/** 今天该轮到哪个 provider——3 天一轮，`PROVIDERS` 数组顺序即轮换顺序。 */
function providerForToday(now: Date): Provider {
  const ordinal = shanghaiDayOrdinal(now);
  const index = ((ordinal % PROVIDERS.length) + PROVIDERS.length) % PROVIDERS.length;
  return PROVIDERS[index];
}

export async function runQuotaCalibration(db: D1Database, now: Date): Promise<void> {
  const windowStart = new Date(now.getTime() - WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const provider = providerForToday(now);
  try {
    await calibrateProvider(db, provider, windowStart, now);
  } catch (error) {
    console.error(`quota calibration failed for provider=${provider}`, error);
  }
}

async function calibrateProvider(db: D1Database, provider: Provider, windowStart: string, now: Date): Promise<void> {
  const conflicted = await hasConflictingAccountFingerprint(db, provider, windowStart);
  const results = conflicted
    ? noneResultsForConflict(provider, now)
    : (await calibrateFromDb(db, provider, windowStart, now)).results;
  await writeQuotaCalibration(db, provider, results);
}

function noneResultsForConflict(provider: Provider, now: Date): CalibrationResult[] {
  const fittedAt = now.toISOString();
  return KNOWN_FAMILIES[provider].map((family) => ({
    provider,
    model_family: family,
    coef: 0,
    effective_delta_u: 0,
    backtest_max_err: null,
    grade: "none",
    sample_intervals: 0,
    formula_version: FORMULA_VERSION,
    fitted_at: fittedAt,
  }));
}

async function calibrateFromDb(db: D1Database, provider: Provider, windowStart: string, now: Date) {
  const observations = await fetchLimitObservations(db, provider, windowStart);
  const facts = await fetchHourlyFamilyFacts(db, provider, windowStart);
  return calibrate(provider, observations, facts, { now });
}

/** 最近 28 天内，这个 provider 是否观察到过 >1 个不同的账户指纹。 */
async function hasConflictingAccountFingerprint(db: D1Database, provider: Provider, windowStart: string): Promise<boolean> {
  const row = await db.prepare(`
    SELECT COUNT(DISTINCT account_fingerprint) AS c
    FROM account_observations
    WHERE provider = ? AND last_seen_at >= ?
  `).bind(provider, windowStart).first<{ c: number }>();
  return Number(row?.c ?? 0) > 1;
}

// 只有可信官方读数（ok + observed + 非本地估算来源）参与校准，与 read-model 的 official 判定同口径。
const LOCAL_ESTIMATE_TYPES = [...localEstimateSourceTypes];
const LOCAL_ESTIMATE_PLACEHOLDERS = LOCAL_ESTIMATE_TYPES.map(() => "?").join(", ");

async function fetchLimitObservations(db: D1Database, provider: Provider, windowStart: string): Promise<LimitObservation[]> {
  const rows = await db.prepare(`
    SELECT source_id, provider, observed_at, reset_at, used_percent, window_duration_minutes
    FROM limit_window_history
    WHERE provider = ? AND window = ? AND observed_at >= ?
      AND status = 'ok' AND confidence = 'observed'
      AND source_type NOT IN (${LOCAL_ESTIMATE_PLACEHOLDERS})
    ORDER BY observed_at ASC
  `).bind(provider, CALIBRATION_LIMIT_WINDOW, windowStart, ...LOCAL_ESTIMATE_TYPES).all<Record<string, unknown>>();
  return (rows.results ?? []).map((r) => ({
    source_id: String(r.source_id),
    provider,
    observed_at: String(r.observed_at),
    reset_at: String(r.reset_at),
    used_percent: Number(r.used_percent),
    window_duration_minutes: Number(r.window_duration_minutes),
  }));
}

interface TokenTotals {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

function zeroTotals(): TokenTotals {
  return { input_tokens: 0, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0 };
}

function totalsFromRow(row: Record<string, unknown>): TokenTotals {
  return {
    input_tokens: Number(row.input_tokens) || 0,
    output_tokens: Number(row.output_tokens) || 0,
    cache_creation_tokens: Number(row.cache_creation_tokens) || 0,
    cache_read_tokens: Number(row.cache_read_tokens) || 0,
  };
}

function addInto(target: TokenTotals, addend: TokenTotals): void {
  target.input_tokens += addend.input_tokens;
  target.output_tokens += addend.output_tokens;
  target.cache_creation_tokens += addend.cache_creation_tokens;
  target.cache_read_tokens += addend.cache_read_tokens;
}

/**
 * SQL 侧按「小时 × 模型」SUM 一遍（`modelRows`）、按「小时」SUM 一遍事实总量（`factTotalRows`）
 * ——两次聚合都在 D1 里做，JS 只处理聚合后的结果行，不搬运逐条 usage_hourly_models。
 * 在 JS 里把模型名映射到族，事实总量减去（无论映射到哪个族的）model 行合计的差额落到
 * `unattributed` 伪族——跟 `scripts/export_calibration_fixture.py` 的口径一致。
 */
async function fetchHourlyFamilyFacts(db: D1Database, provider: Provider, windowStart: string): Promise<HourlyFamilyFact[]> {
  const modelRows = await db.prepare(`
    SELECT f.window_start AS window_start, f.window_end AS window_end, hm.model AS model,
           SUM(hm.input_tokens) AS input_tokens, SUM(hm.output_tokens) AS output_tokens,
           SUM(hm.cache_creation_tokens) AS cache_creation_tokens, SUM(hm.cache_read_tokens) AS cache_read_tokens
    FROM usage_hourly_models hm
    JOIN usage_hourly_facts f ON f.fact_id = hm.fact_id
    WHERE f.agent = ? AND f.window_start >= ?
    GROUP BY f.window_start, f.window_end, hm.model
  `).bind(provider, windowStart).all<Record<string, unknown>>();

  const factTotalRows = await db.prepare(`
    SELECT window_start, window_end,
           SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
           SUM(cache_creation_tokens) AS cache_creation_tokens, SUM(cache_read_tokens) AS cache_read_tokens
    FROM usage_hourly_facts
    WHERE agent = ? AND window_start >= ?
    GROUP BY window_start, window_end
  `).bind(provider, windowStart).all<Record<string, unknown>>();

  const keyOf = (ws: string, we: string) => `${ws}\u0000${we}`;
  const byWindow = new Map<string, { totals: TokenTotals; matchedSum: TokenTotals; families: Map<string, TokenTotals> }>();

  for (const row of factTotalRows.results ?? []) {
    const key = keyOf(String(row.window_start), String(row.window_end));
    byWindow.set(key, { totals: totalsFromRow(row), matchedSum: zeroTotals(), families: new Map() });
  }

  for (const row of modelRows.results ?? []) {
    const key = keyOf(String(row.window_start), String(row.window_end));
    let entry = byWindow.get(key);
    if (!entry) {
      entry = { totals: zeroTotals(), matchedSum: zeroTotals(), families: new Map() };
      byWindow.set(key, entry);
    }
    const rowTotals = totalsFromRow(row);
    addInto(entry.matchedSum, rowTotals);
    const family = familyForModel(provider, String(row.model));
    if (family === null) continue; // 已知模型、不追踪的族（deepseek 等）：计入完整性合计，不产出族行
    const famTotals = entry.families.get(family) ?? zeroTotals();
    addInto(famTotals, rowTotals);
    entry.families.set(family, famTotals);
  }

  const out: HourlyFamilyFact[] = [];
  for (const [key, entry] of byWindow) {
    const [ws, we] = key.split("\u0000");
    for (const [family, totals] of entry.families) {
      out.push({ provider, model_family: family, window_start: ws, window_end: we, ...totals });
    }
    const unattributed: TokenTotals = {
      input_tokens: Math.max(0, entry.totals.input_tokens - entry.matchedSum.input_tokens),
      output_tokens: Math.max(0, entry.totals.output_tokens - entry.matchedSum.output_tokens),
      cache_creation_tokens: Math.max(0, entry.totals.cache_creation_tokens - entry.matchedSum.cache_creation_tokens),
      cache_read_tokens: Math.max(0, entry.totals.cache_read_tokens - entry.matchedSum.cache_read_tokens),
    };
    if (Object.values(unattributed).some((v) => v > 0)) {
      out.push({ provider, model_family: UNATTRIBUTED_FAMILY, window_start: ws, window_end: we, ...unattributed });
    }
  }
  return out;
}

async function writeQuotaCalibration(db: D1Database, provider: Provider, results: CalibrationResult[]): Promise<void> {
  const statements: D1PreparedStatement[] = [db.prepare("DELETE FROM quota_calibration WHERE provider = ?").bind(provider)];
  for (const r of results) {
    statements.push(db.prepare(`
      INSERT INTO quota_calibration (
        provider, model_family, coef, effective_delta_u, backtest_max_err, grade,
        sample_intervals, fitted_at, formula_version
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      r.provider, r.model_family, r.coef, r.effective_delta_u, r.backtest_max_err, r.grade,
      r.sample_intervals, r.fitted_at, r.formula_version,
    ));
  }
  await db.batch(statements);
}

export { fetchHourlyFamilyFacts, fetchLimitObservations, hasConflictingAccountFingerprint, providerForToday, shanghaiDayOrdinal };

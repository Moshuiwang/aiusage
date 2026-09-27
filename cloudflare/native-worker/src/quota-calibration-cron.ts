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
 */
import { calibrate, FORMULA_VERSION, UNATTRIBUTED_FAMILY } from "./calibration";
import type { CalibrationResult, HourlyFamilyFact, LimitObservation } from "./calibration";
import { familyForModel, KNOWN_FAMILIES } from "./calibration/constants";
import type { Provider } from "./calibration/constants";

const PROVIDERS: Provider[] = ["claude", "codex", "antigravity"];
const WINDOW_DAYS = 28;
/** 官方额度读数只用「周」窗口的口径——设计校准分析全程用的是这个窗口（session 窗口太短、
 * 噪音主导 ΔU，不参与拟合）。 */
const CALIBRATION_LIMIT_WINDOW = "week";

export async function runQuotaCalibration(db: D1Database, now: Date): Promise<void> {
  const windowStart = new Date(now.getTime() - WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString();
  for (const provider of PROVIDERS) {
    try {
      await calibrateProvider(db, provider, windowStart, now);
    } catch (error) {
      console.error(`quota calibration failed for provider=${provider}`, error);
    }
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

async function fetchLimitObservations(db: D1Database, provider: Provider, windowStart: string): Promise<LimitObservation[]> {
  const rows = await db.prepare(`
    SELECT source_id, provider, observed_at, reset_at, used_percent, window_duration_minutes
    FROM limit_window_history
    WHERE provider = ? AND window = ? AND observed_at >= ?
    ORDER BY observed_at ASC
  `).bind(provider, CALIBRATION_LIMIT_WINDOW, windowStart).all<Record<string, unknown>>();
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

export { fetchHourlyFamilyFacts, hasConflictingAccountFingerprint };

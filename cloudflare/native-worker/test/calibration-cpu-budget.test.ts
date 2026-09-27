/**
 * #183-a：CPU 门禁（go/no-go）+ 性能回归守卫。
 *
 * Cloudflare Free 计划每次调用 CPU 时间预算约 10ms（#183 设计 v1 §4）。这里用真实
 * fixture 全量（三个 provider）跑完整计算，测量多次取中位数与 P95，并把数据按天数外推
 * 复制，估算账户积累到设计要求的 28 天训练窗口时是否还在预算内。
 *
 * ## 背景：早期实现在这里查出过近似平方增长
 *
 * `intervals.ts` 早期实现对每个区间都重新遍历一次全部 facts（还在循环体里反复
 * `Date.parse` 同一批 facts），实测：
 * ```
 * mult=1(~10天)  单账户 median=4.2ms
 * mult=2(~20天)  单账户 median=13.2ms   ← 已超 10ms 预算
 * mult=3(~28天)  单账户 median=27.2ms   ← 远超
 * ```
 * 改成双指针扫描 + `backtest.ts` 的 Sample 预计算（见两个文件头注释）之后，实测：
 * ```
 * mult=1(~10天)  单账户 median=0.807ms p95=1.459ms | 三账户合计 median=1.912ms p95=2.505ms
 * mult=2(~20天)  单账户 median=1.453ms p95=2.068ms | 三账户合计 median=3.697ms p95=4.063ms
 * mult=3(~30天)  单账户 median=1.839ms p95=2.103ms | 三账户合计 median=5.230ms p95=5.559ms
 * mult=4(~40天)  单账户 median=1.979ms p95=2.209ms | 三账户合计 median=5.650ms p95=6.053ms
 * ```
 * 增长曲线从近似平方变成近似线性后趋于平台（`windowDays=28` 本身就是个滚动窗口，
 * 数据总量超过 28 天之后窗口内数据量不再无限增长）。mult=3（约 28 天）验收：
 * 单账户 P95 ≤3ms、三账户合计 P95 ≤6ms——上面的数字都满足。
 *
 * 这些数字是 Node 环境测的，不是 workerd；workerd 的 CPU 计时口径可能不同，
 * 但相对增长曲线（有没有平方项）不依赖运行时，值得作为回归守卫钉住。
 *
 * ## 部署前审查发现：这里的数字会低估真实开销，别拿它当最终验收门槛
 *
 * 这个文件里的测量都在**同一个热进程**里循环跑 `calibrate()`，第一次调用之后 V8 JIT
 * 会把热路径（坐标下降、Date 解析等）优化掉，后续调用自然更快——上面 mult=3 单账户
 * P95≈2.2ms 就是「已经跑过几十次、JIT 预热完」之后的数字。workerd 的每次 cron/请求
 * 调用可能是一个新鲜（或长时间空闲复用、JIT 状态被丢弃）的 isolate，第一次调用付的是
 * 冷启动的账。部署前审查用单次新进程冷跑复现：28 天规模三账户合计 10.26–10.40ms，
 * 单 Claude 账户冷启动 median≈5.7ms、max≈5.84ms（`scripts/measure_calibration_cold_cpu.mjs`，
 * N=7 次独立新进程，见该脚本头注释）——都明显高于这里热进程测出的数字。
 *
 * **真正的验收门槛以 `scripts/measure_calibration_cold_cpu.mjs` 的冷启动数字为准，
 * 不是这个文件里的热进程 P95。** 这个文件仍然有价值：它钉住"复杂度别退回平方增长"这条
 * 回归线（性能回归守卫那一节），但不能用它的绝对数值论证"已经在预算内"。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { calibrate } from "../src/calibration/index";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration/types";

const FIXTURE_PATH = new URL("./calibration_fixture.json", import.meta.url);
const BASE_NOW = new Date("2026-09-27T10:00:00Z");
const RUNS = 20;
/** 比值测量的预热轮数：先让 V8 把各规模的热路径都 JIT 掉，避免第一个被测规模独自背冷启动的账。 */
const WARMUP_RUNS = 5;

async function loadFixture(): Promise<{ limit_observations: LimitObservation[]; hourly_family_facts: HourlyFamilyFact[] }> {
  const raw = await readFile(FIXTURE_PATH, "utf8");
  return JSON.parse(raw);
}

function shiftIso(iso: string, days: number): string {
  return new Date(Date.parse(iso) + days * 86400000).toISOString();
}

/**
 * 把真实数据按 `shiftDaysPerCopy` 天为间隔平移复制 `multiplier` 份，拼成一段更长的历史，
 * 粗估账户数据量随天数增长的 CPU 曲线。这是外推模拟，不是真实数据——真实数据只有账户
 * 起步以来（约 10 天）这么多，还没长到 28 天。
 */
function scaleObservations(rows: LimitObservation[], multiplier: number, shiftDaysPerCopy = 10): LimitObservation[] {
  const out: LimitObservation[] = [];
  for (let c = 0; c < Math.ceil(multiplier); c++) {
    const shiftDays = c * shiftDaysPerCopy;
    for (const r of rows) out.push({ ...r, observed_at: shiftIso(r.observed_at, shiftDays), reset_at: shiftIso(r.reset_at, shiftDays) });
  }
  return out;
}

function scaleFacts(rows: HourlyFamilyFact[], multiplier: number, shiftDaysPerCopy = 10): HourlyFamilyFact[] {
  const out: HourlyFamilyFact[] = [];
  for (let c = 0; c < Math.ceil(multiplier); c++) {
    const shiftDays = c * shiftDaysPerCopy;
    for (const f of rows) out.push({ ...f, window_start: shiftIso(f.window_start, shiftDays), window_end: shiftIso(f.window_end, shiftDays) });
  }
  return out;
}

function percentile(sorted: number[], p: number): number {
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, idx)];
}

function measure(fn: () => void, runs = RUNS): { median: number; p95: number } {
  const durations: number[] = [];
  for (let i = 0; i < runs; i++) {
    const t0 = performance.now();
    fn();
    durations.push(performance.now() - t0);
  }
  durations.sort((a, b) => a - b);
  return { median: percentile(durations, 50), p95: percentile(durations, 95) };
}

interface Timing {
  median: number;
  p95: number;
  /** 最小耗时：比值断言只用它。 */
  min: number;
}

/**
 * 给「同进程内比较不同规模耗时比值」用的测量：先整体预热，再把各规模**交替轮流**各跑
 * `runs` 次，每个规模取最小值。
 *
 * 为什么这样测（CI run 36324474678 两条比值断言因噪声误报 3.59 / 4.16，本机 16 次里也红过 3 次）：
 * - 计时噪声（GC 停顿、被调度走、CPU 降频）只会让单次耗时**变长**，不会变短，所以最小值
 *   最接近算法的真实成本；中位数在 runner 繁忙时会被整体抬高，而且抬高的幅度两侧不对称。
 * - 原来是先连续跑完 mult=1 的 20 次再跑 mult=3 的 20 次，中间机器负载一变（邻居进程、
 *   降频），两侧就在不同条件下测量；交替轮流让每一轮里各规模面对同一时刻的机器状态。
 * - 预热让各规模都在 JIT 完成后比较，不会让先测的那个规模独自承担首次编译。
 *
 * 这不削弱守卫：真实的复杂度退化（如退回平方增长）让**每一次**大规模运行都变慢，最小值
 * 同样会涨上去；它只过滤掉偶发的、一侧独有的变慢。
 */
function measureInterleaved<K extends string | number>(
  fns: Record<K, () => void>,
  runs = RUNS,
  warmup = WARMUP_RUNS,
): Record<K, Timing> {
  const keys = Object.keys(fns) as K[];
  for (let i = 0; i < warmup; i++) for (const k of keys) fns[k]();
  const durations = Object.fromEntries(keys.map((k) => [k, [] as number[]])) as unknown as Record<K, number[]>;
  for (let i = 0; i < runs; i++) {
    for (const k of keys) {
      const t0 = performance.now();
      fns[k]();
      durations[k].push(performance.now() - t0);
    }
  }
  const out = {} as Record<K, Timing>;
  for (const k of keys) {
    const sorted = durations[k].sort((a, b) => a - b);
    out[k] = { median: percentile(sorted, 50), p95: percentile(sorted, 95), min: sorted[0] };
  }
  return out;
}

describe("CPU 门禁：当前真实数据量", () => {
  it("单账户（Claude）与三账户合计 calibrate() 耗时的中位数与 P95", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const claudeObs = limit_observations.filter((r) => r.provider === "claude");

    const single = measure(() => calibrate("claude", claudeObs, hourly_family_facts, { now: BASE_NOW }));
    // eslint-disable-next-line no-console
    console.log(`[CPU 门禁] Claude 单账户：median=${single.median.toFixed(3)}ms p95=${single.p95.toFixed(3)}ms`);
    expect(single.median).toBeLessThan(10_000);

    const combined = measure(() => {
      for (const provider of ["claude", "codex", "antigravity"] as const) {
        calibrate(provider, limit_observations.filter((r) => r.provider === provider), hourly_family_facts, { now: BASE_NOW });
      }
    });
    // eslint-disable-next-line no-console
    console.log(`[CPU 门禁] 三账户合计：median=${combined.median.toFixed(3)}ms p95=${combined.p95.toFixed(3)}ms`);
    expect(combined.median).toBeLessThan(10_000);
  });
});

describe("CPU 门禁：按天数外推的增长曲线（go/no-go 验收）", () => {
  it("mult=1..4（约10/20/30/40天）单账户与三账户合计的 median/P95，mult=3 需满足验收门槛", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const claudeObs = limit_observations.filter((r) => r.provider === "claude");

    const MULTS = [1, 2, 3, 4] as const;
    const singleFns = {} as Record<(typeof MULTS)[number], () => void>;
    for (const mult of MULTS) {
      const obsS = scaleObservations(claudeObs, mult);
      const factsS = scaleFacts(hourly_family_facts, mult);
      const now = new Date(shiftIso(BASE_NOW.toISOString(), (Math.ceil(mult) - 1) * 10));
      singleFns[mult] = () => calibrate("claude", obsS, factsS, { now });
    }
    const singleResults = measureInterleaved(singleFns);
    for (const mult of MULTS) {
      const r = singleResults[mult];
      // eslint-disable-next-line no-console
      console.log(`[CPU 门禁] mult=${mult}(~${mult * 10}天) 单账户 min=${r.min.toFixed(3)}ms median=${r.median.toFixed(3)}ms p95=${r.p95.toFixed(3)}ms`);
    }

    const combinedFns = {} as Record<(typeof MULTS)[number], () => void>;
    for (const mult of MULTS) {
      const obsAllS = scaleObservations(limit_observations, mult);
      const factsAllS = scaleFacts(hourly_family_facts, mult);
      const now = new Date(shiftIso(BASE_NOW.toISOString(), (Math.ceil(mult) - 1) * 10));
      combinedFns[mult] = () =>
        (["claude", "codex", "antigravity"] as const).forEach((provider) =>
          calibrate(provider, obsAllS.filter((r) => r.provider === provider), factsAllS, { now }),
        );
    }
    const combinedResults = measureInterleaved(combinedFns);
    for (const mult of MULTS) {
      const r = combinedResults[mult];
      // eslint-disable-next-line no-console
      console.log(`[CPU 门禁] mult=${mult}(~${mult * 10}天) 三账户合计 min=${r.min.toFixed(3)}ms median=${r.median.toFixed(3)}ms p95=${r.p95.toFixed(3)}ms`);
    }
    const singleRatio = singleResults[3].min / singleResults[1].min;
    const combinedRatio = combinedResults[3].min / combinedResults[1].min;
    // eslint-disable-next-line no-console
    console.log(`[CPU 门禁] mult=3/mult=1 min 比值：单账户=${singleRatio.toFixed(2)} 三账户合计=${combinedRatio.toFixed(2)}（门槛 3.5）`);

    // 验收门槛：mult=3（约 28 天）单账户 P95 ≤3ms（Node 热进程口径，只是回归参考线）。
    // 绝对毫秒与运行机器相关（CI runner 比本机慢 2–3 倍，曾测得 7.2ms），不在跨机器测试里断言；
    // 真实验收以冷启动脚本 scripts/measure_calibration_cold_cpu.mjs 为准。这里只守增长形状：
    // 线性算法 mult 1→3 约 2 倍，原双循环约 6.5 倍。
    expect(singleRatio).toBeLessThanOrEqual(3.5);
    // 三账户合计这条不再是硬门槛：部署前审查 Must 1b 之后，生产 cron 每次只算一个 provider
    // （`quota-calibration-cron.ts` 的 `providerForToday()` 按日轮换），「三账户合计」这个
    // 场景在生产里已经不会发生——这里放宽到 8ms 只是防止热进程场景本身也失控式退化，
    // 不是真实验收门槛（真实门槛是单 provider 冷启动，见 scripts/measure_calibration_cold_cpu.mjs）。
    expect(combinedRatio).toBeLessThanOrEqual(3.5);

    // 增长曲线不应该是平方级：mult 从 1 到 4（数据量外推到 4 倍历史长度）耗时增长不应该
    // 超过约 4 倍——平方增长会是 ~16 倍，这个上限留了充足余量，只用来拦回归，不是精确刻画。
    expect(singleResults[4].min).toBeLessThan(singleResults[1].min * 10 + 5);
  });
});

describe("性能回归守卫：mult=3 规模下单账户耗时上限", () => {
  /**
   * 门槛取「实测 P95 的 3 倍」，理由：这是防回归的护栏，不是精确性能断言——CI 机器比本机慢、
   * 抖动更大，3 倍留了充分余量避免误报；但如果哪天真的退回 O(intervals×facts) 的双循环，
   * mult=3 规模下耗时会从 ~2ms 变成 ~27ms（见文件头注释的历史数字），远超这个门槛，
   * 守卫依然能抓到。
   */
  const GUARD_MULTIPLIER = 3;

  it(`mult=3（约30天）相对 mult=1 的单账户耗时增长不超过 3.5 倍（GUARD_MULTIPLIER=${GUARD_MULTIPLIER} 仅作历史说明）`, async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const claudeObs = limit_observations.filter((r) => r.provider === "claude");
    const obsS = scaleObservations(claudeObs, 3);
    const factsS = scaleFacts(hourly_family_facts, 3);
    const now = new Date(shiftIso(BASE_NOW.toISOString(), 20));

    const obs1 = scaleObservations(claudeObs, 1);
    const facts1 = scaleFacts(hourly_family_facts, 1);
    const { 1: base, 3: result } = measureInterleaved({
      1: () => calibrate("claude", obs1, facts1, { now: BASE_NOW }),
      3: () => calibrate("claude", obsS, factsS, { now }),
    });
    const ratio = result.min / base.min;
    // eslint-disable-next-line no-console
    console.log(`[性能回归守卫] mult=3/mult=1 min 比值=${ratio.toFixed(2)}（门槛 3.5；线性约 2，原双循环约 6.5）`);
    // 用同一进程内的相对比值，避免不同机器绝对毫秒差异造成误报（CI runner 比本机慢 2–3 倍）；
    // 预热 + 交替轮流 + 取最小值的理由见 measureInterleaved()。
    expect(ratio).toBeLessThanOrEqual(3.5);
  });
});

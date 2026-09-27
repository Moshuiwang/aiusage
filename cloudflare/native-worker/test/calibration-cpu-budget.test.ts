/**
 * #183-a：CPU 门禁（go/no-go）。
 *
 * Cloudflare Free 计划每次调用 CPU 时间预算约 10ms（#183 设计 v1 §4）。这里用真实
 * fixture 全量（三个 provider）跑完整计算，测量多次取中位数与 P95，估算「28 天、3 个账户」
 * 规模下单次 cron 调用是否会超标。这不是拟合正确性测试，是性能护栏——数字本身就是产物，
 * 写进收口报告里给 #183-b 做 cron 接线方式的依据（一次算三个账户 vs 分账户轮转）。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { calibrate } from "../src/calibration/index";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration/types";

const FIXTURE_PATH = new URL("./calibration_fixture.json", import.meta.url);
const NOW = new Date("2026-09-27T10:00:00Z");
const RUNS = 30;

async function loadFixture(): Promise<{ limit_observations: LimitObservation[]; hourly_family_facts: HourlyFamilyFact[] }> {
  const raw = await readFile(FIXTURE_PATH, "utf8");
  return JSON.parse(raw);
}

function percentile(sorted: number[], p: number): number {
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, idx)];
}

describe("CPU 门禁", () => {
  it("单账户（Claude，本 fixture 里数据量最大的账户）单次 calibrate() 耗时的中位数与 P95", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const claudeObs = limit_observations.filter((r) => r.provider === "claude");
    const durations: number[] = [];
    for (let i = 0; i < RUNS; i++) {
      const t0 = performance.now();
      calibrate("claude", claudeObs, hourly_family_facts, { now: NOW });
      durations.push(performance.now() - t0);
    }
    durations.sort((a, b) => a - b);
    const median = percentile(durations, 50);
    const p95 = percentile(durations, 95);
    // eslint-disable-next-line no-console
    console.log(`[CPU 门禁] Claude 单账户 calibrate()：median=${median.toFixed(3)}ms p95=${p95.toFixed(3)}ms (n=${RUNS})`);
    // 记录数字本身就是交付物；这里只做一个宽松的健全性上限（10 秒），真正的判断在收口报告里手动写。
    expect(median).toBeLessThan(10_000);
  });

  it("三个 provider 各跑一次 calibrate()（模拟单次 cron 调用同时算三个账户）的总耗时", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const durations: number[] = [];
    for (let i = 0; i < RUNS; i++) {
      const t0 = performance.now();
      for (const provider of ["claude", "codex", "antigravity"] as const) {
        calibrate(provider, limit_observations.filter((r) => r.provider === provider), hourly_family_facts, { now: NOW });
      }
      durations.push(performance.now() - t0);
    }
    durations.sort((a, b) => a - b);
    const median = percentile(durations, 50);
    const p95 = percentile(durations, 95);
    // eslint-disable-next-line no-console
    console.log(`[CPU 门禁] 三账户合计 calibrate()：median=${median.toFixed(3)}ms p95=${p95.toFixed(3)}ms (n=${RUNS})`);
    expect(median).toBeLessThan(10_000);
  });
});

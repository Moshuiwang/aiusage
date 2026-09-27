/**
 * `measure_calibration_cold_cpu.mjs` 的单次冷启动子进程。每次调用都是一个全新的 node
 * 进程：导入 calibration 模块、构造 3×规模的数据（跟 `test/calibration-cpu-budget.test.ts`
 * 的 mult=3 同一套平移复制方法，量级可比）、只调用一次 `calibrate()`，打印耗时（毫秒），
 * 退出。不做循环——循环会让 JIT 在同一进程里预热，测不出「新鲜 isolate」的真实开销。
 */
import { readFileSync } from "node:fs";
import { calibrate } from "../src/calibration/index.ts";

const provider = process.argv[2];
const fixturePath = process.argv[3];
if (!["claude", "codex", "antigravity"].includes(provider)) {
  throw new Error(`未知 provider: ${provider}`);
}
if (!fixturePath) {
  throw new Error("缺少 fixture 路径参数——esbuild 打包后 import.meta.url 指向临时目录，"
    + "fixture 路径必须由父进程按源码位置传入，不能在这个文件里自己算。");
}
const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));

const BASE_NOW = new Date("2026-09-27T10:00:00Z");
const MULT = 3;
const SHIFT_DAYS_PER_COPY = 10;

function shiftIso(iso, days) {
  return new Date(Date.parse(iso) + days * 86400000).toISOString();
}

function scaleObservations(rows) {
  const out = [];
  for (let c = 0; c < MULT; c++) {
    const shiftDays = c * SHIFT_DAYS_PER_COPY;
    for (const r of rows) out.push({ ...r, observed_at: shiftIso(r.observed_at, shiftDays), reset_at: shiftIso(r.reset_at, shiftDays) });
  }
  return out;
}

function scaleFacts(rows) {
  const out = [];
  for (let c = 0; c < MULT; c++) {
    const shiftDays = c * SHIFT_DAYS_PER_COPY;
    for (const f of rows) out.push({ ...f, window_start: shiftIso(f.window_start, shiftDays), window_end: shiftIso(f.window_end, shiftDays) });
  }
  return out;
}

const observations = scaleObservations(fixture.limit_observations.filter((r) => r.provider === provider));
const facts = scaleFacts(fixture.hourly_family_facts);
const now = new Date(shiftIso(BASE_NOW.toISOString(), (MULT - 1) * SHIFT_DAYS_PER_COPY));

const t0 = performance.now();
calibrate(provider, observations, facts, { now });
const elapsedMs = performance.now() - t0;

// 只打印这一个数字：父进程解析 stdout。
process.stdout.write(String(elapsedMs));

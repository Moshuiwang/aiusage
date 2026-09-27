#!/usr/bin/env node
/**
 * #183-b 部署前审查（Must 1c）：冷启动 CPU 测量。
 *
 * `test/calibration-cpu-budget.test.ts` 用同一个热进程反复跑 `calibrate()`，测出来的
 * P95（~2.2ms）会低估真实开销——workerd 每次 cron/请求调用可能是一个新鲜（或长时间空闲
 * 复用）的 isolate，JIT 没机会预热。部署前审查用单次新进程冷跑复现，28 天规模三账户
 * 合计测到 10.26–10.40ms，超过 Cloudflare Free 单次调用 10ms 的 CPU 预算——这正是
 * Must 1 要求「每次 cron 只算一个 provider」的依据。
 *
 * 这个脚本按 provider 单独测冷启动耗时：先用 esbuild 把子脚本（导入 calibration 模块、
 * 构造 3× 规模数据、调一次 `calibrate()`）**打包成纯 JS 一次**（打包本身不计入测量——
 * workerd 部署的也是预打包好的 JS，不会在请求时现场转译 TS），然后对同一份打包产物
 * 反复用全新 `node` 进程跑（每次测量都是一次新的进程，不是同一进程里循环——循环会让
 * V8 JIT 在同一进程里预热，测不出"新鲜 isolate"的真实开销）。
 *
 * 用法：
 *   node scripts/measure_calibration_cold_cpu.mjs [N]   # N 默认 7，每个 provider 跑 N 次冷启动
 *
 * 验收：单 provider 冷启动最大值 ≤5ms（比部署前审查测到的 10ms+ 留了给「D1 反序列化等
 * 额外开销」的余量——这个脚本只测纯计算，不含 D1 I/O）。
 */
import { execFileSync } from "node:child_process";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { build } from "esbuild";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const childSourcePath = path.join(scriptDir, "_cold_cpu_child.mjs");
const fixturePath = path.join(scriptDir, "..", "test", "calibration_fixture.json");

const PROVIDERS = ["claude", "codex", "antigravity"];
const RUNS = Number(process.argv[2] ?? 7);
const BUDGET_MS = 5;

function percentile(sorted, p) {
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, idx)];
}

async function bundleChild() {
  const outDir = mkdtempSync(path.join(tmpdir(), "aiusage-cold-cpu-"));
  const outfile = path.join(outDir, "child.mjs");
  await build({
    entryPoints: [childSourcePath],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "es2022",
    sourcemap: false,
  });
  return { outfile, outDir };
}

function measureColdRun(bundlePath, provider) {
  const out = execFileSync("node", [bundlePath, provider, fixturePath], { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  const ms = Number(out.trim());
  if (!Number.isFinite(ms)) throw new Error(`子进程没有打印可解析的耗时，原始输出：${JSON.stringify(out)}`);
  return ms;
}

async function main() {
  const { outfile, outDir } = await bundleChild();
  try {
    const results = {};
    let overallMax = -Infinity;

    for (const provider of PROVIDERS) {
      const durations = [];
      for (let i = 0; i < RUNS; i++) durations.push(measureColdRun(outfile, provider));
      durations.sort((a, b) => a - b);
      const median = percentile(durations, 50);
      const max = durations[durations.length - 1];
      results[provider] = { median, max, all: durations };
      overallMax = Math.max(overallMax, max);
      console.log(
        `[冷启动] ${provider}: median=${median.toFixed(3)}ms max=${max.toFixed(3)}ms `
        + `全部=[${durations.map((d) => d.toFixed(3)).join(", ")}]`,
      );
    }

    console.log(`[冷启动] 三个 provider 里的最大值 = ${overallMax.toFixed(3)}ms（验收门槛 ≤${BUDGET_MS}ms）`);
    if (overallMax > BUDGET_MS) {
      console.error(`FAIL: 冷启动最大值 ${overallMax.toFixed(3)}ms 超过 ${BUDGET_MS}ms 门槛`);
      process.exitCode = 1;
    } else {
      console.log("PASS");
    }
  } finally {
    rmSync(outDir, { recursive: true, force: true });
  }
}

await main();

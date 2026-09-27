/**
 * #183-b 部署前审查（Should 3）：`scheduled()` 每日分支里，额度校准失败不能拖垮它前面
 * 已经跑完的维护步骤，也不能把异常原样丢出去（只应该走 `console.error` 记录）。
 *
 * ## 一处诊断，改了测试设计：Miniflare 的 `worker.scheduled()` 本身就不会把处理器内部
 * 抛出的异常转成 rejected promise
 *
 * 一开始想用 `await expect(runScheduled(...)).resolves.toBeUndefined()` 当核心断言，
 * 诊断后发现这是个恒真断言：往 `scheduled()` 最开头加一个无条件 `throw new Error(...)`
 * （诊断用，已还原），这条 `resolves` 断言依然通过——`worker.scheduled()` 不会把处理器里
 * 抛出的异常转成 rejected promise 传回调用方（跟真实 Workers Runtime 对 scheduled 触发器
 * 的语义一致：没有"响应"概念，异常只会被记录/上报，不会让触发这次调用的谁得到一个
 * rejection）。所以这条断言测不出任何东西，换成两条真正会随 try/catch 存在与否变化的：
 *
 * 1. 单元级：直接调 `runQuotaCalibration()`（不经过 `worker.scheduled()` 那层会吞异常的
 *    包装）——这是一个普通 async 函数，它内部的 try/catch 存在与否，直接决定这个
 *    promise 是 resolve 还是 reject，是真正会随变异变化的断言。
 * 2. 集成级：用 `console.error` 的 spy 核实 `scheduled()` 走过了「记录错误」这条路径
 *    （不是走别的、我们没写的兜底路径）；再核实它之前的维护步骤（审计清理）确实生效了。
 */
import { Miniflare } from "miniflare";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applySchema, bundleWorker } from "./golden/harness";
import { fixedNow, timezone, token } from "./golden/paths";
import { runQuotaCalibration } from "../src/quota-calibration-cron";

const DAILY_CRON = "17 19 * * *"; // 跟 MONTHLY_BACKUP_CRON（"23 18 1 * *"）不同，落进每日分支

async function createIsolatedMiniflare(): Promise<Miniflare> {
  const script = await bundleWorker();
  return new Miniflare({
    modules: true,
    script,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_TIMEZONE: timezone,
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
    },
  });
}

async function runScheduled(mf: Miniflare, scheduledTime: string): Promise<void> {
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: DAILY_CRON, scheduledTime: new Date(scheduledTime).getTime() });
}

describe("runQuotaCalibration：单元级——表被破坏时这个函数本身不抛", () => {
  it("quota_calibration 表 DROP 掉之后直接调用仍然 resolve（不是靠 scheduled() 那层吞异常）", async () => {
    const mf = await createIsolatedMiniflare();
    try {
      const db = await mf.getD1Database("AIUSAGE_DB");
      await applySchema(db);
      await db.prepare("DROP TABLE quota_calibration").run();

      await expect(runQuotaCalibration(db, new Date(fixedNow))).resolves.toBeUndefined();
    } finally {
      await mf.dispose();
    }
  });
});

describe("scheduled() 每日分支：额度校准失败走 console.error，不拖垮它之前的审计清理", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("quota_calibration 表被破坏（DROP TABLE）时：console.error 记录了这次失败，且审计清理已经生效", async () => {
    const mf = await createIsolatedMiniflare();
    try {
      const db = await mf.getD1Database("AIUSAGE_DB");
      await applySchema(db);

      const scheduledTime = "2026-06-10T03:17:00+08:00";
      const staleCollectedAt = "2026-05-25T00:00:00Z"; // 距 scheduledTime 超过 7 天审计保留期

      await db.prepare(`
        INSERT INTO collection_runs (collected_at, timezone, collector_version, status)
        VALUES (?, ?, NULL, 'ok')
      `).bind(staleCollectedAt, timezone).run();
      const before = await db.prepare("SELECT COUNT(*) AS c FROM collection_runs WHERE collected_at = ?")
        .bind(staleCollectedAt).first<{ c: number }>();
      expect(Number(before?.c)).toBe(1); // 结构下限：先确认真的插进去了，不是空转

      await db.prepare("DROP TABLE quota_calibration").run();

      const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      await runScheduled(mf, scheduledTime);

      // 走了 console.error 这条路径（不是别的兜底、也不是异常真的没被处理就默默消失在
      // workerd 内部）——直接核实调用参数，不是只看"有没有报错"。
      expect(errorSpy).toHaveBeenCalled();
      const loggedMessages = errorSpy.mock.calls.map((call) => String(call[0]));
      expect(loggedMessages.some((msg) => /quota calibration failed/i.test(msg))).toBe(true);

      // 校准失败没有拖垮它之前已经跑完的审计清理：过期的 collection_runs 行已经被删了。
      const after = await db.prepare("SELECT COUNT(*) AS c FROM collection_runs WHERE collected_at = ?")
        .bind(staleCollectedAt).first<{ c: number }>();
      expect(Number(after?.c)).toBe(0);
    } finally {
      await mf.dispose();
    }
  });
});

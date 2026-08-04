/**
 * #101：共享实例池的统一收尾。
 *
 * vitest 对每个测试文件都会加载本 setup：文件跑完把池里的 Miniflare 全部释放。
 * 不这么做的话，任何一个「用了池却忘写 afterAll」的文件都会让 workerd 子进程
 * 挂着不退，vitest 收不了尾——把清理写成全局约定，这一类漏洞就不存在了。
 *
 * harness 必须动态 import：顶层 import 会让 16 个文件每个都白付一次 miniflare
 * 的加载（实测约 0.8s/文件），而多数文件根本不碰池。`__aiusageWorkerPoolUsed`
 * 由 acquireWorker 打标，没用过池的文件在这里一行 miniflare 都不加载。
 */

import { afterAll } from "vitest";

afterAll(async () => {
  if (!(globalThis as Record<string, unknown>).__aiusageWorkerPoolUsed) return;
  const { disposeWorkers } = await import("./golden/harness");
  await disposeWorkers();
});

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["cloudflare/native-worker/test/**/*.test.ts"],
    // #101：共享实例池的统一收尾，每个测试文件跑完自动释放池里的 Miniflare。
    setupFiles: ["cloudflare/native-worker/test/setup.dispose-workers.ts"],
    // 两个文件并行：压缩串行等待，同时把 workerd 进程与内存上限钉住。
    fileParallelism: true,
    maxWorkers: 2,
    testTimeout: 30000,
  },
});

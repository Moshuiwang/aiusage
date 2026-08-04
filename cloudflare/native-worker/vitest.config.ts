import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["cloudflare/native-worker/test/**/*.test.ts"],
    // #101：共享实例池的统一收尾，每个测试文件跑完自动释放池里的 Miniflare。
    setupFiles: ["cloudflare/native-worker/test/setup.dispose-workers.ts"],
    fileParallelism: false,
    testTimeout: 30000,
  },
});

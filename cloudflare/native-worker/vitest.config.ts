import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["cloudflare/native-worker/test/**/*.test.ts"],
    fileParallelism: false,
    testTimeout: 30000,
  },
});

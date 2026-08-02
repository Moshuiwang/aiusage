#!/usr/bin/env node
/**
 * #74 P1：`npm run cf:golden:gen` 的入口。
 *
 * 生成逻辑全部在 `cloudflare/native-worker/test/golden/`（TypeScript）。这里只做一件事：
 * 用仓库里已有的 esbuild 把那份 TS 打包成一个可以被 node 直接 import 的 mjs，跑完删掉。
 *
 * 打包产物**刻意落在 `test/golden/` 目录内**：`paths.ts` 用 `import.meta.url` 往上数四层
 * 得到仓库根，打到别处（比如 /tmp）会让所有 golden 路径算错，然后静默写到不存在的地方。
 */

import { build } from "esbuild";
import { rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const goldenDir = path.join(repoRoot, "cloudflare/native-worker/test/golden");
const outfile = path.join(goldenDir, ".gen-entry.mjs");

await build({
  entryPoints: [path.join(goldenDir, "generate.ts")],
  outfile,
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node22",
  // miniflare / esbuild 自身留给 node 在运行时解析，不要打进产物。
  packages: "external",
});

try {
  const { generateGoldens } = await import(pathToFileURL(outfile).href);
  await generateGoldens();
} finally {
  await rm(outfile, { force: true });
}

import { build } from "esbuild";
import { rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outfile = path.join(root, "cloudflare/native-worker/test/golden/.navigation-entry.mjs");
await build({
  stdin: { contents: 'export { collectNavigationModels } from "./navigation-models"; export { disposeWorkers } from "./harness";',
    resolveDir: path.dirname(outfile), loader: "ts" },
  outfile, bundle: true, format: "esm", platform: "node", target: "node22", packages: "external",
});
const entry = await import(pathToFileURL(outfile).href);
try {
  const summary = await entry.collectNavigationModels();
  const destination = process.argv[2] ?? path.join(root, "tests/fixtures/navigation-models-owner.json");
  await writeFile(destination, JSON.stringify(summary, null, 2) + "\n");
  console.log(`wrote owner summary: ${summary.breakdown.by_source.length} sources, ${summary.period.total_tokens} tokens`);
} finally {
  await entry.disposeWorkers();
  await rm(outfile, { force: true });
}

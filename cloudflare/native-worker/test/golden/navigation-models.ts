import { execFileSync } from "node:child_process";
import path from "node:path";
import { withWorker } from "./harness";
import { repoRoot } from "./paths";

export function collectModelPayloads(day = "2026-09-22") {
  return JSON.parse(execFileSync("python3", [path.join(repoRoot, "tests/model_wire_scenario.py"), day], {
    cwd: repoRoot, env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src") }, encoding: "utf8",
  }));
}

export async function collectNavigationModels() {
  const payloads = collectModelPayloads();
  return withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ fetchRaw }) => {
    for (const payload of payloads) {
      const response = await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload });
      if (response.status !== 200) throw new Error(`Owner payload rejected: ${response.body}`);
    }
    const response = await fetchRaw({ method: "GET", path: "/api/mobile/summary?period=today&offset=0", auth: true });
    if (response.status !== 200) throw new Error(`Owner summary failed: ${response.status}`);
    return JSON.parse(response.body.toString());
  });
}

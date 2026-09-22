import { describe, expect, it } from "vitest";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { buildMobileSummary } from "../src/mobile-summary";
import { sourceAgents } from "../src/source-breakdown";
import type { SummarySnapshot } from "../src/read-model/shared";
import { withWorker } from "./golden/harness";
import { collectModelPayloads, collectNavigationModels } from "./golden/navigation-models";
import { repoRoot } from "./golden/paths";

describe.sequential("calendar history navigation", () => {
  it("selects actual facts within calendar boundaries and keeps sources and models in the same period", async () => {
    await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ fetchRaw, db }) => {
      for (const day of ["2026-08-31", "2026-09-14", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23"]) {
        for (const payload of collectModelPayloads(day)) {
          const response = await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload });
          expect(response.status).toBe(200);
        }
      }
      expect(await db.prepare("SELECT count(*) AS n FROM usage_hourly_facts").first("n")).toBe(18);
      for (const [period, offset, expected] of [["today", -1, 1000], ["week", 0, 2000], ["week", -1, 2000], ["month", 0, 4000], ["month", -1, 1000]] as const) {
        for (const endpoint of ["/api/summary", "/api/mobile/summary"]) {
          const response = await fetchRaw({ method: "GET", path: `${endpoint}?period=${period}&offset=${offset}`, auth: true });
          expect(response.status).toBe(200);
          const body = JSON.parse(response.body.toString());
          expect((body.period ?? body.summary).total_tokens).toBe(expected);
          if (body.breakdown) {
            expect(body.breakdown.by_source).toHaveLength(2);
            expect(body.breakdown.by_source.reduce((n: number, row: any) => n + row.tokens, 0)).toBe(expected);
            expect(body.breakdown.by_source.flatMap((r: any) => r.agents).flatMap((a: any) => a.models)
              .reduce((n: number, m: any) => n + m.tokens, 0)).toBe(expected);
          }
        }
      }
    });
  });
  it("handles leap February, year boundaries and Shanghai midnight", async () => {
    for (const [now, period, offset, start, end] of [
      ["2024-03-01T00:01:00+08:00", "month", -1, "2024-02-01", "2024-02-29"],
      ["2026-01-01T00:01:00+08:00", "month", -1, "2025-12-01", "2025-12-31"],
      ["2026-01-01T00:01:00+08:00", "week", 0, "2025-12-29", "2026-01-01"],
      ["2026-09-21T16:01:00Z", "today", -1, "2026-09-21", "2026-09-21"],
    ] as const) {
      await withWorker({ now }, async ({ fetchRaw }) => {
        const response = await fetchRaw({ method: "GET", path: `/api/mobile/summary?period=${period}&offset=${offset}`, auth: true });
        expect(response.status).toBe(200);
        expect(JSON.parse(response.body.toString()).period).toMatchObject({ date: end, start_date: start, end_date: end });
      });
    }
  });
  for (const [period, offset, start, end] of [
    ["today", 0, "2026-09-22", "2026-09-22"],
    ["today", -6, "2026-09-16", "2026-09-16"],
    ["week", 0, "2026-09-21", "2026-09-22"],
    ["week", -1, "2026-09-14", "2026-09-20"],
    ["month", 0, "2026-09-01", "2026-09-22"],
    ["month", -1, "2026-08-01", "2026-08-31"],
    ["month", -7, "2026-02-01", "2026-02-28"],
  ] as const) {
    it(`${period} ${offset} returns the complete selected calendar period`, async () => {
      await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ fetchRaw }) => {
        for (const path of ["/api/summary", "/api/mobile/summary"]) {
          const response = await fetchRaw({ method: "GET", path: `${path}?period=${period}&offset=${offset}`, auth: true });
          expect(response.status).toBe(200);
          const body = JSON.parse(response.body.toString());
          const value = body.period ?? body.summary;
          expect(value).toMatchObject({ date: end, start_date: start, end_date: end, total_tokens: 0 });
        }
      });
    });
  }
  it("rejects future, out-of-seven-day, fractional and invalid offsets", async () => {
    await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ fetchRaw }) => {
      const queries = ["period=today&offset=1", "period=today&offset=-7", "period=week&offset=-0.5", "period=month&offset=bad", "period=all&offset=0"];
      let checked = 0;
      for (const query of queries) {
        const response = await fetchRaw({ method: "GET", path: `/api/mobile/summary?${query}`, auth: true });
        expect(response.status, query).toBe(400);
        checked++;
      }
      expect(checked).toBe(5);
    });
  });
});

describe("source Agent model hierarchy", () => {
  it("marks inconsistent model allocation unknown without inflating the source total", () => {
    const rows = sourceAgents([{ agent: "codex", total_tokens: 100,
      model_breakdowns: [{ model_name: "sol", total_tokens: 80 }, { model_name: "luna", total_tokens: 70 }] }]);
    expect(rows).toHaveLength(2);
    expect(rows.find(row => row.id === "codex")).toEqual({
      id: "codex", label: "Codex", tokens: 100, status: "available",
      models: [{ id: "unknown", label: "模型未知", tokens: 100, status: "missing" }],
    });
    expect(rows.flatMap(row => row.models).reduce((sum, row) => sum + row.tokens, 0)).toBe(100);
  });
  it("regenerates the collector to Worker to display contract with nonempty model allocation", async () => {
    const actual = await collectNavigationModels();
    expect(actual.period.total_tokens).toBe(1000);
    expect(actual.breakdown.by_source).toHaveLength(2);
    let models = 0;
    for (const source of actual.breakdown.by_source) {
      expect(source.agents).toHaveLength(2);
      expect(source.agents.reduce((n: number, a: any) => n + a.tokens, 0)).toBe(source.tokens);
      for (const agent of source.agents) {
        models += agent.models.length;
        expect(agent.models.reduce((n: number, m: any) => n + m.tokens, 0)).toBe(agent.tokens);
      }
    }
    expect(models).toBe(7);
    for (const file of [
      "tests/fixtures/navigation-models-owner.json",
      "clients/macos/Tests/AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json",
      "mobile/ios/Tests/AIUsageMobileCoreTests/Fixtures/navigation-models-owner.json",
    ]) {
      expect(actual, file).toEqual(JSON.parse(await readFile(path.join(repoRoot, file), "utf8")));
    }
  });
  it("keeps source identities separate and independently conserves every nested sum", () => {
    const snapshot = {
      generated_at: "2026-09-22T12:00:00+08:00", timezone: "Asia/Shanghai",
      summary: { date: "2026-09-22", period: "today", total_tokens: 400 }, trend: { points: [] },
      source_status: [
        { source_id: "a", machine: "mac", os_user: "alice" },
        { source_id: "b", machine: "linux", os_user: "alice" },
      ], groups: {}, limits: [],
      items: [
        { source_id: "a", machine: "mac", account: "alice", agent: "codex", total_tokens: 150,
          model_breakdowns: [{ model_name: "sol", total_tokens: 100 }] },
        { source_id: "a", machine: "mac", account: "alice", agent: "claude", total_tokens: 200,
          model_breakdowns: [{ model_name: "opus", total_tokens: 200 }] },
        { source_id: "b", machine: "linux", account: "alice", agent: "codex", total_tokens: 50, model_breakdowns: [] },
      ],
    } as unknown as SummarySnapshot;
    const mobile = buildMobileSummary(snapshot);
    const rows = mobile.breakdown.by_source as Array<Record<string, any>>;
    expect(rows).toHaveLength(2);
    expect(rows.map(row => row.id).sort()).toEqual(["a", "b"]);
    expect(rows.reduce((sum, row) => sum + row.tokens, 0)).toBe(400);
    for (const row of rows) {
      expect(row.agents).toHaveLength(2);
      expect(row.agents.reduce((sum: number, a: any) => sum + a.tokens, 0)).toBe(row.tokens);
      for (const agent of row.agents) {
        expect(agent.models.reduce((sum: number, m: any) => sum + m.tokens, 0)).toBe(agent.tokens);
      }
    }
    const a = rows.find(row => row.id === "a")!;
    expect(a.agents.find((v: any) => v.id === "codex").models).toEqual([
      { id: "sol", label: "sol", tokens: 100, status: "available" },
      { id: "unknown", label: "模型未知", tokens: 50, status: "missing" },
    ]);
    const b = rows.find(row => row.id === "b")!;
    expect(b.agents.find((v: any) => v.id === "claude")).toMatchObject({ status: "missing", tokens: 0, models: [] });
    expect(b.agents.find((v: any) => v.id === "codex").models).toEqual([
      { id: "unknown", label: "模型未知", tokens: 50, status: "missing" },
    ]);
  });
});

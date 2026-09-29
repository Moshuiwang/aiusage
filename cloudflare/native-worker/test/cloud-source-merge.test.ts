import { describe, expect, it } from "vitest";

import { buildMobileSummary as buildMobileSummaryTyped } from "../src/mobile-summary";
import type { SummarySnapshot } from "../src/read-model/shared";

const build = (snapshot: Record<string, unknown>) =>
  buildMobileSummaryTyped(snapshot as unknown as SummarySnapshot) as Record<string, any>;

// #210：fixture 里的数字是手写字面量，期望值在测试里从这些字面量独立求和，不调用被测代码。
const cloudRow = (sessionId: string, date: string, agent: string, total: number, models: [string, number][]) => ({
  source_id: `claude-cloud-${sessionId}`, machine: "claude-cloud", account: "claude-cloud",
  date, agent, total_tokens: total,
  model_breakdowns: models.map(([model_name, total_tokens]) => ({ model_name, total_tokens })),
});
const laptop = { source_id: "mac-air-wang", machine: "mac-air", account: "wang", date: "2026-07-18", agent: "claude", total_tokens: 700,
  model_breakdowns: [{ model_name: "claude-opus", total_tokens: 700 }] };
const items = [
  cloudRow("s1", "2026-07-18", "claude", 100, [["claude-opus", 60], ["claude-sonnet", 40]]),
  cloudRow("s2", "2026-07-18", "claude", 200, [["claude-opus", 200]]),
  cloudRow("s3", "2026-07-17", "claude", 30, [["claude-sonnet", 30]]),
  laptop,
  // 前缀相似但不是云端会话：不得被吞
  { ...laptop, source_id: "my-claude-cloud-box", machine: "box", account: "u", total_tokens: 5, model_breakdowns: [] },
  { ...laptop, source_id: "claude-cloudy", machine: "cloudy", account: "u", total_tokens: 7, model_breakdowns: [] },
];
const statusRow = (id: string, observed: string, status: string) => ({
  source_id: id, status, observed_at: observed, machine: id.startsWith("claude-cloud-") ? "claude-cloud" : id, os_user: "claude-cloud",
  display_name: `${id} · x`, accuracy: { status: "unknown", agents: [] },
});
const snapshot = {
  generated_at: "2026-07-18T10:30:00+08:00", timezone: "Asia/Shanghai",
  summary: { period: "week", total_tokens: 1042 }, trend: { points: [] }, limits: [],
  source_status: [
    statusRow("claude-cloud-s1", "2026-07-18T09:00:00+08:00", "ok"),
    statusRow("claude-cloud-s2", "2026-07-18T10:00:00+08:00", "ok"),
    statusRow("claude-cloud-s3", "2026-07-17T09:00:00+08:00", "ok"),
    statusRow("mac-air-wang", "2026-07-18T10:10:00+08:00", "ok"),
  ],
  groups: { by_machine: [
    { name: "claude-cloud", display_name: "claude-cloud", total_tokens: 330,
      source_ids: ["claude-cloud-s1", "claude-cloud-s2", "claude-cloud-s3"],
      users: [{ account: "claude-cloud", machine: "claude-cloud", total_tokens: 330, source_ids: ["claude-cloud-s1", "claude-cloud-s2", "claude-cloud-s3"] }] },
    { name: "mac-air", display_name: "mac-air", total_tokens: 700, source_ids: ["mac-air-wang"],
      users: [{ account: "wang", machine: "mac-air", total_tokens: 700, source_ids: ["mac-air-wang"] }] },
  ] },
  items,
};

describe("#210 云端会话来源合并", () => {
  it("by_source 只有一条云端来源，合计与按模型明细等于 fixture 手算之和", () => {
    const mobile = build(snapshot);
    const bySource = mobile.breakdown.by_source as any[];
    const cloud = bySource.filter((row) => String(row.id).startsWith("claude-cloud-") || row.id === "claude-cloud");
    // 结构下限：4 条来源（云端 + mac + 两个前缀相似的非云端），云端恰好 1 条
    expect(bySource).toHaveLength(4);
    expect(cloud).toHaveLength(1);
    expect(cloud[0].id).toBe("claude-cloud");
    expect(cloud[0].label).toBe("云端");
    expect(cloud[0].source_ids).toEqual(["claude-cloud"]);
    expect(cloud[0].tokens).toBe(100 + 200 + 30);
    expect(cloud[0].contributions).toEqual([{ source_id: "claude-cloud", tokens: 330 }]);
    const claude = cloud[0].agents.find((a: any) => a.id === "claude");
    expect(claude.tokens).toBe(330);
    const models = Object.fromEntries(claude.models.map((m: any) => [m.id, m.tokens]));
    expect(models).toEqual({ "claude-opus": 60 + 200, "claude-sonnet": 40 + 30 });
    // 非云端不受影响
    expect(bySource.map((r) => r.id).sort()).toEqual(["claude-cloud", "claude-cloudy", "mac-air-wang", "my-claude-cloud-box"]);
    expect(bySource.find((r) => r.id === "mac-air-wang")!.tokens).toBe(700);
    expect(bySource.find((r) => r.id === "claude-cloudy")!.tokens).toBe(7);
  });

  it("sources 列表合并成一条，显示名「云端」，取最新一次上报", () => {
    const mobile = build(snapshot);
    const sources = mobile.sources as any[];
    expect(sources).toHaveLength(2);
    const cloud = sources.filter((row) => String(row.source_id).startsWith("claude-cloud"));
    expect(cloud).toHaveLength(1);
    expect(cloud[0]).toMatchObject({ source_id: "claude-cloud", display_name: "云端", last_observed_at: "2026-07-18T10:00:00+08:00" });
    expect(sources.find((r) => r.source_id === "mac-air-wang")).toBeTruthy();
  });

  it("by_machine / by_agent / by_date / by_model 的来源引用同步归并，总量不变", () => {
    const mobile = build(snapshot);
    const byMachine = mobile.breakdown.by_machine as any[];
    const cloudMachine = byMachine.find((r) => r.id === "claude-cloud");
    expect(cloudMachine.tokens).toBe(330);
    expect(cloudMachine.source_ids).toEqual(["claude-cloud"]);
    expect(cloudMachine.contributions).toEqual([{ source_id: "claude-cloud", tokens: 330 }]);
    // 其它口径的总量：从 fixture 手算 100+200+30+700+5+7
    const sum = (rows: any[]) => rows.reduce((s, r) => s + r.tokens, 0);
    expect(sum(mobile.breakdown.by_agent)).toBe(1042);
    expect(sum(mobile.breakdown.by_date)).toBe(1042);
    for (const row of [...mobile.breakdown.by_agent, ...mobile.breakdown.by_date, ...mobile.breakdown.by_model]) {
      const ids = row.source_ids as string[];
      expect(ids.filter((id) => id.startsWith("claude-cloud-"))).toEqual([]);
    }
  });
});

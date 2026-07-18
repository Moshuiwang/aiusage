import { describe, expect, it } from "vitest";

import { buildMobileSummary } from "../src/mobile-summary";

describe("mobile trend agent classification", () => {
  it("groups gpt agents into Codex while preserving every point total", () => {
    const mobile = buildMobileSummary({
      generated_at: "2026-07-18T10:30:00+08:00",
      timezone: "Asia/Shanghai",
      summary: { period: "week", total_tokens: 600 },
      trend: {
        period: "week",
        granularity: "day",
        points: [{ date: "2026-07-18", total_tokens: 600 }],
        by_agent: [
          { agent: "claude", values: [300] },
          { agent: "gpt-5", values: [200] },
        ],
      },
      source_status: [],
      groups: {},
      items: [],
      limits: [],
    }) as Record<string, any>;

    expect(mobile.trend.points[0]).toMatchObject({
      tokens: 600,
      claude_tokens: 300,
      codex_tokens: 200,
      unknown_tokens: 100,
    });
  });
});

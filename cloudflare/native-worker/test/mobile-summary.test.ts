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

describe("mobile official limits freshness", () => {
  it("keeps safe stale provider identity without exposing old percentages", () => {
    const mobile = buildMobileSummary({
      generated_at: "2026-07-18T12:30:00+08:00", summary: { period: "today", total_tokens: 0 },
      trend: { points: [] }, source_status: [], groups: {}, items: [], limits: [],
      limit_status: [{ provider: "claude", source_id: "linux-biai-wangzhipeng", observed_at: "2026-07-18T10:00:00+08:00", source_type: "oauth_usage_api", status: "stale" }],
    }) as Record<string, any>;
    expect(mobile.limits.windows).toEqual([]);
    expect(mobile.limits.providers).toEqual([{ provider: "claude", source_id: "linux-biai-wangzhipeng", observed_at: "2026-07-18T10:00:00+08:00", source_type: "oauth_usage_api", status: "stale" }]);
  });

  it("never combines quota windows from different sources", () => {
    const common = { provider: "claude", remaining_percent: 80, reset_at: "2026-07-20T00:00:00+08:00", source_type: "oauth_usage_api", confidence: "observed", status: "ok", official: true };
    const mobile = buildMobileSummary({
      generated_at: "2026-07-18T10:30:00+08:00", summary: { period: "today", total_tokens: 0 },
      trend: { points: [] }, source_status: [], groups: {}, items: [],
      limit_status: [{ provider: "claude", source_id: "source-b", observed_at: "2026-07-18T10:20:00+08:00", source_type: "oauth_usage_api", status: "ok" }],
      limits: [
        { ...common, source_id: "source-a", window: "session", used_percent: 10, window_duration_minutes: 300, observed_at: "2026-07-18T10:10:00+08:00" },
        { ...common, source_id: "source-b", window: "week", used_percent: 20, window_duration_minutes: 10080, observed_at: "2026-07-18T10:20:00+08:00" },
      ],
    }) as Record<string, any>;
    expect(new Set(mobile.limits.windows.map((row: any) => row.source_id))).toEqual(new Set(["source-b"]));
  });

  it("hides previous percentages immediately after an explicit provider failure", () => {
    const mobile = buildMobileSummary({
      generated_at: "2026-07-18T10:31:00+08:00", summary: { period: "today", total_tokens: 0 },
      trend: { points: [] }, source_status: [], groups: {}, items: [],
      limit_status: [{ provider: "claude", source_id: "linux-biai-wangzhipeng", observed_at: "2026-07-18T10:00:00+08:00", source_type: "oauth_usage_api", status: "unavailable" }],
      limits: [{ source_id: "linux-biai-wangzhipeng", provider: "claude", window: "session", used_percent: 76, remaining_percent: 24, reset_at: "2026-07-18T15:00:00+08:00", window_duration_minutes: 300, observed_at: "2026-07-18T10:00:00+08:00", source_type: "oauth_usage_api", confidence: "observed", status: "ok", official: true }],
    }) as Record<string, any>;
    expect(mobile.limits.windows).toEqual([]);
  });

  it("hides stale remote windows while preserving the last trusted update", () => {
    const mobile = buildMobileSummary({
      generated_at: "2026-07-18T12:30:00+08:00",
      timezone: "Asia/Shanghai",
      summary: { period: "today", total_tokens: 600 },
      trend: { points: [] },
      source_status: [],
      groups: {},
      items: [],
      limits: [{
        source_id: "linux-biai-wang",
        provider: "claude",
        window: "week",
        used_percent: 41,
        remaining_percent: 59,
        reset_at: "2026-07-20T00:00:00+08:00",
        window_duration_minutes: 10080,
        observed_at: "2026-07-18T10:00:00+08:00",
        source_type: "official_cli",
        confidence: "observed",
        status: "ok",
        official: true,
      }],
    }) as Record<string, any>;

    expect(mobile.limits.windows).toEqual([]);
    expect(mobile.metadata).toMatchObject({
      freshness_status: "stale",
      limits_observed_at: "2026-07-18T10:00:00+08:00",
    });
  });
});

import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { collectQuotaUnavailableSummary, quotaUnavailableOwnerFixturePath } from "./golden/quota-unavailable-owner";
import { sourceAgents } from "../src/source-breakdown";

describe("quota unavailable owner fixture", () => {
  it("regenerates the complete actual route fixture and checks seven distinct real models in three groups", async () => {
    const actual = await collectQuotaUnavailableSummary();
    const fixture = JSON.parse(await readFile(quotaUnavailableOwnerFixturePath, "utf8"));
    expect(actual).toEqual(fixture);
    const expected: Record<string, string> = {
      "gpt-6-sol": "backtest_failed", "gpt-5.6-sol": "insufficient_data",
      "unmapped-model": "unsupported_model", "claude-sonnet-5": "stale",
      "claude-haiku-5": "not_calibrated", "claude-fable-5": "formula_changed",
    };
    for (const key of ["by_source", "by_machine", "by_os_user"]) {
      expect(actual.breakdown[key]).toHaveLength(1);
      const models = actual.breakdown[key][0].agents.flatMap((a: any) => a.models);
      expect(models).toHaveLength(8);
      for (const [name, reason] of Object.entries(expected)) {
        const model = models.find((m: any) => m.id === name);
        expect(model.tokens).toBe(1000);
        expect(model.quota_estimate).toBeUndefined();
        expect(model.quota_estimate_unavailable.reason).toBe(reason);
      }
      const failed = models.find((m: any) => m.id === "gpt-6-sol");
      expect(failed.quota_estimate_unavailable).toEqual({ reason: "backtest_failed", sample_intervals: 92, backtest_max_error: 2.306 });
      const insufficient = models.find((m: any) => m.id === "gpt-5.6-sol");
      expect(insufficient.quota_estimate_unavailable).toEqual({ reason: "insufficient_data", sample_intervals: 0 });
      const opus = models.find((m: any) => m.id === "claude-opus-5");
      expect(opus.quota_estimate).toEqual({ percent: 0.01, grade: "A", basis: "week" });
      expect(opus.quota_estimate_unavailable).toBeUndefined();
      const unknown = models.find((m: any) => m.id === "unknown");
      expect(unknown.tokens).toBe(200);
      expect(unknown.status).toBe("missing");
      expect(unknown.quota_estimate_unavailable).toBeUndefined();
    }
    // 独立用最终产物复算守恒，不能只比较两份相同 owner 输出。
    expect(actual.period.total_tokens).toBe(7200);
    expect(actual.breakdown.by_machine[0].agents.flatMap((a: any) => a.models)
      .reduce((sum: number, m: any) => sum + m.tokens, 0)).toBe(7200);
  });

  it("conflicting or missing diagnostics stay revoked even when a later row repeats the first", () => {
    const failed = { reason: "backtest_failed", sample_intervals: 92, backtest_max_error: 2.306 };
    const rows = (diagnoses: any[]) => diagnoses.map((diagnosis) => ({ agent: "codex", total_tokens: 10,
      model_breakdowns: [{ model_name: "gpt-6-sol", total_tokens: 10, quota_estimate_unavailable: diagnosis }] }));
    for (const middle of [{ ...failed, backtest_max_error: 1 }, undefined]) {
      const groups = sourceAgents(rows([failed, middle, failed]));
      const models = groups.find((g) => g.id === "codex")!.models;
      expect(models).toHaveLength(1);
      expect(models[0].tokens).toBe(30);
      expect(models[0].quota_estimate_unavailable).toBeUndefined();
    }
  });
});

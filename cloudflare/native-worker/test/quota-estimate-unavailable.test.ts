import { describe, expect, it } from "vitest";
import { indexQuotaCalibration, quotaEstimateForModel, quotaEstimateUnavailableForModel, type QuotaCalibrationRow } from "../src/read-model/quota-estimate";
const now = new Date("2026-06-10T12:00:00Z");
const base: QuotaCalibrationRow = { provider: "codex", model_family: "gpt-6", coef: 0.001,
  grade: "B", fitted_at: now.toISOString(), formula_version: "v1", backtest_max_err: 0.2, sample_intervals: 10 };

describe("quota estimate failure gates", () => {
  it("classifies each gate, including null error, signed error, period, formula, stale and unknown grade", () => {
    const cases: [Partial<QuotaCalibrationRow> | null, string, string, string, string | undefined][] = [
      [{ grade: "none", backtest_max_err: -2.306 }, "codex", "gpt-6-sol", "week", "backtest_failed"],
      [{ grade: "none", backtest_max_err: 0.25 }, "codex", "gpt-6-sol", "week", "insufficient_data"],
      [{ grade: "none", backtest_max_err: null, sample_intervals: 0 }, "codex", "gpt-6-sol", "today", "insufficient_data"],
      [{ fitted_at: "2026-06-01T12:00:00Z" }, "codex", "gpt-6-sol", "week", "stale"],
      [{ formula_version: "v0" }, "codex", "gpt-6-sol", "week", "formula_changed"],
      [null, "codex", "gpt-6-sol", "week", "not_calibrated"],
      [{ grade: "C" }, "codex", "gpt-6-sol", "week", "not_calibrated"],
      [{}, "codex", "unknown-model", "week", "unsupported_model"],
      [{}, "unknown-provider", "gpt-6-sol", "week", "unsupported_model"],
      [{}, "codex", "gpt-6-sol", "all", "unsupported_period"],
      [{}, "codex", "gpt-6-sol", "month", undefined],
      [{ grade: "A" }, "codex", "gpt-6-sol", "today", undefined],
    ];
    expect(cases).toHaveLength(12);
    for (const [patch, provider, model, period, reason] of cases) {
      const rows = indexQuotaCalibration(patch === null ? [] : [{ ...base, ...patch }]);
      const diag = quotaEstimateUnavailableForModel(provider, model, period as any, now, rows);
      expect(diag?.reason).toBe(reason);
      const estimate = quotaEstimateForModel(provider, model,
        { input_tokens: 100, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0 },
        period as any, "2026-06-01", "2026-06-10", now, rows);
      if (reason) expect(estimate).toBeUndefined();
      else expect(estimate?.percent).toBeGreaterThan(0);
      if (patch?.backtest_max_err === null) expect(diag).toEqual({ reason, sample_intervals: 0 });
      if (patch?.backtest_max_err === -2.306) expect(diag?.backtest_max_error).toBe(2.306);
    }
  });
});

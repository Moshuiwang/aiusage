/** #183-a：模型族映射与价格加权口径的单元覆盖。 */
import { describe, expect, it } from "vitest";
import { familyForModel, KNOWN_FAMILIES, priceWeightedTokens } from "../src/calibration/constants";

describe("familyForModel", () => {
  it("按子串把 Claude 模型名映射到 opus/sonnet/haiku/fable 四个族", () => {
    expect(familyForModel("claude", "claude-opus-4-8")).toBe("opus");
    expect(familyForModel("claude", "claude-opus-5-5")).toBe("opus");
    expect(familyForModel("claude", "claude-sonnet-5")).toBe("sonnet");
    expect(familyForModel("claude", "claude-haiku-4-5-20251001")).toBe("haiku");
    expect(familyForModel("claude", "claude-fable-5-1")).toBe("fable");
  });

  it("claude agent 下非 Anthropic 模型（deepseek 等）不属于任何族", () => {
    expect(familyForModel("claude", "deepseek-v4-pro")).toBeNull();
  });

  it("Codex 模型按档位（astra / sol / luna / terra）映射，不按版本号；review 优先", () => {
    // #206：同一版本前缀下不同档位的额度消耗相差十倍以上，版本号不决定消耗。
    expect(familyForModel("codex", "codex-auto-review")).toBe("review");
    expect(familyForModel("codex", "gpt-6-astra")).toBe("astra");
    expect(familyForModel("codex", "gpt-6-sol")).toBe("sol");
    expect(familyForModel("codex", "gpt-6.1-sol")).toBe("sol");
    expect(familyForModel("codex", "gpt-5.6-sol")).toBe("sol");
    expect(familyForModel("codex", "gpt-6-luna")).toBe("luna");
    expect(familyForModel("codex", "gpt-5.6-luna")).toBe("luna");
    expect(familyForModel("codex", "gpt-5.6-terra")).toBe("terra");
  });

  it("codex agent 下非 OpenAI 档位模型（本地 qwen 等）不属于任何族", () => {
    expect(familyForModel("codex", "qwen3.8-27b")).toBeNull();
  });

  it("Antigravity 模型按 flash / pro / claude-on-antigravity 映射，unknown 模型名不属于任何族", () => {
    expect(familyForModel("antigravity", "gemini-3.8-flash-tiered")).toBe("flash");
    expect(familyForModel("antigravity", "gemini-pro-default")).toBe("pro");
    expect(familyForModel("antigravity", "claude-opus-4-6-thinking")).toBe("claude-on-antigravity");
    expect(familyForModel("antigravity", "unknown")).toBeNull();
  });

  it("大小写不敏感", () => {
    expect(familyForModel("claude", "CLAUDE-OPUS-4-8")).toBe("opus");
  });
});

describe("KNOWN_FAMILIES", () => {
  it("每个 provider 都声明了至少一个已知族，且与 familyForModel 的映射集一致", () => {
    for (const provider of ["claude", "codex", "antigravity"] as const) {
      expect(KNOWN_FAMILIES[provider].length).toBeGreaterThan(0);
    }
    expect(KNOWN_FAMILIES.claude).toEqual(["opus", "sonnet", "haiku", "fable"]);
    expect(KNOWN_FAMILIES.codex).toEqual(["review", "astra", "sol", "luna", "terra"]);
    expect(KNOWN_FAMILIES.antigravity).toEqual(["flash", "pro", "claude-on-antigravity"]);
  });
});

describe("priceWeightedTokens", () => {
  it("Claude output 权重是 input 的 5 倍；Codex 按官方 credit 表（#271）同样是 5 倍，cached 0.1 倍", () => {
    // 官方 credit 表（learn.chatgpt.com/docs/pricing，2026-10-07）：GPT-6 Sol input 50 / cached 5 / output 250。
    const tokens = { input_tokens: 1000, output_tokens: 1000, cache_creation_tokens: 0, cache_read_tokens: 1000 };
    expect(priceWeightedTokens("claude", tokens)).toBe(1000 * 1 + 1000 * 5 + 1000 * 0.1);
    expect(priceWeightedTokens("codex", tokens) * 50).toBeCloseTo(1000 * 50 + 1000 * 250 + 1000 * 5, 6);
  });

  it("独立复算：input×1 + output×W_out + cache_creation×1.25 + cache_read×0.1", () => {
    const tokens = { input_tokens: 200, output_tokens: 50, cache_creation_tokens: 40, cache_read_tokens: 1000 };
    const expected = 200 * 1 + 50 * 5 + 40 * 1.25 + 1000 * 0.1;
    expect(priceWeightedTokens("claude", tokens)).toBeCloseTo(expected, 6);
  });
});

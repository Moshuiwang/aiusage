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

// #90 缺口块 6：移动端账户 / 套餐标签的安全处理。
//
// `safeAccountLabel` / `safePlanLabel` / `mergeAccountContext` 在 Worker 测试里原本零命中，
// 而它们守的是**会一路送到 iPhone / Watch 屏幕上**的字符串。账户标签的来源包括
// `ai_accounts.label`、`account_hourly.by_ai_account`、额度窗口自带的 `account_email`——
// 这几处都可能被采集端灌进凭据片段或本机路径。展示层是只读的，不会再过滤一遍，
// 所以「不该露的东西不能进 payload」这条只能在这里守。
//
// 每条脱敏断言都配一个**安全对照组**：只断言「不安全的没出现」是恒真的——
// 实现整个坏掉、什么都不输出时，那条断言照样绿。
describe("mobile account and plan labels", () => {
  const snapshotWith = (window: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
    generated_at: "2026-07-18T12:30:00+08:00",
    timezone: "Asia/Shanghai",
    summary: { period: "today", total_tokens: 600 },
    trend: { points: [] },
    source_status: [],
    groups: {},
    items: [],
    limit_status: [],
    ...extra,
    limits: [{
      source_id: "linux-dev",
      provider: "claude",
      window: "week",
      used_percent: 41,
      remaining_percent: 59,
      reset_at: "2026-07-25T00:00:00+08:00",
      window_duration_minutes: 10080,
      observed_at: "2026-07-18T12:00:00+08:00",
      source_type: "oauth_usage_api",
      confidence: "observed",
      status: "ok",
      official: true,
      ...window,
    }],
  });

  const onlyWindow = (snapshot: Record<string, unknown>) => {
    const mobile = buildMobileSummary(snapshot) as Record<string, any>;
    // 结构下限：窗口必须真的进到 payload 里。它被上游任何一条过滤挡掉时，
    // 下面所有「标签是什么」的断言都会变成对 undefined 的断言，全部恒真。
    expect(mobile.limits.windows, "额度窗口必须进入 payload，否则下面的断言什么都没检查")
      .toHaveLength(1);
    return mobile.limits.windows[0] as Record<string, any>;
  };

  it("把安全的账户标签透出，把带凭据或本机路径的整条丢掉", () => {
    // 正面对照：证明这个字段在安全时**确实会**出现——否则下面的「不出现」全是恒真。
    expect(onlyWindow(snapshotWith({ account_email: "alice@example.com" })).account_label)
      .toBe("alice@example.com");

    const unsafe = [
      "sk-ant-api03-abcdef",              // API key 前缀
      "sess-0123456789",                  // session token 前缀
      "eyJhbGciOiJIUzI1NiJ9.payload",     // JWT
      "Bearer abcdef123456",              // 授权头原文
      "authorization: token abc",         // 字段名 + 值
      "/Users/wangzhipeng/.claude/auth.json", // 本机路径 + 凭据文件（同时命中三条规则）
      "/home/wangzp/.codex/auth.json",
      // **纯路径**：不含 auth.json / .claude / .codex，只靠路径前缀这一条规则拦。
      // 少了这三条，上面那两条会同时命中凭据文件规则，路径规则本身从未被求值——
      // 把 safeAccountLabel 的 "/users/" "/home/" "\\users\\" 三项删掉，全量测试仍然全绿
      // （审查实测过）。此后账户标签是本机路径时会原样送到 iPhone / Watch 屏幕上。
      "/Users/wangzhipeng/Documents",
      "/home/wangzp/projects/ai-usage",
      "C:\\Users\\alice\\AppData",       // Windows 形态，此前零覆盖
      "x".repeat(121),                    // 超长：整段日志被灌进来的形态
    ];
    for (const value of unsafe) {
      const window = onlyWindow(snapshotWith({ account_email: value }));
      expect("account_label" in window, `不安全的账户标签必须整条丢掉，不能留空串：${value.slice(0, 24)}`)
        .toBe(false);
      // 丢掉之后也不许从别处泄回来：整份 payload 里不得再出现这个片段。
      expect(JSON.stringify(window).includes(value.slice(0, 12)), `${value.slice(0, 24)} 从别的字段泄回来了`)
        .toBe(false);
    }
  });

  it("把套餐名人性化，并丢掉形状可疑的整条", () => {
    const planOf = (provider: string, subscription: string) =>
      onlyWindow(snapshotWith({ provider, subscription })).account_plan_label;

    // provider 专属的人性化：同一个 "pro" 在两侧含义不同，不能混。
    expect(planOf("codex", "pro"), "codex 的 pro 是 20x 档").toBe("Pro 20x");
    expect(planOf("codex", "pro_lite"), "codex 的 prolite 是 5x 档").toBe("Pro 5x");
    expect(planOf("claude", "claude pro"), "claude 的 pro 就是 Pro").toBe("Pro");
    // 通用回落：下划线转空格 + 首字母大写，但 "20x" 这类倍数保持小写 x。
    expect(planOf("claude", "team_plan")).toBe("Team Plan");
    expect(planOf("claude", "max_20X")).toBe("Max 20x");

    for (const value of ["y".repeat(33), "pro; DROP TABLE", "计划<script>"]) {
      const window = onlyWindow(snapshotWith({ provider: "claude", subscription: value }));
      expect("account_plan_label" in window, `形状可疑的套餐名必须整条丢掉：${value.slice(0, 20)}`)
        .toBe(false);
    }
  });

  it("从多个来源合并账户信息，先到的不被后到的覆盖", () => {
    // 同一个账号的信息散在 account_hourly 与 ai_accounts 两处：
    // 各自只有一半字段，合并后两半都要在。
    const window = onlyWindow(snapshotWith({}, {
      account_hourly: { by_ai_account: [{ provider: "claude", account_id: "claude-main", label: "alice@example.com" }] },
      ai_accounts: [{ provider: "anthropic", account_id: "claude-main", subscription: "team_plan" }],
    }));
    expect(window.account_label, "account_hourly 那半边的标签要在").toBe("alice@example.com");
    expect(window.account_plan_label, "ai_accounts 那半边的套餐要被合并进来").toBe("Team Plan");
  });

  it("同一 provider 下有两个不同账号时不猜，整条 context 不产出", () => {
    // 猜错的后果是把 A 账号的标签挂到 B 账号的额度上——比不显示更糟。
    const ambiguous = onlyWindow(snapshotWith({}, {
      ai_accounts: [
        { provider: "claude", account_id: "claude-a", label: "alice@example.com" },
        { provider: "claude", account_id: "claude-b", label: "bob@example.com" },
      ],
    }));
    expect("account_label" in ambiguous, "两个账号无法区分时不许挑一个显示").toBe(false);

    // 对照：只有一个账号时照常显示，证明上面不是「这条路径根本不工作」。
    const unambiguous = onlyWindow(snapshotWith({}, {
      ai_accounts: [{ provider: "claude", account_id: "claude-a", label: "alice@example.com" }],
    }));
    expect(unambiguous.account_label).toBe("alice@example.com");
  });

  it("provider 别名按 canonical 归一：openai→codex、anthropic→claude", () => {
    // 账户上下文用 canonical provider 做键；别名不归一时，标签会挂不上去。
    const claude = onlyWindow(snapshotWith({ provider: "claude" }, {
      ai_accounts: [{ provider: "anthropic", account_id: "claude-main", label: "alice@example.com" }],
    }));
    expect(claude.account_label, "anthropic 的账户信息必须挂到 claude 槽位").toBe("alice@example.com");

    const codex = onlyWindow(snapshotWith({ provider: "codex" }, {
      ai_accounts: [{ provider: "openai", account_id: "codex-main", label: "bob@example.com" }],
    }));
    expect(codex.account_label, "openai 的账户信息必须挂到 codex 槽位").toBe("bob@example.com");
  });
});

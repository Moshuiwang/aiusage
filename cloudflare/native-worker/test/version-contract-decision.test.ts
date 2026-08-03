// 版本判定的单元级守卫（Issue #90 块 3 / 4 / 10）。
//
// 现有的 `version-contract.test.ts` 全部是 HTTP 端到端级用例：走 Miniflare + D1，
// 只能覆盖「被 ingest 调到的那条路径」。`compareVersions` 的 semver 语义、判定优先级、
// 词表本身——被误改时端到端用例不一定变红（比如 prerelease 排序错了，只要没有 beta
// 采集端在场景里出现，全绿）。本文件直接对导出函数与常量下断言，补上这一层。
//
// 期望值不是照着实现读出来的，是先跑探针拿到真实行为再写的；每条都能指出
// 「改坏了什么会让它红」。
import { describe, expect, it } from "vitest";
import {
  ALL_VERSION_STATES,
  VERSION_STATES,
  VERSION_STATE_CURRENT,
  VERSION_STATE_ROLLBACK_AVAILABLE,
  VERSION_STATE_SEVERITY,
  VERSION_STATE_UNKNOWN,
  VERSION_STATE_UNSUPPORTED,
  VERSION_STATE_UPDATE_AVAILABLE,
  VersionContractError,
  buildVersionHealth,
  compareVersions,
  evaluateCollectorRelease,
  normalizeCollectorRelease,
  type VersionPolicy,
} from "../src/version-contract";

type AnyRecord = Record<string, any>;

/** 判定探针策略。默认策略 min = 0.1.0，构造不出 below_minimum，必须自带一份。 */
const POLICY: VersionPolicy = {
  min_supported_collector_version: "0.2.0",
  target_collector_version: "0.4.0",
  min_supported_config_schema_version: 1,
  min_supported_parser_schema_version: 2,
};

function evaluate(raw: Record<string, unknown> | null): AnyRecord {
  return evaluateCollectorRelease(normalizeCollectorRelease(raw), POLICY);
}

function expectContractError(raw: unknown): VersionContractError {
  let caught: unknown;
  try {
    normalizeCollectorRelease(raw);
  } catch (error) {
    caught = error;
  }
  expect(caught, `${JSON.stringify(raw)} 必须被拒绝，实际没有抛错`).toBeInstanceOf(VersionContractError);
  return caught as VersionContractError;
}

// --- 块 3：compareVersions 的 semver 语义 -----------------------------------

describe("compareVersions 的 semver 语义（#90 块 3）", () => {
  it("按数值比较而不是字符串比较", () => {
    // 字符串序会把 0.9.0 判在 0.10.0 之后，这正是版本判定最容易悄悄错的一处：
    // 判错方向 = 已经升到 0.10.0 的设备被当成落后，一直提示升级。
    expect(compareVersions("0.10.0", "0.9.0")).toBe(1);
    expect(compareVersions("0.9.0", "0.10.0")).toBe(-1);
    expect(compareVersions("1.0.0", "0.100.0")).toBe(1);
    expect(compareVersions("0.4.0", "0.4.0")).toBe(0);
  });

  it("prerelease 版本低于同号正式版，但高于上一个正式版", () => {
    expect(compareVersions("1.0.0-alpha", "1.0.0")).toBe(-1);
    expect(compareVersions("1.0.0", "1.0.0-alpha")).toBe(1);
    expect(compareVersions("0.4.0-beta.1", "0.3.9")).toBe(1);
  });

  it("prerelease 段按 semver 规则排序：数字段低于字母段，前缀相同时段数多的更大", () => {
    // semver 官方示例序列。整条序列一次钉住，比逐对断言更难被局部改坏而不红。
    const semverOrder = [
      "1.0.0-alpha",
      "1.0.0-alpha.1",
      "1.0.0-alpha.beta",
      "1.0.0-beta",
      "1.0.0-beta.2",
      "1.0.0-beta.11",
      "1.0.0-rc.1",
      "1.0.0",
    ];

    const shuffled = [
      "1.0.0-beta.11",
      "1.0.0",
      "1.0.0-alpha.beta",
      "1.0.0-rc.1",
      "1.0.0-alpha",
      "1.0.0-beta",
      "1.0.0-beta.2",
      "1.0.0-alpha.1",
    ];
    // 结构下限：打乱后的输入必须真的和目标序列不同，否则 sort 什么都没做也能绿。
    expect(shuffled).not.toEqual(semverOrder);
    expect([...shuffled].sort()).toEqual([...semverOrder].sort());

    expect([...shuffled].sort(compareVersions)).toEqual(semverOrder);
  });

  it("build metadata 不参与比较（正式版与 prerelease 两条剥离路径都要覆盖）", () => {
    // 第一版这条只写了 `1.0.0+build.1` 这类例子，变异「不再剥离 core 的 +」时**没有变红**：
    // `+build` 落在第 3 段之后，被 `slice(0, 3)` 顺手抹掉了，断言实际被一个无关机制护着。
    // 下面两条把 build metadata 放进真正会参与比较的位置，才算守住剥离逻辑本身。
    expect(compareVersions("0.4.1+20260803", "0.4.1")).toBe(0);
    expect(compareVersions("1.0.0-beta+exp.1", "1.0.0-beta")).toBe(0);

    expect(compareVersions("1.0.0+build.1", "1.0.0+build.2")).toBe(0);
    expect(compareVersions("0.4.1+20260803", "0.4.0")).toBe(1);
  });

  it("缺段补零，非数字段按 0 处理", () => {
    expect(compareVersions("1.2", "1.2.0")).toBe(0);
    expect(compareVersions("1", "1.0.0")).toBe(0);
    expect(compareVersions("x.y.z", "0.0.0")).toBe(0);
    // 补零不能顺手把比较也抹平：1.2 仍然必须小于 1.2.1。
    expect(compareVersions("1.2", "1.2.1")).toBe(-1);
  });

  it("beta 通道的采集端按 prerelease 判定：落后于目标，但不拒收", () => {
    // 这条把 compareVersions 接到真实判定上——单元序对了、判定没用它，同样是坏的。
    const beta = evaluate({ collector_version: "0.4.0-beta.1" });

    expect(beta.state).toBe(VERSION_STATE_UPDATE_AVAILABLE);
    expect(beta.reason).toBe("collector_version_behind_target");
    expect(beta.accepted).toBe(true);
  });
});

// --- 块 4：判定细节 ----------------------------------------------------------

describe("版本判定的边界与优先级（#90 块 4）", () => {
  it("枚举字段非法时明确拒绝，错误只报字段名不回显值", () => {
    const channelError = expectContractError({ collector_version: "0.4.0", release_channel: "canary" });
    expect(channelError.field).toBe("collector_release.release_channel");
    expect(channelError.message).toContain("stable, beta, dev");
    expect(channelError.message).not.toContain("canary");

    const statusError = expectContractError({
      collector_version: "0.4.0",
      last_upgrade: { status: "exploded" },
    });
    expect(statusError.field).toBe("collector_release.last_upgrade.status");
    expect(statusError.message).toContain("never, succeeded, failed, rolled_back");
    expect(statusError.message).not.toContain("exploded");
  });

  it("unsupported 优先于其余所有状态", () => {
    // 同时满足「低于最低支持版本」和「上次升级失败可回滚」时，必须判 unsupported：
    // 反过来就是把一台服务端根本不接受的采集端显示成「可回滚」，用户会以为还能用。
    const belowAndRollback = evaluate({
      collector_version: "0.1.0",
      last_upgrade: { status: "failed", from_version: "0.0.9" },
    });
    expect(belowAndRollback.state).toBe(VERSION_STATE_UNSUPPORTED);
    expect(belowAndRollback.reason).toBe("collector_version_below_minimum");
    expect(belowAndRollback.accepted).toBe(false);

    // 版本号超前目标、但 parser schema 低于最低支持值：仍然是 unsupported。
    const aheadButParserTooOld = evaluate({ collector_version: "0.9.0", parser_schema_version: 1 });
    expect(aheadButParserTooOld.state).toBe(VERSION_STATE_UNSUPPORTED);
    expect(aheadButParserTooOld.reason).toBe("parser_schema_version_below_minimum");
    expect(aheadButParserTooOld.accepted).toBe(false);
  });

  it("rollback_available 优先于 update_available，并带出可回退版本", () => {
    const behindAndFailed = evaluate({
      collector_version: "0.3.0",
      last_upgrade: { status: "failed", from_version: "0.2.0" },
    });

    expect(behindAndFailed.state).toBe(VERSION_STATE_ROLLBACK_AVAILABLE);
    expect(behindAndFailed.reason).toBe("last_upgrade_failed");
    expect(behindAndFailed.rollback_target_version).toBe("0.2.0");
    expect(behindAndFailed.accepted).toBe(true);
  });

  it("跑在比目标更新的版本上判可回滚，回退目标是目标版本本身", () => {
    const ahead = evaluate({ collector_version: "0.9.0" });

    expect(ahead.state).toBe(VERSION_STATE_ROLLBACK_AVAILABLE);
    expect(ahead.reason).toBe("collector_version_ahead_of_target");
    expect(ahead.rollback_target_version).toBe(POLICY.target_collector_version);
    expect(ahead.compatible).toBe(true);
  });

  it("升级失败但没有可回退版本时不谎报可回滚", () => {
    // 只有「失败 + 有 from_version」才构成可回滚。少了 from_version 还判 rollback，
    // 用户会看到一个回退按钮指向 null。
    const failedWithoutSource = evaluate({
      collector_version: "0.4.0",
      last_upgrade: { status: "failed" },
    });
    expect(failedWithoutSource.state).toBe(VERSION_STATE_CURRENT);
    expect(failedWithoutSource.rollback_target_version).toBeNull();

    // `rolled_back` 是已经回滚完成，不是待回滚，同样不触发 rollback_available。
    const alreadyRolledBack = evaluate({
      collector_version: "0.4.0",
      last_upgrade: { status: "rolled_back", from_version: "0.3.0" },
    });
    expect(alreadyRolledBack.state).toBe(VERSION_STATE_CURRENT);
    expect(alreadyRolledBack.rollback_target_version).toBeNull();
  });

  it("last_upgrade 里的未知 key 同样脱敏，且普通字段名照常回显", () => {
    // 顶层未知 key 的脱敏已有覆盖，嵌套层此前零覆盖——脱敏只做一层的话，
    // 凭据形态的 key 会从 last_upgrade 这条路径原样进 400 响应体和日志。
    const credentialKey = "sk-ant-api03-FAKEfakeFAKEfake0123456789";
    const redacted = expectContractError({
      collector_version: "0.4.0",
      last_upgrade: { [credentialKey]: "1" },
    });
    expect(redacted.field).toBe("collector_release.last_upgrade.<redacted>");
    expect(redacted.message).not.toContain(credentialKey);

    // 安全对照组：普通 snake_case key 必须**原样保留**。少了这条，
    // 一个「无脑全脱敏」的实现也能让上面那条绿，错误信息则彻底失去可操作性。
    const plain = expectContractError({
      collector_version: "0.4.0",
      last_upgrade: { rollback_note: "1" },
    });
    expect(plain.field).toBe("collector_release.last_upgrade.rollback_note");
    expect(plain.message).toContain("rollback_note");
  });

  it("update_available 不拒收：落后的采集端照常写入，只是带升级提示", () => {
    const behind = evaluate({ collector_version: "0.3.0" });

    expect(behind.state).toBe(VERSION_STATE_UPDATE_AVAILABLE);
    expect(behind.accepted).toBe(true);
    expect(behind.compatible).toBe(true);
    expect(behind.verified).toBe(true);
  });
});

// --- 块 10：状态词表与严重度 --------------------------------------------------

describe("版本状态词表与严重度（#90 块 10）", () => {
  it("四态词表逐字钉住，unknown 不在四态里", () => {
    // 这些字符串是 wire 值：进 /api/summary 的 source_status[].version.state，
    // 也进 macOS / iOS 客户端的展示分支。改一个字就是一次静默的对外合同变更。
    expect([...VERSION_STATES]).toEqual([
      "current",
      "update_available",
      "unsupported",
      "rollback_available",
    ]);
    expect([...ALL_VERSION_STATES]).toEqual([
      "current",
      "update_available",
      "unsupported",
      "rollback_available",
      "unknown",
    ]);
    // 这里原本还有 `VERSION_STATES 不含 unknown` 与 `ALL_VERSION_STATES 无重复` 两条。
    // 它们是恒真的：上面两条 toEqual 一旦通过，两个数组就已经是那几个互不相同的字面量，
    // 后面两条不可能为假。独立审查抓到，删掉，覆盖力零损失。
  });

  it("严重度覆盖全部状态、互不相同，且顺序是「越需要人工处理越小」", () => {
    expect(Object.keys(VERSION_STATE_SEVERITY).sort()).toEqual([...ALL_VERSION_STATES].sort());
    expect(new Set(Object.values(VERSION_STATE_SEVERITY)).size).toBe(ALL_VERSION_STATES.length);

    const bySeverity = [...ALL_VERSION_STATES].sort(
      (left, right) => VERSION_STATE_SEVERITY[left] - VERSION_STATE_SEVERITY[right],
    );
    expect(bySeverity).toEqual([
      VERSION_STATE_UNSUPPORTED,
      VERSION_STATE_ROLLBACK_AVAILABLE,
      VERSION_STATE_UPDATE_AVAILABLE,
      VERSION_STATE_UNKNOWN,
      VERSION_STATE_CURRENT,
    ]);
  });

  it("词表是 counts 的闭集：词表外的状态归 unknown，不新建计数键", () => {
    // 状态值来自库里的历史行，不是受控输入。让它自建键，看板上就会冒出一个
    // 谁都没定义过的状态桶，而「全部设备数 == 各状态之和」这条口径照样成立，很难发现。
    const health = buildVersionHealth([
      { source_id: "a", version: { state: VERSION_STATE_CURRENT } },
      { source_id: "b", version: { state: "totally-made-up" } },
      { source_id: "c", version: {} },
      { source_id: "d" },
    ]);
    const counts = health.counts as Record<string, number>;

    expect(Object.keys(counts).sort()).toEqual([...ALL_VERSION_STATES].sort());
    expect(counts[VERSION_STATE_UNKNOWN]).toBe(3);
    expect(counts[VERSION_STATE_CURRENT]).toBe(1);
    // 结构下限：总数必须等于输入行数，否则「某些行被静默丢掉」也能让上面两条绿。
    expect(Object.values(counts).reduce((sum, value) => sum + value, 0)).toBe(4);

    const listed = (health.needs_attention as AnyRecord[]).map((row) => row.source_id);
    expect(listed).toEqual(["b", "c", "d"]);
  });
});

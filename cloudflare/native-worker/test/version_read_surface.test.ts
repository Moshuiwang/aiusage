// Issue #63 C 组：Cloudflare Native Worker 读取侧三个出口的版本读模型。
//
// #74 之后口径唯一 owner 是本目录的 src/：
//   - `source_status[].version` = `publicVersionView(evaluateCollectorRelease(...))`（read-model.ts）
//   - 顶层 `version_health` 与 `/api/health` 的 `versions` = `buildVersionHealth(source_status)`
//     （version-contract.ts）。语义从删除前的 Python 读模型逐字继承。
// Worker 必须逐字一致：字段名、状态名、reason 名、排序规则都不允许分叉。
//
// 语义红线（#63 2026-08-02 修订）：物化下来的版本是「**最后一次被服务端成功接收的版本**」，
// 不能证明设备此刻正在运行的版本——不兼容 payload 在写库前就被拒绝了，根本进不了这张表。
// 所以本文件只断言结构与判定，不断言任何「当前运行版本 / 正在运行」的文案。
//
// 本文件只写断言，不写实现。期望值全部手写字面量，不调用被测代码反算期望值。
import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  MIN_SUPPORTED_COLLECTOR_VERSION,
  TARGET_COLLECTOR_VERSION,
} from "../src/version-contract";

type AnyRecord = Record<string, any>;

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const token = "contract-test-token";
const fixedNow = "2026-06-03T12:00:00+08:00";
const authHeaders = { Authorization: `Bearer ${token}` };

/** `public_version_view` 之后每个来源版本块的**完整**字段集，共 16 个，多一个少一个都算分叉。 */
const VERSION_VIEW_FIELDS = [
  "collector_version",
  "config_schema_version",
  "parser_schema_version",
  "release_channel",
  "build_sha",
  "last_upgrade_status",
  "last_upgrade_from_version",
  "last_upgrade_to_version",
  "last_upgrade_finished_at",
  "min_supported_collector_version",
  "target_collector_version",
  "rollback_target_version",
  "state",
  "reason",
  "compatible",
  "verified",
].sort();

/** `build_version_health` 的 counts 必须覆盖全部五个状态，包括计数为 0 的那些。 */
const ALL_VERSION_STATE_KEYS = [
  "current",
  "update_available",
  "unsupported",
  "rollback_available",
  "unknown",
].sort();

/** `needs_attention` 每一项的**完整**字段集，共 12 个。 */
const NEEDS_ATTENTION_FIELDS = [
  "source_id",
  "display_name",
  "machine",
  "os_user",
  "status",
  "observed_at",
  "state",
  "collector_version",
  "release_channel",
  "build_sha",
  "reason",
  "compatible",
].sort();

/**
 * 读取侧只物化了 `collector_version` 单个字段（Python 侧同样只取这一个：
 * `source_versions = {source_id: {"collector_version": row[4]}}`），其余采集端字段一律为 null。
 */
function expectedVersionView(overrides: AnyRecord): AnyRecord {
  return {
    collector_version: null,
    config_schema_version: null,
    parser_schema_version: null,
    release_channel: null,
    build_sha: null,
    last_upgrade_status: null,
    last_upgrade_from_version: null,
    last_upgrade_to_version: null,
    last_upgrade_finished_at: null,
    min_supported_collector_version: MIN_SUPPORTED_COLLECTOR_VERSION,
    target_collector_version: TARGET_COLLECTOR_VERSION,
    rollback_target_version: null,
    ...overrides,
  };
}

/**
 * 六个来源覆盖四态 + unknown 降级态。
 * 版本号是相对 `MIN_SUPPORTED_COLLECTOR_VERSION` / `TARGET_COLLECTOR_VERSION` 挑的，
 * 常量一旦变动必须同步改这里——下面有一条守卫测试会先报出来。
 */
const SOURCES = [
  {
    // 插入顺序故意打乱，用来证明 needs_attention 的排序与输入顺序无关。
    source_id: "zeta-current",
    machine: "zeta-box",
    os_user: "alice",
    platform: "darwin",
    collected_at: "2026-06-03T11:45:00+08:00",
    status: "ok",
    error_message: null as string | null,
    collector_version: "0.3.0" as string | null,
  },
  {
    source_id: "gamma-legacy",
    machine: "gamma-box",
    os_user: "dave",
    platform: "linux",
    collected_at: "2026-06-03T11:42:00+08:00",
    status: "provider_failed",
    error_message: "provider down" as string | null,
    collector_version: "0.0.9" as string | null,
  },
  {
    // 从未上报过版本：必须判成 unknown 且 verified=false，不许当成合规。
    source_id: "omega-silent",
    machine: "omega-box",
    os_user: "frank",
    platform: "linux",
    collected_at: "2026-06-03T11:44:00+08:00",
    status: "ok",
    error_message: null as string | null,
    collector_version: null as string | null,
  },
  {
    source_id: "alpha-outdated",
    machine: "alpha-box",
    os_user: "carol",
    platform: "linux",
    collected_at: "2026-06-03T11:40:00+08:00",
    status: "ok",
    error_message: null as string | null,
    collector_version: "0.1.5" as string | null,
  },
  {
    source_id: "beta-ahead",
    machine: "beta-box",
    os_user: "erin",
    platform: "darwin",
    collected_at: "2026-06-03T11:41:00+08:00",
    status: "ok",
    error_message: null as string | null,
    collector_version: "0.4.0" as string | null,
  },
  {
    source_id: "mid-outdated",
    machine: "mid-box",
    os_user: "bob",
    platform: "linux",
    collected_at: "2026-06-03T11:43:00+08:00",
    status: "ok",
    error_message: null as string | null,
    collector_version: "0.2.0" as string | null,
  },
];

/** 每个来源期望的 `source_status[].version`，逐字手写。 */
const EXPECTED_VERSION_VIEW: Record<string, AnyRecord> = {
  "zeta-current": expectedVersionView({
    collector_version: "0.3.0",
    state: "current",
    reason: "collector_version_current",
    compatible: true,
    verified: true,
  }),
  "mid-outdated": expectedVersionView({
    collector_version: "0.2.0",
    state: "update_available",
    reason: "collector_version_behind_target",
    compatible: true,
    verified: true,
  }),
  "alpha-outdated": expectedVersionView({
    collector_version: "0.1.5",
    state: "update_available",
    reason: "collector_version_behind_target",
    compatible: true,
    verified: true,
  }),
  "gamma-legacy": expectedVersionView({
    collector_version: "0.0.9",
    state: "unsupported",
    reason: "collector_version_below_minimum",
    compatible: false,
    verified: true,
  }),
  "beta-ahead": expectedVersionView({
    collector_version: "0.4.0",
    rollback_target_version: "0.3.0",
    state: "rollback_available",
    reason: "collector_version_ahead_of_target",
    compatible: true,
    verified: true,
  }),
  "omega-silent": expectedVersionView({
    collector_version: null,
    state: "unknown",
    reason: "collector_release_missing",
    compatible: true,
    verified: false,
  }),
};

const EXPECTED_SERVER_BLOCK = {
  api_version: "1.0.0",
  read_model_version: "1.0.0",
  ingest_schema_version: 1,
  min_supported_collector_version: "0.1.0",
  target_collector_version: "0.3.0",
};

const EXPECTED_COUNTS = {
  current: 1,
  update_available: 2,
  unsupported: 1,
  rollback_available: 1,
  unknown: 1,
};

/** 严重度优先（unsupported < rollback_available < update_available < unknown），同级按 source_id 升序。 */
const EXPECTED_NEEDS_ATTENTION_ORDER = [
  "gamma-legacy",
  "beta-ahead",
  "alpha-outdated",
  "mid-outdated",
  "omega-silent",
];

describe.sequential("native TS Worker version read surface", () => {
  let mf: Miniflare;

  async function fetchJson(pathAndQuery: string): Promise<AnyRecord> {
    const response = await mf.dispatchFetch(`http://native.test${pathAndQuery}`, { headers: authHeaders });
    expect(response.status, `${pathAndQuery} must be readable`).toBe(200);
    return await response.json<AnyRecord>();
  }

  beforeEach(async () => {
    mf = await createMiniflare();
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await assertCollectorVersionColumn(db);
    await seedVersionFixture(db);
  });

  afterEach(async () => {
    await mf.dispose();
  });

  it("pins the version policy constants the seeded fixture versions are chosen against", () => {
    // 这条不是产品断言，是防呆：常量一变，下面所有 state 期望都要重挑版本号。
    expect(MIN_SUPPORTED_COLLECTOR_VERSION).toBe("0.1.0");
    expect(TARGET_COLLECTOR_VERSION).toBe("0.3.0");
  });

  it("exposes the full Python-equivalent version block on every /api/summary source_status entry", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const bySource = sourceStatusById(summary);

    expect([...bySource.keys()].sort()).toEqual(SOURCES.map((source) => source.source_id).sort());
    for (const [sourceId, expected] of Object.entries(EXPECTED_VERSION_VIEW)) {
      const entry = bySource.get(sourceId);
      expect(entry, `source_status must contain ${sourceId}`).toBeTruthy();
      const version = (entry as AnyRecord).version;
      expect(version, `${sourceId} must carry a version block`).toBeTruthy();
      // 字段集完整：少一个是丢口径，多一个是分叉。
      expect(Object.keys(version).sort(), `${sourceId} version field set`).toEqual(VERSION_VIEW_FIELDS);
      expect(version, `${sourceId} version block`).toEqual(expected);
      // `accepted` 只在服务端内部用于接受/拒绝写入，public_version_view 已剥掉，不得外泄。
      expect(version).not.toHaveProperty("accepted");
    }
  });

  it("decides all four version states plus the unknown degradation from the last accepted report", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const bySource = sourceStatusById(summary);
    const stateOf = (sourceId: string) => (bySource.get(sourceId) as AnyRecord)?.version?.state;

    expect(stateOf("zeta-current")).toBe("current");
    expect(stateOf("mid-outdated")).toBe("update_available");
    expect(stateOf("gamma-legacy")).toBe("unsupported");
    expect(stateOf("beta-ahead")).toBe("rollback_available");
    expect(stateOf("omega-silent")).toBe("unknown");

    // 不兼容必须同时体现在 compatible 上，不能只改 state 文案。
    expect((bySource.get("gamma-legacy") as AnyRecord).version.compatible).toBe(false);
    expect((bySource.get("beta-ahead") as AnyRecord).version.rollback_target_version).toBe("0.3.0");
  });

  it("never marks a source with no reported version as verified", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const silent = sourceStatusById(summary).get("omega-silent") as AnyRecord;

    expect(silent.version.state).toBe("unknown");
    expect(silent.version.collector_version).toBeNull();
    // verified 是「服务端核实过版本」的唯一开关：版本未知时**必须**是 false，
    // 不许用 undefined / null 蒙混，也不许因为 compatible 为 true 就当成合规。
    expect(silent.version.verified).toBe(false);
    expect(silent.version.reason).toBe("collector_release_missing");

    for (const [sourceId, entry] of sourceStatusById(summary)) {
      if (entry.version?.collector_version) continue;
      expect(entry.version?.verified, `${sourceId} has no reported version, must not be verified`).toBe(false);
    }
  });

  it("summarises every source version into a deterministic top-level version_health block", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const health = summary.version_health as AnyRecord;

    expect(health, "/api/summary must expose top-level version_health").toBeTruthy();
    expect(Object.keys(health).sort()).toEqual(["counts", "needs_attention", "server"]);
    expect(health.server).toEqual(EXPECTED_SERVER_BLOCK);
    expect(Object.keys(health.counts).sort(), "counts must cover every state").toEqual(ALL_VERSION_STATE_KEYS);
    expect(health.counts).toEqual(EXPECTED_COUNTS);
    // 排序是 (状态严重度, source_id)，与来源插入顺序、SQL 返回顺序都无关。
    expect((health.needs_attention as AnyRecord[]).map((row) => row.source_id))
      .toEqual(EXPECTED_NEEDS_ATTENTION_ORDER);
    // current 的来源不进 needs_attention。
    expect((health.needs_attention as AnyRecord[]).map((row) => row.source_id)).not.toContain("zeta-current");
  });

  it("keeps zero-count states in version_health when a filtered view only has current sources", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today&machine=zeta-box");
    const health = summary.version_health as AnyRecord;

    expect(health, "filtered /api/summary must still expose version_health").toBeTruthy();
    expect(health.counts).toEqual({
      current: 1,
      update_available: 0,
      unsupported: 0,
      rollback_available: 0,
      unknown: 0,
    });
    expect(health.needs_attention).toEqual([]);
  });

  it("lists an outdated device in needs_attention with every identity and version field filled in", async () => {
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const needsAttention = (summary.version_health as AnyRecord).needs_attention as AnyRecord[];
    const outdated = needsAttention.find((row) => row.source_id === "mid-outdated");

    expect(outdated, "a device behind the target version must need attention").toBeTruthy();
    expect(Object.keys(outdated as AnyRecord).sort()).toEqual(NEEDS_ATTENTION_FIELDS);
    expect(outdated).toEqual({
      source_id: "mid-outdated",
      display_name: "mid-box · bob",
      machine: "mid-box",
      os_user: "bob",
      status: "ok",
      observed_at: "2026-06-03T11:43:00+08:00",
      state: "update_available",
      collector_version: "0.2.0",
      release_channel: null,
      build_sha: null,
      reason: "collector_version_behind_target",
      compatible: true,
    });

    const unsupported = needsAttention.find((row) => row.source_id === "gamma-legacy");
    expect(unsupported).toEqual({
      source_id: "gamma-legacy",
      display_name: "gamma-box · dave",
      machine: "gamma-box",
      os_user: "dave",
      status: "provider_failed",
      observed_at: "2026-06-03T11:42:00+08:00",
      state: "unsupported",
      collector_version: "0.0.9",
      release_channel: null,
      build_sha: null,
      reason: "collector_version_below_minimum",
      compatible: false,
    });

    const silent = needsAttention.find((row) => row.source_id === "omega-silent");
    expect(silent).toEqual({
      source_id: "omega-silent",
      display_name: "omega-box · frank",
      machine: "omega-box",
      os_user: "frank",
      status: "ok",
      observed_at: "2026-06-03T11:44:00+08:00",
      state: "unknown",
      collector_version: null,
      release_channel: null,
      build_sha: null,
      reason: "collector_release_missing",
      compatible: true,
    });
  });

  it("reports the same version health from /api/health as the summary read model", async () => {
    const health = await fetchJson("/api/health");
    const summary = await fetchJson("/api/summary?date=2026-06-03&period=today");
    const versions = health.versions as AnyRecord;

    expect(versions, "/api/health must expose versions").toBeTruthy();
    expect(Object.keys(versions).sort()).toEqual(["counts", "needs_attention", "rejected_recent", "server"]);
    expect(versions.server).toEqual(EXPECTED_SERVER_BLOCK);
    expect(Object.keys(versions.counts).sort()).toEqual(ALL_VERSION_STATE_KEYS);
    expect(versions.counts).toEqual(EXPECTED_COUNTS);
    expect(versions.rejected_recent).toEqual([]);
    expect((versions.needs_attention as AnyRecord[]).map((row) => row.source_id))
      .toEqual(EXPECTED_NEEDS_ATTENTION_ORDER);
    for (const row of versions.needs_attention as AnyRecord[]) {
      expect(Object.keys(row).sort(), `${row.source_id} needs_attention field set`).toEqual(NEEDS_ATTENTION_FIELDS);
    }
    // 两个出口的版本判定核心仍是同一个 build_version_health 产物；只有健康端额外暴露
    // 写入拒绝观测，不能把服务端审计数据扩散进面向客户端的 summary 合同。
    const { rejected_recent: _rejectedRecent, ...versionCore } = versions;
    expect(versionCore).toEqual(summary.version_health);
  });
});

function sourceStatusById(summary: AnyRecord): Map<string, AnyRecord> {
  const rows = (summary.source_status ?? []) as AnyRecord[];
  return new Map(rows.map((row) => [String(row.source_id), row]));
}

async function createMiniflare(): Promise<Miniflare> {
  const bundleScript = await bundleWorker();
  return new Miniflare({
    modules: true,
    script: bundleScript,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_TIMEZONE: "Asia/Shanghai",
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_BACKEND_MODE: "native_d1_production",
    },
  });
}

async function bundleWorker(): Promise<string> {
  const outdir = path.join(tmpdir(), `aiusage-version-read-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  await mkdir(outdir, { recursive: true });
  const outfile = path.join(outdir, "index.mjs");
  await build({
    entryPoints: [workerEntry],
    outfile,
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    sourcemap: false,
  });
  return readFile(outfile, "utf8");
}

async function applySchema(db: D1Database): Promise<void> {
  const sql = (await readFile(schemaPath, "utf8"))
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
  for (const statement of sql.split(";")) {
    const trimmed = statement.trim();
    if (trimmed) await db.prepare(trimmed).run();
  }
}

/**
 * 本文件的 fixture 依赖 `collector_version` 列已经由 schema 建出来。
 *
 * 这里**只断言、不补列**。红测阶段曾经有过一版「列不存在就 ALTER 补上」的临时脚手架，
 * schema 落地后它变成 no-op，但留着有害：一旦哪天该列被从 migration 里删掉，
 * 补列逻辑会把这个 schema 回归自动兜住、掩盖成绿。缺列必须红，并指明是 schema 的问题。
 */
async function assertCollectorVersionColumn(db: D1Database): Promise<void> {
  const info = await db.prepare("PRAGMA table_info(source_report_states)").all<{ name: string }>();
  const columns = (info.results ?? []).map((row) => String(row.name));
  if (!columns.includes("collector_version")) {
    throw new Error(
      "source_report_states 缺少 collector_version 列，schema 回归了。"
        + `当前列：${columns.join(", ")}。`
        + "本文件不负责补列，请检查 cloudflare/migrations/0001_initial_schema.sql 与 0007。",
    );
  }
}

async function seedVersionFixture(db: D1Database): Promise<void> {
  await db.prepare(`
    INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status)
    VALUES (?, ?, ?, ?, ?)
  `).bind(1, "2026-06-03T11:45:00+08:00", "Asia/Shanghai", "0.3.0", "ok").run();

  for (const source of SOURCES) {
    await db.batch([
      db.prepare(`
        INSERT INTO source_identities (
          source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
      `).bind(
        source.source_id, source.machine, source.machine, source.os_user, source.platform,
        source.collected_at, source.collected_at,
      ),
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message, collector_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        source.source_id, source.collected_at, "daily", "HTTP Ingest", source.status, null,
        "2026-06-03", "2026-06-03", source.status === "ok" ? null : source.status,
        source.error_message, source.collector_version,
      ),
    ]);
  }

  // 少量真实用量，保证 summary 的其余分支正常成形；版本读模型本身不依赖用量。
  await db.batch([
    db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "zeta-current", "2026-06-03", "claude", 100, 150, 50, 0, 300, null,
      JSON.stringify({ machine: "zeta-box", account: "alice", platform: "darwin" }), "{}",
      "2026-06-03T11:45:00+08:00", "2026-06-03T11:45:00+08:00",
    ),
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "version-fact", "zeta-current", "zeta-box", "alice", "claude", "claude-alice", "claude", "test",
      "2026-06-03T11:00:00+08:00", "2026-06-03T12:00:00+08:00", "Asia/Shanghai",
      100, 150, 50, 0, 0, 300, null, 1, 1, "observed", "test",
      "2026-06-03T11:45:00+08:00", "2026-06-03T11:45:00+08:00",
    ),
  ]);
}

// Issue #58 阶段二在 Cloudflare Native Worker（生产权威实现）侧的版本合同。
//
// #74 之后口径唯一 owner 就是本目录的 src/version-contract.ts（Python 服务端判定已删除，
// 只留采集端自报半边）。本文件的期望值是从删除前的 Python 实现逐字继承的行为合同：
// 字段名、状态名、拒绝语义改动都必须是显式决策，不是重构副产品。
import { readFile, readdir } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { applySqlText } from "./golden/harness";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { evaluateCollectorRelease } from "../src/version-contract";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const token = "contract-test-token";
const fixedNow = "2026-06-03T12:00:00+08:00";

type AnyRecord = Record<string, any>;

function ingestPayload(overrides: AnyRecord = {}): AnyRecord {
  return {
    schema_version: 1,
    source_id: "mac-local",
    host: "macbook-pro",
    machine: "macbook-pro",
    os_user: "alice",
    platform: "darwin",
    timezone: "Asia/Shanghai",
    observed_at: "2026-06-03T11:30:00+08:00",
    collection_window: "daily",
    usage_daily: [],
    collection_status: "ok",
    error_type: null,
    error_message: null,
    ...overrides,
  };
}

describe.sequential("native TS Worker collector version contract", () => {
  // `_safe_key` 语义是「超长 或 不匹配正则」两个条件。正则允许 `a_b_c…` 无限
  // 拼接，所以长度上限不是冗余的：少了它，长 key 会原样回显进 400 响应体和服务端日志。
  // 这些期望值继承自删除前 Python owner 的 _safe_key 行为（#74 起本实现即权威）。
  it("redacts unknown keys per the contract inherited from the deleted Python owner", async () => {
    const cases: Array<[string, boolean]> = [
      ["collector", true],
      ["last_upgrade_status", true],
      ["aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbb", true],
      ["aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbbbb", false],
      ["aaaaaaaaaa_bbbbbbbbbb_cccccccccc_d", false],
      ["aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbbbb_cccc", false],
      ["AKIAIOSFODNN7EXAMPLE", false],
      ["sk-ant-api03-XYZ", false],
      ["/home/wangzp/.config/ai-usage", false],
    ];

    for (const [key, expectedEcho] of cases) {
      const response = await ingest(ingestPayload({ collector_release: { collector_version: "0.3.0", [key]: "v" } }));
      const body = await response.text();
      expect(response.status, `${key} must be rejected as an unknown key`).toBe(400);
      if (expectedEcho) {
        expect(body, `${key} is a safe key name and should be named`).toContain(key);
      } else {
        expect(body, `${key} must never be echoed back`).not.toContain(key);
        expect(body).toContain("<redacted>");
      }
    }
  });

  let mf: Miniflare;

  beforeEach(async () => {
    mf = await createMiniflare({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    await applySchema(await mf.getD1Database("AIUSAGE_DB"));
  });

  afterEach(async () => {
    await mf.dispose();
  });

  it("accepts an optional collector_release block and echoes the flattened version block", async () => {
    const response = await ingest(ingestPayload({
      collector_release: {
        collector_version: "0.3.0",
        config_schema_version: 1,
        parser_schema_version: 2,
        release_channel: "stable",
        build_sha: "0a1b2c3d4e5",
        last_upgrade: {
          status: "succeeded",
          from_version: "0.2.0",
          to_version: "0.3.0",
          finished_at: "2026-06-02T10:00:00+08:00",
        },
      },
    }));
    const body = await response.json<AnyRecord>();

    expect(response.status).toBe(200);
    expect(body.status).toBe("accepted");
    expect(body.version).toEqual({
      collector_version: "0.3.0",
      config_schema_version: 1,
      parser_schema_version: 2,
      release_channel: "stable",
      build_sha: "0a1b2c3d4e5",
      last_upgrade_status: "succeeded",
      last_upgrade_from_version: "0.2.0",
      last_upgrade_to_version: "0.3.0",
      last_upgrade_finished_at: "2026-06-02T10:00:00+08:00",
      min_supported_collector_version: "0.1.0",
      target_collector_version: "0.3.0",
      rollback_target_version: null,
      state: "current",
      reason: "collector_version_current",
      compatible: true,
      verified: true,
    });
  });

  it("degrades to unknown instead of failing when the collector reports no version", async () => {
    const response = await ingest(ingestPayload());
    const body = await response.json<AnyRecord>();

    expect(response.status).toBe(200);
    expect(body.version.state).toBe("unknown");
    expect(body.version.reason).toBe("collector_release_missing");
    expect(body.version.verified).toBe(false);
    expect(await tableCount("source_reports")).toBe(1);
  });

  it("keeps known fields and nulls the rest for a partial collector_release", async () => {
    const response = await ingest(ingestPayload({
      collector_release: { collector_version: "0.2.0" },
    }));
    const body = await response.json<AnyRecord>();

    expect(response.status).toBe(200);
    expect(body.version.state).toBe("update_available");
    expect(body.version.reason).toBe("collector_version_behind_target");
    expect(body.version.release_channel).toBeNull();
    expect(body.version.build_sha).toBeNull();
    expect(body.version.config_schema_version).toBeNull();
    expect(body.version.last_upgrade_status).toBeNull();
  });

  it("rejects an illegal collector_release value with an explicit schema error and writes nothing", async () => {
    for (const release of [
      "0.3.0",
      { collector_version: "not-a-version" },
      { collector_version: "0.3.0", release_channel: "nightly" },
      { collector_version: "0.3.0", build_sha: "zzz" },
      { collector_version: "0.3.0", surprise: "value" },
      { collector_version: "0.3.0", last_upgrade: { status: "maybe" } },
      { collector_version: "0.3.0", config_schema_version: "1" },
    ]) {
      const response = await ingest(ingestPayload({ collector_release: release }));
      const body = await response.json<AnyRecord>();

      expect(response.status, JSON.stringify(release)).toBe(400);
      expect(body.error_type, JSON.stringify(release)).toBe("http_schema_invalid");
    }
    expect(await tableCount("source_reports")).toBe(0);
    expect(await tableCount("collection_runs")).toBe(0);
  });

  it("rejects an unsupported collector with an explicit error instead of a silent 200", async () => {
    const response = await ingest(ingestPayload({
      collector_release: { collector_version: "0.0.9" },
    }));
    const body = await response.json<AnyRecord>();

    expect(response.status).toBe(400);
    expect(body.error_type).toBe("collector_version_unsupported");
    expect(body.message).toContain("0.0.9");
    expect(body.message).toContain("0.1.0");
    expect(body.message).toContain("未写入");
  });

  it("does not silently drop a rejected unsupported upload into the store", async () => {
    const response = await ingest(ingestPayload({
      collector_release: { collector_version: "0.0.9" },
      usage_hourly_facts: [{
        fact_id: "rejected-fact-1",
        agent: "claude",
        window_start: "2026-06-03T10:00:00+08:00",
        window_end: "2026-06-03T10:59:59+08:00",
        usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
        attribution_confidence: "account_exact",
        provenance: "ccusage_blocks",
      }],
    }));

    expect(response.status).toBe(400);
    for (const table of [
      "collection_runs",
      "source_reports",
      "source_report_states",
      "source_identities",
      "usage_hourly_facts",
    ]) {
      expect(await tableCount(table), table).toBe(0);
    }
  });

  it("rejects a collector whose schema versions are below the minimum", async () => {
    const config = await ingest(ingestPayload({
      collector_release: { collector_version: "0.3.0", config_schema_version: 0 },
    }));
    expect(config.status).toBe(400);
    expect((await config.json<AnyRecord>()).error_type).toBe("collector_version_unsupported");

    const parser = await ingest(ingestPayload({
      collector_release: { collector_version: "0.3.0", parser_schema_version: 0 },
    }));
    expect(parser.status).toBe(400);
    expect((await parser.json<AnyRecord>()).error_type).toBe("collector_version_unsupported");
  });

  it("stores the reported collector version verbatim and leaves it NULL when nothing was reported", async () => {
    await ingest(ingestPayload({
      source_id: "reported", host: "macbook-pro", machine: "macbook-pro", os_user: "alice",
      collector_release: { collector_version: "0.3.0" },
    }));
    await ingest(ingestPayload({
      source_id: "silent", host: "linux-dev", machine: "linux-dev", os_user: "bob",
      observed_at: "2026-06-03T11:31:00+08:00",
    }));

    const db = await mf.getD1Database("AIUSAGE_DB");
    const rows = await db.prepare(`
      SELECT r.source_id AS source_id, c.collector_version AS collector_version
      FROM source_reports r JOIN collection_runs c ON r.run_id = c.id
      ORDER BY r.source_id ASC
    `).all<{ source_id: string; collector_version: string | null }>();

    expect(rows.results).toEqual([
      { source_id: "reported", collector_version: "0.3.0" },
      // 没上报版本就必须留 NULL。写占位假值等于把「未知」伪装成「确认在跑 0.1.0」。
      { source_id: "silent", collector_version: null },
    ]);
  });

  it("never writes a placeholder collector version anywhere in the write model", async () => {
    // #126 目录化后必须读整个 write-model/ 目录：只读 barrel 时本断言恒真（守卫失明）。
    const writeModelDir = path.join(repoRoot, "cloudflare/native-worker/src/write-model");
    const moduleNames = (await readdir(writeModelDir)).sort();
    expect(moduleNames.length, "write-model/ 目录不该少于 7 个模块").toBeGreaterThanOrEqual(7);
    const pieces = [await readFile(path.join(repoRoot, "cloudflare/native-worker/src/write-model.ts"), "utf8")];
    for (const name of moduleNames) {
      pieces.push(await readFile(path.join(writeModelDir, name), "utf8"));
    }
    const writeModelSource = pieces.join("\n");

    // 结构下限：拼接结果必须真的包含 collection_runs 写入路径，否则「没匹配」毫无意义。
    expect(writeModelSource).toContain("INSERT INTO collection_runs");
    expect(writeModelSource).not.toMatch(/collection_runs[\s\S]{0,400}?"0\.1\.0"/);
  });

  it("orders needs_attention deterministically regardless of input order", async () => {
    const { buildVersionHealth } = await import("../src/version-contract");
    const rows = [
      { source_id: "s-unknown", display_name: "s-unknown", status: "ok", version: { state: "unknown" } },
      { source_id: "b-unsupported", display_name: "b-unsupported", status: "ok", version: { state: "unsupported" } },
      { source_id: "c-update", display_name: "c-update", status: "ok", version: { state: "update_available" } },
      { source_id: "a-rollback", display_name: "a-rollback", status: "ok", version: { state: "rollback_available" } },
      { source_id: "a-unsupported", display_name: "a-unsupported", status: "ok", version: { state: "unsupported" } },
      { source_id: "a-current", display_name: "a-current", status: "ok", version: { state: "current" } },
      { source_id: "a-update", display_name: "a-update", status: "ok", version: { state: "update_available" } },
    ];
    const expected = [
      "a-unsupported",
      "b-unsupported",
      "a-rollback",
      "a-update",
      "c-update",
      "s-unknown",
    ];

    const forward = buildVersionHealth(rows);
    const reverse = buildVersionHealth([...rows].reverse());

    expect(forward.needs_attention.map((row: AnyRecord) => row.source_id)).toEqual(expected);
    expect(reverse).toEqual(forward);
  });

  it("rejects a version value that hides behind a trailing newline", async () => {
    for (const release of [
      { collector_version: "0.3.0\n" },
      { collector_version: "0.3.0", build_sha: "cafebabe\n" },
      { collector_version: "0.3.0", last_upgrade: { finished_at: "2026-06-02T10:00:00+08:00\n" } },
    ]) {
      const response = await ingest(ingestPayload({ collector_release: release }));
      expect(response.status, JSON.stringify(release)).toBe(400);
      expect((await response.json<AnyRecord>()).error_type).toBe("http_schema_invalid");
    }
  });

  it("never leaks a token or an absolute path through any version field", async () => {
    const fakeToken = "sk-ant-api03-FAKEfakeFAKEfake0123456789";
    const fakePath = "/opt/ai-usage/releases/current/bin/collector";

    for (const value of [fakeToken, fakePath]) {
      const response = await ingest(ingestPayload({
        collector_release: { collector_version: value, build_sha: value },
      }));
      const rendered = await response.text();
      expect(response.status).toBe(400);
      expect(rendered).not.toContain(value);
    }
    // 纯字母数字、<= 32 字符的凭据形态也必须脱敏，不能因为「看起来像标识符」就原样回显。
    for (const key of [
      fakeToken,
      "AKIAIOSFODNN7EXAMPLE",
      "xoxbXXXXXXXXXXXXXXXXXXXXXXXX",
      "AIzaSyDUMMYdummyDUMMYdummy1234",
      "deadbeefcafe1234deadbeefcafe1234",
    ]) {
      const unknownKeyResponse = await ingest(ingestPayload({
        collector_release: { collector_version: "0.3.0", [key]: "1" },
      }));
      expect(unknownKeyResponse.status, key).toBe(400);
      expect(await unknownKeyResponse.text(), key).not.toContain(key);
    }

    const accepted = await ingest(ingestPayload({
      collector_release: { collector_version: "0.3.0", build_sha: "0a1b2c3d4e5" },
    }));
    const ingestBody = await accepted.text();
    const summary = await readSummary("/api/summary?date=2026-06-03&period=today");
    const health = await (await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Authorization: `Bearer ${token}` },
    })).json<AnyRecord>();

    const rendered = JSON.stringify({ ingest: JSON.parse(ingestBody), summary, health });
    expect(rendered).not.toContain(fakeToken);
    expect(rendered).not.toContain(fakePath);
    expect(rendered).toContain("0.3.0");
  });

  it("keeps an ordinary snake_case field name in the error so it stays actionable", async () => {
    const response = await ingest(ingestPayload({
      collector_release: { collector_version: "0.3.0", auth_token: "x" },
    }));

    expect(response.status).toBe(400);
    expect((await response.json<AnyRecord>()).message).toContain("auth_token");
  });

  async function ingest(payload: AnyRecord): Promise<Response> {
    return mf.dispatchFetch("http://native.test/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload),
    });
  }

  async function readSummary(requestPath: string): Promise<AnyRecord> {
    const response = await mf.dispatchFetch(`http://native.test${requestPath}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.status).toBe(200);
    return response.json<AnyRecord>();
  }

  async function tableCount(table: string): Promise<number> {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    return Number(row?.count ?? 0);
  }

});

async function bundleWorker(): Promise<string> {
  const outdir = path.join(tmpdir(), `aiusage-version-contract-${Date.now()}-${Math.random().toString(16).slice(2)}`);
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

async function createMiniflare(extraBindings: Record<string, string> = {}): Promise<Miniflare> {
  const bundleScript = await bundleWorker();
  return new Miniflare({
    modules: true,
    script: bundleScript,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
      ...extraBindings,
    },
  });
}

async function applySchema(db: D1Database): Promise<void> {
  await applySqlText(db, await readFile(schemaPath, "utf8"));
}

// #90 缺口块 13：两种「没有版本」必须判成**不同的 reason**。
//
// `read-model.ts:753-758` 的注释写明了这个区分：没有版本时传 `null`（整块省略）
// 而不是 `{collector_version: null}`，因为前者判成 `collector_release_missing`、
// 后者判成 `collector_version_missing`。0007 迁移后存量行的该列全是 NULL，
// 整块省略是**常态路径**。
//
// 实测：`collector_release_missing` 有三处覆盖，而 `collector_version_missing`
// **全仓零命中**——两条分支合并成一条不会有任何测试变红，而合并之后运维就分不清
// 「这台设备根本没上报版本块」和「上报了版本块但版本字段是空的」——
// 前者是老采集端，后者是采集端出了 bug，处置动作完全不同。
describe("两种「没有版本」不能混为一谈（#90 块 13）", () => {
  it("整块省略判 collector_release_missing，版本字段为空判 collector_version_missing", () => {
    const omitted = evaluateCollectorRelease(null);
    const emptyVersion = evaluateCollectorRelease({ collector_version: null });

    // 两条都必须落在 unknown 态——它们的区别在 reason，不在 state。
    expect(omitted.state, "整块省略是 unknown 态").toBe("unknown");
    expect(emptyVersion.state, "版本字段为空也是 unknown 态").toBe("unknown");

    expect(omitted.reason, "整块省略").toBe("collector_release_missing");
    expect(emptyVersion.reason, "上报了版本块但版本字段为空").toBe("collector_version_missing");
    // 结构下限：两个 reason 必须真的不同。合并成一条时上面两条会一起变红，
    // 但这一条把「必须可区分」这个意图直接写死。
    expect(omitted.reason, "两种缺失必须可区分").not.toBe(emptyVersion.reason);

    // 两条都不算已核验：把「没上报」读成「核验过且没问题」是最糟的一种。
    expect(omitted.verified, "整块省略不算已核验").toBe(false);
    expect(emptyVersion.verified, "版本字段为空不算已核验").toBe(false);
  });

  it("undefined 与 null 一样按整块省略处理", () => {
    // 采集端漏传与显式传 null 在 JSON 上是同一件事，判定不能不同。
    expect(evaluateCollectorRelease(undefined).reason).toBe("collector_release_missing");
  });
});

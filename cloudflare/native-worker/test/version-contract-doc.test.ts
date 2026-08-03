// 版本与升级合同文档的**服务端半边**守卫（Issue #90 块 2）。
//
// PM-6 决策（2026-08-03）：不放弃「文档与代码不一致会红」这条守卫，在 TS 侧新建。
//
// 拆分依据（#67 裁决清单第 4 条，`version_contract.py` 是拆分不是整体删除）：
//   - 采集端字段清单 + 上报路径 → **留 Python**（`tests/test_version_contract_doc.py`），
//     owner 是 `version_contract.py` 的采集端自报部分，`pusher.py` / `config.py` 在用。
//   - 服务端字段、四态词表与判定条件、排序权重、最低支持版本语义 → **本文件**，
//     owner 是 `cloudflare/native-worker/src/version-contract.ts`。
//   - 呈现端字段 → **本文件**。`data_contract_version` 的 owner 是 mobile DTO，
//     而 DTO owner 已随 #67 迁到 `cloudflare/native-worker/src/mobile-summary.ts`。
//   - 全文链接与凭据扫描 → 留 Python（全文级卫生，与服务端判定无关，不重复实现）。
//
// 并存期的已知重叠（给 #74 执行者）：Python 侧 `tests/test_version_contract_doc.py` 现在仍在
// 对着**Python 常量**守整个服务端半边，共 8 条 —— `test_server_field_inventory_*`、
// `test_presentation_field_inventory_*`、`test_state_reason_map_*`、`test_doc_documents_every_state_*`、
// `test_each_documented_state_lists_the_reasons_*`、`test_doc_records_the_deterministic_severity_order`、
// `test_min_supported_version_section_*`、`test_doc_points_at_code_as_the_source_of_truth_for_thresholds`；
// 另有 `test_every_version_field_points_at_an_owner_path_*` 横跨三张表（采集端半边要留）。
// 其中最后一条是本文件「阈值常量」那条的**更松版本**（全文 contains，删掉服务端表那一处照样绿）。
// 本轮一条都不动（#90 明确不执行 #74 的任何删除），它们随 #74 的服务端半边一起摘除。
//
// 这类测试的典型失效模式非常具体：**从文档解析出集合、再和代码常量比对时，
// 如果解析失败返回空集，「空集 == 空集」会照样通过。** 所以每条解析结果都配
// 确切条数下限，且代码常量本身也断言确切长度——两侧任何一侧塌成空都会红。
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ALL_VERSION_STATES,
  PRESENTATION_VERSION_FIELDS,
  SERVER_VERSION_FIELDS,
  UNSUPPORTED_ERROR_TYPE,
  VERSION_STATE_SEVERITY,
  evaluateCollectorRelease,
  normalizeCollectorRelease,
  type VersionPolicy,
} from "../src/version-contract";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const DOC = path.join(repoRoot, "docs/architecture/version-and-upgrade-contract.md");
const ARCHITECTURE_DOC = path.join(repoRoot, "docs/architecture/architecture.md");

/** 服务端判定权威。文档必须指到它，指回已冻结的 Python 模块就是过期。 */
const SERVER_AUTHORITY = "cloudflare/native-worker/src/version-contract.ts";
/** 呈现端 `data_contract_version` 的 owner：mobile DTO 已随 #67 迁到 Worker。 */
const PRESENTATION_DTO_OWNER = "cloudflare/native-worker/src/mobile-summary.ts";

const AUTHORITY_SECTION = "## 权威入口";
const FIELD_SECTION_SERVER = "### 服务端版本字段";
const FIELD_SECTION_PRESENTATION = "### 呈现端版本字段";
const STATE_SECTION = "## 四态判定规则";
const MIN_SUPPORTED_SECTION = "## 服务端最低支持采集端版本的语义";

// 结构下限。这些数字**刻意写死**：加一个版本字段、加一个状态都是合同变更，
// 必须同时改文档、改代码、改这里。只改其中两处会红，正是想要的效果。
const EXPECTED_SERVER_FIELD_COUNT = 5;
const EXPECTED_PRESENTATION_FIELD_COUNT = 3;
const EXPECTED_STATE_COUNT = 5;
const EXPECTED_REASON_COUNT = 9;

/**
 * 「权威入口」清单：文档指派的职责 → owner 路径 → 该 owner 里必须真的出现的符号。
 *
 * 最后一列不是装饰。本 PR 的第一版把「兼容判定与拒绝动作」指到了 `index.ts`——
 * 路径当然存在，但那个文件里只有 `buildVersionHealth` 一个引用，判定与拒绝其实在
 * `write-model.ts`。**只查「路径存在」的守卫对这种错完全瞎。**
 */
const AUTHORITY_ENTRIES = [
  {
    duty: "服务端版本字段口径、四态判定、最低支持版本策略",
    owner: SERVER_AUTHORITY,
    mustReference: ["evaluateCollectorRelease", "SERVER_VERSION_FIELDS"],
  },
  {
    duty: "采集端自报版本字段",
    owner: "src/ai_usage_widget/version_contract.py",
    mustReference: ["COLLECTOR_VERSION_FIELDS"],
  },
  {
    duty: "上报 payload 校验与敏感字段边界",
    owner: "cloudflare/native-worker/src/write-model.ts",
    mustReference: ["normalizeCollectorRelease"],
  },
  {
    duty: "兼容判定与拒绝动作",
    owner: "cloudflare/native-worker/src/write-model.ts",
    mustReference: ["evaluateCollectorRelease", "UNSUPPORTED_ERROR_TYPE"],
  },
  {
    // `buildVersionHealth` 一个符号不够：它在 `index.ts` 里也有（`/api/health` 那条）。
    // `version_health` 只在 `read-model.ts` 里出现，它才是把这条职责钉死的那个符号。
    duty: "来源健康读模型",
    owner: "cloudflare/native-worker/src/read-model.ts",
    mustReference: ["buildVersionHealth", "version_health"],
  },
  {
    duty: "`/api/health` 的 `versions` 块",
    owner: "cloudflare/native-worker/src/index.ts",
    mustReference: ["buildVersionHealth"],
  },
];
/**
 * 符号检查次数 = 2+1+1+2+2+1。它守的是「`AUTHORITY_ENTRIES` 被悄悄删条目」，
 * **不是**「文档解析塌空」——循环源是本文件的字面量，这一点与下面那个真下限不同级。
 */
const EXPECTED_AUTHORITY_SYMBOL_CHECKS = 9;
/**
 * 「权威入口」共 9 条：上面 6 条代码 owner + 3 条文档索引
 * （模块 owner 总表 / 接口索引 / 表结构索引，它们的可达性由 Python 侧的相对链接测试守）。
 * 这是对着**文档解析结果**的真下限：写死条数让「悄悄少一条」也红。
 */
const EXPECTED_AUTHORITY_BULLET_COUNT = 9;

/** 判定探针用的策略。不用默认策略，默认策略下 min == 0.1.0 构造不出 below_minimum。 */
const PROBE_POLICY: VersionPolicy = {
  min_supported_collector_version: "0.2.0",
  target_collector_version: "0.4.0",
  min_supported_config_schema_version: 1,
  min_supported_parser_schema_version: 2,
};

/** 每个状态对应的 reason。下面第一条用例用真实判定行为**反向验证这张表本身是真的**。 */
const STATE_REASONS: Record<string, string[]> = {
  current: ["collector_version_current"],
  update_available: ["collector_version_behind_target"],
  unsupported: [
    "collector_version_below_minimum",
    "config_schema_version_below_minimum",
    "parser_schema_version_below_minimum",
  ],
  rollback_available: ["last_upgrade_failed", "collector_version_ahead_of_target"],
  unknown: ["collector_release_missing", "collector_version_missing"],
};

const REASON_PROBES: Record<string, Record<string, unknown> | null> = {
  collector_version_current: { collector_version: "0.4.0" },
  collector_version_behind_target: { collector_version: "0.3.0" },
  collector_version_below_minimum: { collector_version: "0.1.0" },
  config_schema_version_below_minimum: { collector_version: "0.4.0", config_schema_version: 0 },
  parser_schema_version_below_minimum: { collector_version: "0.4.0", parser_schema_version: 1 },
  last_upgrade_failed: {
    collector_version: "0.4.0",
    last_upgrade: { status: "failed", from_version: "0.3.0" },
  },
  collector_version_ahead_of_target: { collector_version: "0.9.0" },
  collector_release_missing: null,
  collector_version_missing: { config_schema_version: 1 },
};

function readDoc(): string {
  return readFileSync(DOC, "utf8");
}

/** 取一个章节的正文：从标题下一行到下一个同级或更高级标题为止。 */
function section(text: string, heading: string): string {
  const lines = text.split("\n");
  const level = heading.length - heading.replace(/^#+/, "").length;
  const start = lines.findIndex((line) => line.trim().toLowerCase() === heading.toLowerCase());
  if (start < 0) throw new Error(`文档缺少章节: ${heading}`);
  const collected: string[] = [];
  for (const line of lines.slice(start + 1)) {
    const stripped = line.trim();
    if (stripped.startsWith("#")) {
      const currentLevel = stripped.length - stripped.replace(/^#+/, "").length;
      if (currentLevel <= level) break;
    }
    collected.push(line);
  }
  return collected.join("\n");
}

/** 不抛错的章节存在性探测。`section()` 缺章节时会抛，用它做断言拿不到清晰的失败原因。 */
function sectionExists(text: string, heading: string): boolean {
  return text.split("\n").some((line) => line.trim().toLowerCase() === heading.toLowerCase());
}

/**
 * 剥掉注释再判断符号是否出现。
 *
 * 不剥的话 `source.includes(symbol)` 会被注释里的一句提及糊弄过去——独立审查实测：
 * 把 `read-model.ts` 里 `buildVersionHealth` 的真实调用全删、只在注释里留一句
 * 「这里以前调用 buildVersionHealth」，用例照样绿。那样用例名说的「它真的承担被指派的职责」
 * 就高于实际强度。剥注释可能因为字符串里的 `//` `#` 产生误剥，但那只会让断言更严（变红），
 * 不会让它更松。
 */
function stripComments(source: string, ext: string): string {
  const lineMarker = ext === ".py" ? "#" : "//";
  const withoutBlocks = ext === ".py" ? source : source.replace(/\/\*[\s\S]*?\*\//g, "");
  return withoutBlocks
    .split("\n")
    .map((line) => {
      const index = line.indexOf(lineMarker);
      return index >= 0 ? line.slice(0, index) : line;
    })
    .join("\n");
}

/** 把无序列表拆成条目，续行并回它所属的那一条。 */
function bullets(sectionText: string): string[] {
  const items: string[] = [];
  for (const line of sectionText.split("\n")) {
    if (/^-\s/.test(line)) items.push(line.replace(/^-\s*/, "").trim());
    else if (items.length > 0 && /^\s+\S/.test(line)) items[items.length - 1] += ` ${line.trim()}`;
  }
  return items;
}

function tableRows(sectionText: string): string[][] {
  const rows: string[][] = [];
  for (const line of sectionText.split("\n")) {
    const stripped = line.trim();
    if (!stripped.startsWith("|") || !stripped.endsWith("|")) continue;
    const cells = stripped.slice(1, -1).split("|").map((cell) => cell.trim());
    // 分隔行（`| --- | --- |`）不是数据
    if (cells.every((cell) => cell.length > 0 && /^[-: ]+$/.test(cell))) continue;
    rows.push(cells);
  }
  return rows;
}

type FieldTable = { header: string[]; byField: Map<string, string[]> };

function fieldTable(sectionText: string): FieldTable {
  const rows = tableRows(sectionText);
  if (rows.length === 0) throw new Error("章节里没有表格");
  const header = rows[0].map((cell) => cell.toLowerCase());
  if (!header.includes("字段") || !header.includes("owner")) {
    throw new Error(`表头必须包含「字段」和「Owner」列，实际: ${JSON.stringify(rows[0])}`);
  }
  const fieldIndex = header.indexOf("字段");
  const byField = new Map<string, string[]>();
  for (const row of rows.slice(1)) byField.set(row[fieldIndex].replace(/`/g, "").trim(), row);
  return { header, byField };
}

function stateRows(): { header: string[]; rows: string[][] } {
  const rows = tableRows(section(readDoc(), STATE_SECTION));
  if (rows.length === 0) throw new Error("四态章节里没有表格");
  return { header: rows[0].map((cell) => cell.toLowerCase()), rows: rows.slice(1) };
}

describe("版本合同文档 · 服务端半边（#90 块 2）", () => {
  it("文档存在、被架构总文档引用，且本测试依赖的章节一个不少", () => {
    expect(existsSync(DOC), `缺少版本与升级架构决策文档: ${DOC}`).toBe(true);
    expect(readFileSync(ARCHITECTURE_DOC, "utf8")).toContain("version-and-upgrade-contract.md");

    // 章节标题被改名时，下面每条用例都会因为「缺少章节」抛错。这条用**不抛错**的探测
    // 先把缺哪一节说清楚，否则一次改名会产生四条失败原因完全相同的红，指不到真因。
    // （第一版这里用的是会抛错的 `section()`，注释描述的作用它根本没实现——独立审查抓到。）
    const text = readDoc();
    const required = [
      AUTHORITY_SECTION,
      FIELD_SECTION_SERVER,
      FIELD_SECTION_PRESENTATION,
      STATE_SECTION,
      MIN_SUPPORTED_SECTION,
    ];
    expect(required.filter((heading) => !sectionExists(text, heading))).toEqual([]);
    // 标题在、正文空同样要红：解析出空表时「一条都没查」会和「查了且全过」同色。
    expect(required.filter((heading) => section(text, heading).trim().length === 0)).toEqual([]);
  });

  it("「权威入口」清单里的每条 owner 都存在，且它真的承担被指派的职责", () => {
    const items = bullets(section(readDoc(), AUTHORITY_SECTION));
    expect(items.length).toBe(EXPECTED_AUTHORITY_BULLET_COUNT);

    let checked = 0;
    for (const entry of AUTHORITY_ENTRIES) {
      const bullet = items.find((item) => item.startsWith(entry.duty));
      expect(bullet, `「权威入口」里没有「${entry.duty}」这一条`).toBeDefined();
      expect(bullet, `「${entry.duty}」没有指到 ${entry.owner}`).toContain(`\`${entry.owner}\``);

      const ownerPath = path.join(repoRoot, entry.owner);
      expect(existsSync(ownerPath), `${entry.owner} 在仓库里不存在`).toBe(true);

      const source = stripComments(readFileSync(ownerPath, "utf8"), path.extname(entry.owner));
      for (const symbol of entry.mustReference) {
        expect(
          source.includes(symbol),
          `${entry.owner} 的**代码**里没有 ${symbol}（注释不算），它承担不了「${entry.duty}」`,
        ).toBe(true);
        checked += 1;
      }
    }
    expect(checked).toBe(EXPECTED_AUTHORITY_SYMBOL_CHECKS);
  });

  it("服务端字段表与代码常量完全相等（多一个少一个都红）", () => {
    const table = fieldTable(section(readDoc(), FIELD_SECTION_SERVER));

    expect(SERVER_VERSION_FIELDS.length).toBe(EXPECTED_SERVER_FIELD_COUNT);
    expect(table.byField.size).toBe(EXPECTED_SERVER_FIELD_COUNT);
    expect([...table.byField.keys()].sort()).toEqual([...SERVER_VERSION_FIELDS].sort());
  });

  it("呈现端字段表与代码常量完全相等（多一个少一个都红）", () => {
    const table = fieldTable(section(readDoc(), FIELD_SECTION_PRESENTATION));

    expect(PRESENTATION_VERSION_FIELDS.length).toBe(EXPECTED_PRESENTATION_FIELD_COUNT);
    expect(table.byField.size).toBe(EXPECTED_PRESENTATION_FIELD_COUNT);
    expect([...table.byField.keys()].sort()).toEqual([...PRESENTATION_VERSION_FIELDS].sort());
  });

  it("服务端与呈现端的每个字段都指认了仓库里真实存在的 owner 路径", () => {
    const text = readDoc();
    let checked = 0;
    for (const heading of [FIELD_SECTION_SERVER, FIELD_SECTION_PRESENTATION]) {
      const table = fieldTable(section(text, heading));
      const ownerIndex = table.header.indexOf("owner");
      for (const [field, row] of table.byField) {
        const owner = row[ownerIndex].replace(/`/g, "").trim();
        expect(owner, `${heading} / ${field} 没有指认 owner`).not.toBe("");
        expect(
          existsSync(path.join(repoRoot, owner)),
          `${heading} / ${field} 的 owner 路径在仓库里不存在: ${owner}`,
        ).toBe(true);
        checked += 1;
      }
    }

    // 结构下限：不写这条，表被解析成空时「一条都没查」和「全查过了」产生同一个绿。
    expect(checked).toBe(EXPECTED_SERVER_FIELD_COUNT + EXPECTED_PRESENTATION_FIELD_COUNT);
  });

  it("服务端字段的 owner 必须是 Worker 侧权威实现，不能停在已冻结的 Python 模块", () => {
    const table = fieldTable(section(readDoc(), FIELD_SECTION_SERVER));
    const ownerIndex = table.header.indexOf("owner");

    const owners = [...table.byField].map(([field, row]) => [field, row[ownerIndex].replace(/`/g, "").trim()]);

    expect(owners.length).toBe(EXPECTED_SERVER_FIELD_COUNT);
    expect(owners.map(([, owner]) => owner)).toEqual(
      Array(EXPECTED_SERVER_FIELD_COUNT).fill(SERVER_AUTHORITY),
    );
  });

  it("呈现端数据合同版本的 owner 必须是 Worker 侧 DTO，不能停在已冻结的 mobile_summary.py", () => {
    const table = fieldTable(section(readDoc(), FIELD_SECTION_PRESENTATION));
    const ownerIndex = table.header.indexOf("owner");
    const row = table.byField.get("data_contract_version");

    expect(row, "呈现端表里没有 data_contract_version 这一行").toBeDefined();
    expect(row![ownerIndex].replace(/`/g, "").trim()).toBe(PRESENTATION_DTO_OWNER);
  });

  it("本测试用的「状态 → reason」表由真实判定行为反向验证", () => {
    // 没有这一条，下面两条用例就退化成「文档和一张写死的表一致」——
    // 表本身写错时，文档跟着错也照样全绿。
    const allReasons = Object.values(STATE_REASONS).flat();
    expect(allReasons.length).toBe(EXPECTED_REASON_COUNT);
    expect(new Set(allReasons).size).toBe(EXPECTED_REASON_COUNT);
    expect([...Object.keys(REASON_PROBES)].sort()).toEqual([...allReasons].sort());

    let verified = 0;
    for (const [reason, probe] of Object.entries(REASON_PROBES)) {
      const release = normalizeCollectorRelease(probe);
      const result = evaluateCollectorRelease(release, PROBE_POLICY);
      expect(result.reason, `探针 ${reason} 没有产出预期 reason`).toBe(reason);
      const expectedStates = Object.entries(STATE_REASONS)
        .filter(([, reasons]) => reasons.includes(reason))
        .map(([state]) => state);
      expect([result.state], `reason ${reason} 的状态归属与代码不符`).toEqual(expectedStates);
      verified += 1;
    }
    expect(verified).toBe(EXPECTED_REASON_COUNT);
  });

  it("文档记录了全部状态，含 unknown 降级态", () => {
    const { header, rows } = stateRows();
    expect(header).toContain("状态");
    expect(header).toContain("判定条件");
    const documented = rows.map((row) => row[header.indexOf("状态")].replace(/`/g, "").trim());

    expect(ALL_VERSION_STATES.length).toBe(EXPECTED_STATE_COUNT);
    expect(documented.length).toBe(EXPECTED_STATE_COUNT);
    expect([...documented].sort()).toEqual([...ALL_VERSION_STATES].sort());
  });

  it("每个状态下文档写出了代码真实产出的 reason", () => {
    const { header, rows } = stateRows();
    const byState = new Map(
      rows.map((row) => [row[header.indexOf("状态")].replace(/`/g, "").trim(), row[header.indexOf("判定条件")]]),
    );

    let checked = 0;
    for (const [state, reasons] of Object.entries(STATE_REASONS)) {
      const condition = byState.get(state);
      expect(condition, `文档四态表里没有 ${state} 这一行`).toBeDefined();
      for (const reason of reasons) {
        expect(condition, `${state} 的判定条件里没写 ${reason}`).toContain(reason);
        checked += 1;
      }
    }
    expect(checked).toBe(EXPECTED_REASON_COUNT);
  });

  it("文档记录的排序权重与代码常量逐个相等", () => {
    const { header, rows } = stateRows();
    expect(header).toContain("排序权重");
    const stateIndex = header.indexOf("状态");
    const severityIndex = header.indexOf("排序权重");

    let checked = 0;
    for (const row of rows) {
      const state = row[stateIndex].replace(/`/g, "").trim();
      const documented = Number.parseInt(row[severityIndex].trim(), 10);
      expect(Number.isNaN(documented), `${state} 的排序权重不是整数: ${row[severityIndex]}`).toBe(false);
      expect(documented, `${state} 的排序权重与代码不符`).toBe(VERSION_STATE_SEVERITY[state]);
      checked += 1;
    }
    expect(checked).toBe(EXPECTED_STATE_COUNT);
    expect(Object.keys(VERSION_STATE_SEVERITY).length).toBe(EXPECTED_STATE_COUNT);
  });

  it("最低支持版本章节写明了是提示还是拒绝，并带上真实 error_type", () => {
    const sectionText = section(readDoc(), MIN_SUPPORTED_SECTION);

    for (const required of ["提示", "拒绝", UNSUPPORTED_ERROR_TYPE, "400", "不得无提示丢弃"]) {
      expect(sectionText, `最低支持版本章节缺少「${required}」`).toContain(required);
    }
  });

  it("两条阈值字段在文档里点名的常量，必须是权威实现里真实存在的导出", () => {
    // 第一版这条写成全文 `contains("MIN_SUPPORTED_COLLECTOR_VERSION")`，变异证明它是虚的：
    // 常量名在文档里出现两次，把服务端字段表那处删掉，另一处照样让断言绿。
    // 现在改成「在定义它的那一行里点名」+「点的名字在代码里真的导出了」。
    const table = fieldTable(section(readDoc(), FIELD_SECTION_SERVER));
    const source = readFileSync(path.join(repoRoot, SERVER_AUTHORITY), "utf8");
    const exported = new Set(
      [...source.matchAll(/^export const ([A-Z][A-Z0-9_]*)\b/gm)].map((match) => match[1]),
    );

    // 结构下限：正则解析塌成空集时，下面的 has() 会全假、看起来像「文档写错了」。
    // 用两个与文档无关的锚点证明「确实解析到了导出」。
    expect(exported.has("COLLECTOR_RELEASE_FIELD")).toBe(true);
    expect(exported.has("SERVER_API_VERSION")).toBe(true);

    const expectedConstants: Record<string, string> = {
      min_supported_collector_version: "MIN_SUPPORTED_COLLECTOR_VERSION",
      target_collector_version: "TARGET_COLLECTOR_VERSION",
    };
    let checked = 0;
    for (const [field, constantName] of Object.entries(expectedConstants)) {
      const row = table.byField.get(field);
      expect(row, `服务端字段表里没有 ${field} 这一行`).toBeDefined();
      const named = [...row!.join(" ").matchAll(/`([A-Z][A-Z0-9_]{3,})`/g)].map((match) => match[1]);
      expect(named, `${field} 这一行必须且只能点名一个阈值常量`).toEqual([constantName]);
      expect(exported.has(constantName), `${constantName} 在 ${SERVER_AUTHORITY} 里不是导出常量`).toBe(true);
      checked += 1;
    }
    expect(checked).toBe(Object.keys(expectedConstants).length);
  });
});

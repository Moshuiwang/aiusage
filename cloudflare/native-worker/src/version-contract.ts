// 版本合同：采集端 / 服务端版本字段口径、四态判定与最低支持版本策略。
//
// **服务端判定的唯一 owner 是本文件**（#67 决策，2026-08-02：服务端收敛为
// Cloudflare Worker + D1 单实现）。`src/ai_usage_widget/version_contract.py` 只保留
// 采集端自报部分（`pusher.py` / `config.py` 在用），它的服务端判定部分已冻结、随 #74 删除。
// 在两份实现并存期间，常量、状态名、字段名、判定优先级与拒绝语义仍必须逐字一致。
//
// 安全边界：所有版本字段都用收紧的字面量白名单校验（semver / 十六进制 SHA /
// 枚举 / ISO 时间戳）。token、绝对路径、命令行参数等形态无法通过校验，
// 因此不可能出现在任何版本字段或来源健康输出里。校验失败的错误信息
// **只报字段名，不回显值**，避免把疑似凭据写进响应或日志。

type AnyRecord = Record<string, unknown>;

// --- 四态与降级态 ------------------------------------------------------------

export const VERSION_STATE_CURRENT = "current";
export const VERSION_STATE_UPDATE_AVAILABLE = "update_available";
export const VERSION_STATE_UNSUPPORTED = "unsupported";
export const VERSION_STATE_ROLLBACK_AVAILABLE = "rollback_available";
export const VERSION_STATE_UNKNOWN = "unknown";

/** Issue #58 明确要求的四态。`unknown` 不属于四态，是「采集端没报版本」的降级态。 */
export const VERSION_STATES = [
  VERSION_STATE_CURRENT,
  VERSION_STATE_UPDATE_AVAILABLE,
  VERSION_STATE_UNSUPPORTED,
  VERSION_STATE_ROLLBACK_AVAILABLE,
] as const;

export const ALL_VERSION_STATES = [...VERSION_STATES, VERSION_STATE_UNKNOWN] as const;

/** 排序权重，数字越小越需要人工处理。用于来源健康列表的确定性排序。 */
export const VERSION_STATE_SEVERITY: Record<string, number> = {
  [VERSION_STATE_UNSUPPORTED]: 0,
  [VERSION_STATE_ROLLBACK_AVAILABLE]: 1,
  [VERSION_STATE_UPDATE_AVAILABLE]: 2,
  [VERSION_STATE_UNKNOWN]: 3,
  [VERSION_STATE_CURRENT]: 4,
};

// --- 采集端本机版本常量 ------------------------------------------------------

export const COLLECTOR_VERSION = "0.3.0";
export const COLLECTOR_PARSER_SCHEMA_VERSION = 3;
export const DEFAULT_RELEASE_CHANNEL = "stable";
export const RELEASE_CHANNELS = ["stable", "beta", "dev"] as const;
export const LAST_UPGRADE_STATUSES = ["never", "succeeded", "failed", "rolled_back"] as const;

// --- 服务端版本与兼容策略 ----------------------------------------------------

export const SERVER_API_VERSION = "1.0.0";
export const SERVER_READ_MODEL_VERSION = "1.0.0";
export const SERVER_INGEST_SCHEMA_VERSION = 1;
export const MIN_SUPPORTED_COLLECTOR_VERSION = "0.1.0";
export const TARGET_COLLECTOR_VERSION = COLLECTOR_VERSION;
export const MIN_SUPPORTED_CONFIG_SCHEMA_VERSION = 1;
export const MIN_SUPPORTED_PARSER_SCHEMA_VERSION = 1;

/** ingest payload 里承载采集端版本的顶层 key（wire 格式，嵌套 last_upgrade）。 */
export const COLLECTOR_RELEASE_FIELD = "collector_release";

/** wire 格式允许的 key，多一个都拒绝，避免任意数据借版本块夹带上来。 */
const COLLECTOR_RELEASE_WIRE_FIELDS = [
  "collector_version",
  "config_schema_version",
  "parser_schema_version",
  "release_channel",
  "build_sha",
  "last_upgrade",
];

const COLLECTOR_RELEASE_LAST_UPGRADE_FIELDS = [
  "status",
  "from_version",
  "to_version",
  "finished_at",
];

/** 内部规范化后的扁平字段名，也是 read model / 存储层使用的字段名。 */
export const COLLECTOR_VERSION_FIELDS = [
  "collector_version",
  "config_schema_version",
  "parser_schema_version",
  "release_channel",
  "build_sha",
  "last_upgrade_status",
  "last_upgrade_from_version",
  "last_upgrade_to_version",
  "last_upgrade_finished_at",
];

export const SERVER_VERSION_FIELDS = [
  "api_version",
  "read_model_version",
  "ingest_schema_version",
  "min_supported_collector_version",
  "target_collector_version",
];

/**
 * 呈现端版本字段（Mac / iPhone / Watch / Web），只定合同不实现客户端。
 *
 * 与 Python 侧 `PRESENTATION_VERSION_FIELDS` 一样，唯一消费者是文档合同测试
 * （`test/version-contract-doc.test.ts`）：它保证「文档里的呈现端字段表」和
 * 「代码声明的字段集合」不会各写一套。没有产品逻辑读它，这是刻意的。
 */
export const PRESENTATION_VERSION_FIELDS = [
  "app_version",
  "build_number",
  "data_contract_version",
];

/** 服务端判定「明确不兼容」后返回的错误类型。不是静默 200，也不是静默丢弃。 */
export const UNSUPPORTED_ERROR_TYPE = "collector_version_unsupported";

// --- 校验用字面量白名单 ------------------------------------------------------

const SEMVER_RE = /^\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][0-9A-Za-z][0-9A-Za-z.]{0,31})?$/;
const BUILD_SHA_RE = /^[0-9a-fA-F]{7,64}$/;
const TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
const MAX_SCHEMA_VERSION = 10000;
/**
 * 只有形态明确安全的 key 名才会出现在错误信息里；其余一律脱敏。
 * JSON key 是完全不受控的任意文本，直接回显等于把疑似凭据写进 HTTP 响应和日志。
 *
 * 这里只放行「普通 snake_case 字段名」形态：纯小写字母分段、单段不超过 16 字符、
 * 总长不超过 32。大小写混排、含数字、超长单段（AWS Access Key ID、Slack token、
 * 十六进制密钥等凭据形态）一律脱敏。与 Python 侧 `_SAFE_KEY_RE` 同一条规则。
 */
const SAFE_KEY_RE = /^[a-z]{1,16}(?:_[a-z]{1,16})*$/;
const MAX_SAFE_KEY_LENGTH = 32;
const REDACTED_KEY = "<redacted>";

/** 版本字段不符合合同。错误信息只包含字段名，不回显字段值。 */
export class VersionContractError extends Error {
  field: string;

  constructor(message: string, field: string) {
    super(message);
    this.field = field;
  }
}

/** 服务端的兼容策略。`min_*` 是拒绝线，`target_*` 是提示线。 */
export type VersionPolicy = {
  min_supported_collector_version: string;
  target_collector_version: string;
  min_supported_config_schema_version: number;
  min_supported_parser_schema_version: number;
};

export const DEFAULT_VERSION_POLICY: VersionPolicy = {
  min_supported_collector_version: MIN_SUPPORTED_COLLECTOR_VERSION,
  target_collector_version: TARGET_COLLECTOR_VERSION,
  min_supported_config_schema_version: MIN_SUPPORTED_CONFIG_SCHEMA_VERSION,
  min_supported_parser_schema_version: MIN_SUPPORTED_PARSER_SCHEMA_VERSION,
};

/** 按 semver 语义比较两个版本号，返回 -1 / 0 / 1。 */
export function compareVersions(left: string, right: string): number {
  return compareKeys(versionKey(left), versionKey(right));
}

/**
 * 把 wire 格式的 collector_release 块规范化成扁平字段。
 *
 * - `null` / 缺失 -> `null`（采集端没报版本，降级，不抛错）
 * - 非对象 / 未知 key / 不合法值 -> `VersionContractError`
 * - 缺字段 -> 该字段为 `null`，其余字段照常保留
 */
export function normalizeCollectorRelease(raw: unknown): AnyRecord | null {
  if (raw === null || raw === undefined) return null;
  if (!isPlainObject(raw)) {
    throw new VersionContractError(
      `${COLLECTOR_RELEASE_FIELD} must be an object`,
      COLLECTOR_RELEASE_FIELD,
    );
  }

  for (const key of Object.keys(raw)) {
    if (!COLLECTOR_RELEASE_WIRE_FIELDS.includes(key)) {
      const safeKey = safeKeyName(key);
      throw new VersionContractError(
        `${COLLECTOR_RELEASE_FIELD} does not accept unknown field: ${safeKey}`,
        `${COLLECTOR_RELEASE_FIELD}.${safeKey}`,
      );
    }
  }

  const normalized: AnyRecord = {};
  for (const field of COLLECTOR_VERSION_FIELDS) normalized[field] = null;
  normalized.collector_version = semverOrNull(
    raw.collector_version,
    `${COLLECTOR_RELEASE_FIELD}.collector_version`,
  );
  normalized.config_schema_version = schemaVersionOrNull(
    raw.config_schema_version,
    `${COLLECTOR_RELEASE_FIELD}.config_schema_version`,
  );
  normalized.parser_schema_version = schemaVersionOrNull(
    raw.parser_schema_version,
    `${COLLECTOR_RELEASE_FIELD}.parser_schema_version`,
  );
  normalized.release_channel = enumOrNull(
    raw.release_channel,
    RELEASE_CHANNELS,
    `${COLLECTOR_RELEASE_FIELD}.release_channel`,
  );
  normalized.build_sha = patternOrNull(
    raw.build_sha,
    BUILD_SHA_RE,
    `${COLLECTOR_RELEASE_FIELD}.build_sha`,
  );

  const lastUpgrade = raw.last_upgrade;
  if (lastUpgrade !== null && lastUpgrade !== undefined) {
    if (!isPlainObject(lastUpgrade)) {
      throw new VersionContractError(
        `${COLLECTOR_RELEASE_FIELD}.last_upgrade must be an object`,
        `${COLLECTOR_RELEASE_FIELD}.last_upgrade`,
      );
    }
    for (const key of Object.keys(lastUpgrade)) {
      if (!COLLECTOR_RELEASE_LAST_UPGRADE_FIELDS.includes(key)) {
        const safeKey = safeKeyName(key);
        throw new VersionContractError(
          `${COLLECTOR_RELEASE_FIELD}.last_upgrade does not accept unknown field: ${safeKey}`,
          `${COLLECTOR_RELEASE_FIELD}.last_upgrade.${safeKey}`,
        );
      }
    }
    normalized.last_upgrade_status = enumOrNull(
      lastUpgrade.status,
      LAST_UPGRADE_STATUSES,
      `${COLLECTOR_RELEASE_FIELD}.last_upgrade.status`,
    );
    normalized.last_upgrade_from_version = semverOrNull(
      lastUpgrade.from_version,
      `${COLLECTOR_RELEASE_FIELD}.last_upgrade.from_version`,
    );
    normalized.last_upgrade_to_version = semverOrNull(
      lastUpgrade.to_version,
      `${COLLECTOR_RELEASE_FIELD}.last_upgrade.to_version`,
    );
    normalized.last_upgrade_finished_at = patternOrNull(
      lastUpgrade.finished_at,
      TIMESTAMP_RE,
      `${COLLECTOR_RELEASE_FIELD}.last_upgrade.finished_at`,
    );
  }
  return normalized;
}

/**
 * 判定采集端版本状态。
 *
 * 判定优先级：`unsupported` > `rollback_available` > `update_available` > `current`。
 * 版本未知时返回 `unknown`：既不拒绝，也**不当成合规**（`verified` 为 false）。
 */
export function evaluateCollectorRelease(
  release: AnyRecord | null | undefined,
  policy?: VersionPolicy,
): AnyRecord {
  const active = policy ?? DEFAULT_VERSION_POLICY;
  const result: AnyRecord = {};
  for (const field of COLLECTOR_VERSION_FIELDS) result[field] = null;
  if (release !== null && release !== undefined) {
    for (const field of COLLECTOR_VERSION_FIELDS) result[field] = release[field] ?? null;
  }
  result.min_supported_collector_version = active.min_supported_collector_version;
  result.target_collector_version = active.target_collector_version;
  result.rollback_target_version = null;

  if (release === null || release === undefined) {
    return finish(result, VERSION_STATE_UNKNOWN, "collector_release_missing", false);
  }

  const collectorVersion = result.collector_version;
  if (!collectorVersion) {
    return finish(result, VERSION_STATE_UNKNOWN, "collector_version_missing", false);
  }

  if (compareVersions(String(collectorVersion), active.min_supported_collector_version) < 0) {
    return finish(result, VERSION_STATE_UNSUPPORTED, "collector_version_below_minimum");
  }

  const configSchemaVersion = result.config_schema_version;
  if (typeof configSchemaVersion === "number" && configSchemaVersion < active.min_supported_config_schema_version) {
    return finish(result, VERSION_STATE_UNSUPPORTED, "config_schema_version_below_minimum");
  }

  const parserSchemaVersion = result.parser_schema_version;
  if (typeof parserSchemaVersion === "number" && parserSchemaVersion < active.min_supported_parser_schema_version) {
    return finish(result, VERSION_STATE_UNSUPPORTED, "parser_schema_version_below_minimum");
  }

  if (result.last_upgrade_status === "failed" && result.last_upgrade_from_version) {
    result.rollback_target_version = result.last_upgrade_from_version;
    return finish(result, VERSION_STATE_ROLLBACK_AVAILABLE, "last_upgrade_failed");
  }

  const targetDelta = compareVersions(String(collectorVersion), active.target_collector_version);
  if (targetDelta > 0) {
    result.rollback_target_version = active.target_collector_version;
    return finish(result, VERSION_STATE_ROLLBACK_AVAILABLE, "collector_version_ahead_of_target");
  }
  if (targetDelta < 0) {
    return finish(result, VERSION_STATE_UPDATE_AVAILABLE, "collector_version_behind_target");
  }
  return finish(result, VERSION_STATE_CURRENT, "collector_version_current");
}

/** 把判定结果转成对外可见的版本块，去掉只在服务端内部用的接受/拒绝开关。 */
export function publicVersionView(result: AnyRecord): AnyRecord {
  const view: AnyRecord = {};
  for (const [key, value] of Object.entries(result)) {
    if (key !== "accepted") view[key] = value;
  }
  return view;
}

/** 明确不兼容时给采集端的可读理由。必须说清本次上报没有写入。 */
export function unsupportedMessage(result: AnyRecord): string {
  const reason = result.reason;
  const tail = "本次上报未写入，请升级采集端后重试";
  if (reason === "collector_version_below_minimum") {
    return `采集端版本 ${String(result.collector_version)} 低于服务端最低支持版本 `
      + `${String(result.min_supported_collector_version)}，${tail}`;
  }
  if (reason === "config_schema_version_below_minimum") {
    return `采集端配置 schema 版本 ${String(result.config_schema_version)} 低于服务端最低支持版本，${tail}`;
  }
  if (reason === "parser_schema_version_below_minimum") {
    return `采集端 parser schema 版本 ${String(result.parser_schema_version)} 低于服务端最低支持版本，${tail}`;
  }
  return `采集端版本与服务端不兼容，${tail}`;
}

/** 服务端自身的版本与兼容策略，用于诊断页和 /api/health。 */
export function serverVersionBlock(policy?: VersionPolicy): AnyRecord {
  const active = policy ?? DEFAULT_VERSION_POLICY;
  return {
    api_version: SERVER_API_VERSION,
    read_model_version: SERVER_READ_MODEL_VERSION,
    ingest_schema_version: SERVER_INGEST_SCHEMA_VERSION,
    min_supported_collector_version: active.min_supported_collector_version,
    target_collector_version: active.target_collector_version,
  };
}

/**
 * 汇总所有来源的版本状态，列出全部落后或不兼容设备。
 *
 * `needs_attention` 按 (状态严重度, source_id) 确定性排序，与输入顺序无关。
 */
export function buildVersionHealth(
  sourceStatus: AnyRecord[] | null | undefined,
  policy?: VersionPolicy,
): AnyRecord {
  const counts: Record<string, number> = {};
  for (const state of ALL_VERSION_STATES) counts[state] = 0;
  const needsAttention: AnyRecord[] = [];
  for (const entry of sourceStatus ?? []) {
    if (!isPlainObject(entry)) continue;
    const version = isPlainObject(entry.version) ? entry.version : {};
    let state = String(version.state ?? VERSION_STATE_UNKNOWN);
    if (!(state in counts)) state = VERSION_STATE_UNKNOWN;
    counts[state] += 1;
    if (state === VERSION_STATE_CURRENT) continue;
    needsAttention.push({
      source_id: String(pickTruthy(entry.source_id)),
      display_name: String(pickTruthy(entry.display_name, entry.source_id)),
      machine: entry.machine ?? null,
      os_user: entry.os_user ?? null,
      status: entry.status ?? null,
      observed_at: entry.observed_at ?? null,
      state,
      collector_version: version.collector_version ?? null,
      release_channel: version.release_channel ?? null,
      build_sha: version.build_sha ?? null,
      reason: version.reason ?? null,
      compatible: Object.prototype.hasOwnProperty.call(version, "compatible")
        ? Boolean(version.compatible)
        : state !== VERSION_STATE_UNSUPPORTED,
    });
  }
  needsAttention.sort((left, right) => {
    const severity = VERSION_STATE_SEVERITY[String(left.state)] - VERSION_STATE_SEVERITY[String(right.state)];
    if (severity !== 0) return severity;
    const leftId = String(left.source_id);
    const rightId = String(right.source_id);
    if (leftId === rightId) return 0;
    return leftId < rightId ? -1 : 1;
  });
  return {
    server: serverVersionBlock(policy),
    counts,
    needs_attention: needsAttention,
  };
}

// --- 内部工具 ---------------------------------------------------------------

function finish(result: AnyRecord, state: string, reason: string, verified = true): AnyRecord {
  result.state = state;
  result.reason = reason;
  result.compatible = state !== VERSION_STATE_UNSUPPORTED;
  result.accepted = state !== VERSION_STATE_UNSUPPORTED;
  result.verified = verified;
  return result;
}

type VersionKey = [number[], number, Array<[number, number, string]>];

/** 按 semver 优先级规则拆解版本号。build metadata（`+`）不参与比较。 */
function versionKey(value: string): VersionKey {
  const text = String(value ?? "");
  const dashIndex = text.indexOf("-");
  const hasDash = dashIndex >= 0;
  let core = hasDash ? text.slice(0, dashIndex) : text;
  const rest = hasDash ? text.slice(dashIndex + 1) : "";
  core = core.split("+")[0];
  const prerelease = hasDash ? rest.split("+")[0] : "";
  const parts: number[] = [];
  for (const chunk of core.split(".")) {
    parts.push(/^-?\d+$/.test(chunk.trim()) ? Number(chunk.trim()) : 0);
  }
  while (parts.length < 3) parts.push(0);
  const identifiers: Array<[number, number, string]> = prerelease
    ? prerelease.split(".").map(identifierKey)
    : [];
  // 有 prerelease 的版本优先级低于同号正式版；identifiers 逐段比较，
  // 段数多的一方在前缀相同时优先级更高。
  return [parts.slice(0, 3), identifiers.length ? 0 : 1, identifiers];
}

function identifierKey(identifier: string): [number, number, string] {
  // semver：纯数字段按数值比较，且优先级低于含字母的段。
  if (identifier.length > 0 && /^\d+$/.test(identifier)) return [0, Number(identifier), ""];
  return [1, 0, identifier];
}

function compareKeys(left: VersionKey, right: VersionKey): number {
  const core = compareSequence(left[0], right[0]);
  if (core !== 0) return core;
  if (left[1] !== right[1]) return left[1] > right[1] ? 1 : -1;
  return compareSequence(left[2], right[2]);
}

/** 复刻 Python 元组比较：逐位比较，前缀相同时短的一方更小。 */
function compareSequence(left: unknown[], right: unknown[]): number {
  const shared = Math.min(left.length, right.length);
  for (let index = 0; index < shared; index += 1) {
    const item = compareScalar(left[index], right[index]);
    if (item !== 0) return item;
  }
  if (left.length === right.length) return 0;
  return left.length > right.length ? 1 : -1;
}

function compareScalar(left: unknown, right: unknown): number {
  if (Array.isArray(left) && Array.isArray(right)) return compareSequence(left, right);
  if (left === right) return 0;
  return (left as number | string) > (right as number | string) ? 1 : -1;
}

function safeKeyName(key: unknown): string {
  const text = String(key);
  // 长度上限不能省：正则允许 `a_b_c…` 无限拼接，只靠它挡不住长 key。
  // Python 侧 `_safe_key` 是「超长 或 不匹配」两个条件，这里必须逐字一致，
  // 否则同一个未知 key 在两套实现上一个脱敏一个原样回显进 400 响应体。
  if (text.length > MAX_SAFE_KEY_LENGTH || !SAFE_KEY_RE.test(text)) {
    return REDACTED_KEY;
  }
  return text;
}

function semverOrNull(value: unknown, field: string): string | null {
  return patternOrNull(value, SEMVER_RE, field);
}

function patternOrNull(value: unknown, pattern: RegExp, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new VersionContractError(`${field} is not a valid version field value (value omitted)`, field);
  }
  return value;
}

function enumOrNull(value: unknown, allowed: readonly string[], field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !allowed.includes(value)) {
    throw new VersionContractError(
      `${field} must be one of: ${allowed.join(", ")} (value omitted)`,
      field,
    );
  }
  return value;
}

function schemaVersionOrNull(value: unknown, field: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean" || typeof value !== "number" || !Number.isInteger(value)) {
    throw new VersionContractError(`${field} must be an integer (value omitted)`, field);
  }
  if (value < 0 || value > MAX_SCHEMA_VERSION) {
    throw new VersionContractError(`${field} is out of the accepted range (value omitted)`, field);
  }
  return value;
}

function isPlainObject(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pickTruthy(...candidates: unknown[]): unknown {
  for (const candidate of candidates) {
    if (candidate) return candidate;
  }
  return "";
}

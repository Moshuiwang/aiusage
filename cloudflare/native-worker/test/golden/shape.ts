/**
 * #74 P1：合同记录的字段口径（易变字段抹除、shape 投影）与可读差异比对。
 *
 * 原来这份逻辑同时存在于 `tests/test_api_contract.py::_shape`、
 * `cloudflare/native-worker/test/parity.test.ts` 与 `web_surface.test.ts` 三处。
 * golden 的生成端与校验端只要各自持有一份，就会出现「两边一起错」的自洽结果，
 * 所以三处统一到这里。
 */

export type Shape = Record<string, unknown>;

/** 与运行时刻、临时目录、文件大小绑定的字段：重放必然不同，记录前统一抹掉。 */
export const volatileFields = new Set([
  "accepted_at",
  "generated_at",
  "mtime",
  "path",
  "size_bytes",
  "updated_at",
]);

/** 枚举字段：shape golden 里连值一起记，值变了必须变红。 */
export const enumFields = new Set([
  "client",
  "confidence",
  "error_type",
  "exists",
  "granularity",
  "id",
  "official",
  "period",
  "provider",
  "schema_version",
  "status",
  "success",
  "window",
]);

/** 百分比字段：整数值也必须记成 float，否则 78 与 78.25 在 shape 里会分成两种类型。 */
export const floatFields = new Set(["used_percent", "remaining_percent"]);

export function isVolatile(fieldName: string): boolean {
  return volatileFields.has(fieldName) || fieldName.endsWith("_path");
}

/** 值 golden：保留全部数值，只把易变字段替换成固定占位。 */
export function maskVolatile(value: unknown, fieldName = ""): unknown {
  if (isVolatile(fieldName)) return "<masked>";
  if (Array.isArray(value)) return value.map((item) => maskVolatile(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, maskVolatile(item, key)]),
    );
  }
  return value;
}

/** shape golden：非枚举标量只记类型不记值，用来守 API 的结构合同。 */
export function shape(value: unknown, fieldName = ""): Shape {
  if (isVolatile(fieldName)) {
    return { type: typeName(value, fieldName), value: "<masked>" };
  }
  if (Array.isArray(value)) {
    return {
      type: "array",
      length: value.length,
      items: uniqueShapes(value.map((item) => shape(item))),
    };
  }
  if (value !== null && typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    const keys = Object.keys(objectValue).sort();
    return {
      type: "object",
      keys,
      fields: Object.fromEntries(keys.map((key) => [key, shape(objectValue[key], key)])),
    };
  }
  if (enumFields.has(fieldName)) {
    return { type: typeName(value, fieldName), value };
  }
  return { type: typeName(value, fieldName) };
}

export function typeName(value: unknown, fieldName = ""): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "list";
  if (floatFields.has(fieldName) && typeof value === "number") return "float";
  switch (typeof value) {
    case "boolean":
      return "bool";
    case "number":
      return Number.isInteger(value) ? "int" : "float";
    case "string":
      return "str";
    default:
      return typeof value;
  }
}

export function uniqueShapes(shapes: Shape[]): Shape[] {
  const seen = new Set<string>();
  const result: Shape[] = [];
  for (const item of shapes) {
    const serialized = stableStringify(item);
    if (seen.has(serialized)) continue;
    seen.add(serialized);
    result.push(item);
  }
  return result;
}

export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
}

export function bodyContract(contentType: string, body: Buffer): Shape {
  if (contentType.includes("application/json")) {
    return { kind: "json", shape: shape(JSON.parse(body.toString("utf8"))) };
  }
  if (contentType.includes("text/html")) {
    return { kind: "html", present: body.length > 0 };
  }
  if (body.length > 0) return { kind: "text", present: true };
  return { kind: "empty", present: false };
}

const maxValueChars = 200;
const maxDiffsReported = 40;

/**
 * 逐字段比对，返回「差在哪个 record 的哪个字段」的可读清单。
 *
 * 差异种类刻意分开：「字段缺失」「多出字段」「数组长度不同」「值不同」各自单列，
 * 「字段存在但值是 null / 空数组」这类绕过路径不会被当成一致。
 */
export function diffPaths(committed: unknown, regenerated: unknown, jsonPath = "records"): string[] {
  if (isPlainObject(committed) && isPlainObject(regenerated)) {
    const diffs: string[] = [];
    for (const key of [...new Set([...Object.keys(committed), ...Object.keys(regenerated)])].sort()) {
      const child = `${jsonPath}.${key}`;
      if (!(key in committed)) {
        diffs.push(`${child}: golden 缺失该字段，Worker 现在会产出 ${brief(regenerated[key])}`);
      } else if (!(key in regenerated)) {
        diffs.push(`${child}: golden 里多出该字段，Worker 已不再产出（golden=${brief(committed[key])}）`);
      } else {
        diffs.push(...diffPaths(committed[key], regenerated[key], child));
      }
    }
    return diffs;
  }

  if (Array.isArray(committed) && Array.isArray(regenerated)) {
    const diffs: string[] = [];
    if (committed.length !== regenerated.length) {
      diffs.push(`${jsonPath}: 长度不同，golden=${committed.length} regenerated=${regenerated.length}`);
    }
    for (let index = 0; index < Math.min(committed.length, regenerated.length); index += 1) {
      diffs.push(...diffPaths(committed[index], regenerated[index], `${jsonPath}[${elementLabel(committed[index], index)}]`));
    }
    return diffs;
  }

  if (!Object.is(committed, regenerated) || kindOf(committed) !== kindOf(regenerated)) {
    return [`${jsonPath}: golden=${brief(committed)} regenerated=${brief(regenerated)}`];
  }
  return [];
}

export function formatDiffs(diffs: string[]): string {
  const shown = diffs.slice(0, maxDiffsReported);
  const lines = shown.map((line) => `  - ${line}`);
  if (diffs.length > shown.length) {
    lines.push(`  ...(另有 ${diffs.length - shown.length} 处差异未列出，共 ${diffs.length} 处)`);
  }
  return lines.join("\n");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function kindOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function elementLabel(element: unknown, index: number): string {
  if (isPlainObject(element)) {
    for (const key of ["name", "provider", "machine", "account", "date"]) {
      const value = element[key];
      if (typeof value === "string") return `${index}:${value}`;
    }
  }
  return String(index);
}

function brief(value: unknown): string {
  const text = stableStringify(value);
  return text.length > maxValueChars ? `${text.slice(0, maxValueChars)}...(共 ${text.length} 字符)` : text;
}

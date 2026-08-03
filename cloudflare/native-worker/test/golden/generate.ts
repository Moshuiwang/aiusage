/**
 * #74 P1：四份 golden 的**唯一**生成入口。
 *
 *     npm run cf:golden:gen
 *
 * 生成逻辑的 owner 是 `test/golden/` 下的收集器，本文件只负责把它们的产物写到磁盘——
 * 同一个行为只允许有一份实现，否则「生成」与「校验」会各自漂移，
 * 最后产出一对自洽的错误：测试全绿，守护范围已经悄悄缩小。
 *
 * 只有在 Worker 的输出**确实**要变时才跑它，跑完必须逐条复核 `git diff`：
 * golden 里改掉一个既有值，等于悄悄改掉一条验收标准。
 */

import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { collectApiContractRecords } from "./api-contract-golden";
import {
  apiContractGoldenPath,
  macosOwnerFixturePath,
  providerSlotsGoldenPath,
  repoRoot,
  valueGoldenPath,
} from "./paths";
import { collectProviderSlotsRecords, macosOwnerFixtureFrom } from "./provider-slots-golden";
import { collectValueGoldenRecords } from "./value-golden";

/**
 * 序列化口径与这几份 golden 历史上的写法保持一致：键名排序 + 非 ASCII 转义 + 2 空格缩进。
 *
 * 键名排序不是审美：不排序时读模型调一下字段顺序就会让整份 golden 变成一个巨大的 diff，
 * 真正的口径变化会淹在里面没人看得见。
 */
function serialize(records: unknown[]): string {
  const sorted = JSON.stringify(records, (_key, value) => {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
    const entries = Object.entries(value as Record<string, unknown>);
    entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return Object.fromEntries(entries);
  }, 2);
  // 逐个 UTF-16 码元转义，与 Python `ensure_ascii=True` 同口径（含代理对）。
  // 只碰 >= U+007F：缩进用的换行是 0x0A，控制字符在字符串里已被 JSON.stringify 转义过，
  // 用「非可打印 ASCII」做判据会把整份文件的换行也转义掉。
  let escaped = "";
  for (let index = 0; index < sorted.length; index += 1) {
    const code = sorted.charCodeAt(index);
    escaped += code < 0x7f ? sorted[index] : `\\u${code.toString(16).padStart(4, "0")}`;
  }
  return `${escaped}\n`;
}

async function writeJson(filePath: string, records: unknown[]): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, serialize(records), "utf8");
  console.log(`wrote ${records.length} records to ${path.relative(repoRoot, filePath)}`);
}

export async function generateGoldens(): Promise<void> {
  await writeJson(valueGoldenPath, await collectValueGoldenRecords());

  const providerSlots = await collectProviderSlotsRecords();
  await writeJson(providerSlotsGoldenPath, providerSlots);
  await writeJson(macosOwnerFixturePath, macosOwnerFixtureFrom(providerSlots));

  await writeJson(apiContractGoldenPath, await collectApiContractRecords());
}

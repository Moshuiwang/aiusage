import type { SourceIdentity } from "./shared";

/** #226: one server-owned display-name table. */
const machineNames = new Map<string, string>([
  ["wangzhipengdeMac-Mini.local", "Mac mini"],
  ["wangzhipengdeMac-Mini", "Mac mini"],
  ["wangzhipengdeMacBook-Air.local", "MacBook Air"],
  ["wangzhipengdeMacBook-Air", "MacBook Air"],
  ["tz", "TZ"],
]);

export function machineDisplayName(value: unknown): string {
  const name = typeof value === "string" ? value.trim() : "";
  if (!name) return "未知设备";
  return machineNames.get(name) ?? name.replace(/\.local$/, "");
}

function isIpAddress(value: string): boolean {
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value)) {
    return value.split(".").every((part) => String(Number(part)) === part && Number(part) <= 255);
  }
  if (!value.includes(":") || !/^[\da-f:.]+(?:%[\w.-]+)?$/i.test(value)) return false;
  try {
    new URL(`http://[${value.split("%", 1)[0]}]`);
    return true;
  } catch {
    return false;
  }
}

/** Historical IP names can be replaced once the same paired source reports a stable name. */
export function withStableMachineName<T extends Record<string, unknown>>(
  row: T,
  identities: Record<string, SourceIdentity>,
): T {
  const { source_id, machine_id, machine_name, os_user } = row;
  if (typeof source_id !== "string" || !Object.hasOwn(identities, source_id)) return row;
  if (typeof machine_id !== "string" || machine_name !== machine_id || !isIpAddress(machine_id)) return row;
  const identity = identities[source_id];
  const stableName = identity.machine?.trim();
  if (identity.platform !== "darwin" || !os_user || identity.os_user !== os_user || !stableName || isIpAddress(stableName)) {
    return row;
  }
  return { ...row, machine_id: stableName, machine_name: stableName };
}

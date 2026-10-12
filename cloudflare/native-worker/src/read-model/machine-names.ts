/** #226: one server-owned display-name table; identity and aggregation keys are unchanged. */
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

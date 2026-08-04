// #126：目录化拆分后的兼容入口。对外 import 面不变（index.ts 只认这里），
// 实现在 ./read-model/ 目录；owner 表以「read-model/ 目录」为准。
export type { Period, SummaryRequest } from "./read-model/shared";
export { buildMobile, buildSummary } from "./read-model/summary";
export { buildHealthSourceStatus } from "./read-model/source-status";

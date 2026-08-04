// #126：目录化拆分后的兼容入口。对外 import 面不变（index.ts 只认这里），
// 实现在 ./write-model/ 目录；owner 表以「write-model/ 目录」为准。
export { handleIngestWrite, handleLimitsWrite } from "./write-model/handlers";
export { WriteValidationError } from "./write-model/shared";

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fixedNow, token } from "./golden/paths";

const webSurfaceTestPath = fileURLToPath(new URL("./web_surface.test.ts", import.meta.url));

describe("合同常量单一事实源", () => {
  it("web_surface 不再本地重抄 token 与固定时刻", async () => {
    const source = await readFile(webSurfaceTestPath, "utf8");

    expect(source, "token 必须从 golden/paths 导入").not.toContain(JSON.stringify(token));
    expect(source, "fixedNow 必须从 golden/paths 导入").not.toContain(JSON.stringify(fixedNow));
  });
});

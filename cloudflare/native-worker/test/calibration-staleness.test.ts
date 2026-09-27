/** #183-a：`fitted_at` 过期判断——供 #183-b 接线时用来把过期系数降级成「—」。 */
import { describe, expect, it } from "vitest";
import { isStale } from "../src/calibration/staleness";

const NOW = new Date("2026-09-27T00:00:00Z");

describe("isStale", () => {
  it("刚拟合完（0 天前）不算过期", () => {
    expect(isStale("2026-09-27T00:00:00Z", NOW)).toBe(false);
  });

  it("2 天前不算过期", () => {
    expect(isStale("2026-09-25T00:00:00Z", NOW)).toBe(false);
  });

  it("3 天多 1 毫秒前不算过期（部署前审查 Must 1b：门槛从 3 天调到 4 天，给轮换节奏留缓冲）", () => {
    expect(isStale("2026-09-23T23:59:59.999Z", NOW)).toBe(false);
  });

  it("恰好 4 天前不算过期（边界是 >4 天，不是 ≥4 天）", () => {
    expect(isStale("2026-09-23T00:00:00Z", NOW)).toBe(false);
  });

  it("超过 4 天（4 天 1 毫秒前）算过期", () => {
    expect(isStale("2026-09-22T23:59:59.999Z", NOW)).toBe(true);
  });

  it("5 天前算过期", () => {
    expect(isStale("2026-09-22T00:00:00Z", NOW)).toBe(true);
  });

  it("支持自定义过期门槛（接线时如果需要跟设计文档不同的口径）", () => {
    expect(isStale("2026-09-26T00:00:00Z", NOW, 1)).toBe(false);
    expect(isStale("2026-09-25T00:00:00Z", NOW, 1)).toBe(true);
  });

  it("未来时间戳（fitted_at 在 now 之后，比如时钟偏移）不算过期", () => {
    expect(isStale("2026-09-28T00:00:00Z", NOW)).toBe(false);
  });
});

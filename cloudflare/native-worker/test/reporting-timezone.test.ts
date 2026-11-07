/**
 * #287：统计时区可配置（取代全栈写死的 Asia/Shanghai / +08:00）。
 *
 * 用户已移居 UTC+1（设备时区 Africa/Kinshasa）。写死北京时间时「今天」从本地 17:00 开始、
 * 小时趋势整体偏 7 小时。这里覆盖：默认（北京）输出逐字不变；UTC+1；带夏令时的时区。
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  configureReportingTimezone,
  dateAxis,
  formatDate,
  hourAxis,
  localDateFromWindowStart,
  localHourFromWindowStart,
  parseDateOnly,
  periodBounds,
  periodWindowBounds,
  shiftDate,
  toOffsetIso,
} from "../src/read-model/shared";

afterEach(() => configureReportingTimezone(undefined));

describe("默认时区保持北京时间（现有 golden 不变）", () => {
  it("输出逐字等于原来的 +08:00 写法", () => {
    configureReportingTimezone(undefined);
    expect(toOffsetIso(new Date("2026-11-07T23:30:00Z"))).toBe("2026-11-08T07:30:00+08:00");
    expect(periodWindowBounds("2026-11-07", "2026-11-07")).toEqual(["2026-11-07T00:00:00+08:00", "2026-11-08T00:00:00+08:00"]);
    expect(hourAxis("2026-11-07")[0]).toBe("2026-11-07T00:00:00+08:00");
    expect(hourAxis("2026-11-07")).toHaveLength(24);
  });
});

describe("UTC+1（Africa/Kinshasa）", () => {
  it("日界、小时与区间都按本地时间", () => {
    configureReportingTimezone("Africa/Kinshasa");
    const lateEvening = new Date("2026-11-07T23:30:00Z"); // 本地 11-08 00:30
    expect(toOffsetIso(lateEvening)).toBe("2026-11-08T00:30:00+01:00");
    expect(formatDate(lateEvening)).toBe("2026-11-08");
    expect(localDateFromWindowStart("2026-11-07T23:30:00Z")).toBe("2026-11-08");
    expect(localDateFromWindowStart("2026-11-07T16:30:00+08:00")).toBe("2026-11-07"); // 北京 16:30 = 本地 09:30
    expect(localHourFromWindowStart("2026-11-07T23:30:00Z")).toBe("2026-11-08T00:00:00+01:00");
    expect(periodWindowBounds("2026-11-07", "2026-11-07")).toEqual(["2026-11-07T00:00:00+01:00", "2026-11-08T00:00:00+01:00"]);
    expect(parseDateOnly("2026-11-07").toISOString()).toBe("2026-11-06T23:00:00.000Z");
    const axis = hourAxis("2026-11-07");
    expect(axis).toHaveLength(24);
    expect([axis[0], axis[23]]).toEqual(["2026-11-07T00:00:00+01:00", "2026-11-07T23:00:00+01:00"]);
  });
});

describe("夏令时（Europe/Berlin）", () => {
  it("春季切换日只有 23 个小时，区间端点各用当时的偏移", () => {
    configureReportingTimezone("Europe/Berlin");
    expect(parseDateOnly("2026-03-29").toISOString()).toBe("2026-03-28T23:00:00.000Z");
    expect(periodWindowBounds("2026-03-29", "2026-03-29")).toEqual(["2026-03-29T00:00:00+01:00", "2026-03-30T00:00:00+02:00"]);
    const axis = hourAxis("2026-03-29");
    expect(axis).toHaveLength(23);
    expect(axis.slice(1, 3)).toEqual(["2026-03-29T01:00:00+01:00", "2026-03-29T03:00:00+02:00"]);
  });

  it("日期加减是纯日历运算，不受 23/25 小时日影响", () => {
    configureReportingTimezone("Europe/Berlin");
    expect(shiftDate("2026-10-25", 1)).toBe("2026-10-26"); // 秋季 25 小时日
    expect(shiftDate("2026-03-29", -1)).toBe("2026-03-28");
    expect(shiftDate("2026-12-31", 1)).toBe("2027-01-01");
  });
});

describe("非法时区名", () => {
  it("回落北京时间而不是抛错拖垮请求", () => {
    configureReportingTimezone("Not/AZone");
    expect(toOffsetIso(new Date("2026-11-07T23:30:00Z"))).toBe("2026-11-08T07:30:00+08:00");
  });
});

describe("周期与日期轴是纯日历运算（审查探针复现）", () => {
  it.each(["Asia/Shanghai", "Africa/Kinshasa", "Europe/Berlin", "Pacific/Auckland"])("%s：today/week/month 区间与日期轴", (zone) => {
    configureReportingTimezone(zone);
    expect(periodBounds("2026-01-15", "today", 0)).toEqual(["today", "2026-01-15", "2026-01-15"]);
    expect(periodBounds("2026-03-30", "week")).toEqual(["week", "2026-03-24", "2026-03-30"]); // 滚动 7 天
    expect(periodBounds("2026-03-30", "week", 0)).toEqual(["week", "2026-03-30", "2026-03-30"]); // 周一
    expect(periodBounds("2026-03-29", "week", -1)).toEqual(["week", "2026-03-16", "2026-03-22"]);
    expect(periodBounds("2026-03-29", "month", -1)).toEqual(["month", "2026-02-01", "2026-02-28"]);
    expect(dateAxis("2026-03-27", "2026-03-30", [])).toEqual(["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"]);
    expect(dateAxis("2026-10-23", "2026-10-26", [])).toEqual(["2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"]);
  });
});

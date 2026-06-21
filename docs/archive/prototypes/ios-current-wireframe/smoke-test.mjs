import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = dirname(fileURLToPath(import.meta.url));

function read(name) {
  return readFileSync(join(root, name), "utf8");
}

const html = read("index.html");
const css = read("styles.css");
const js = read("app.js");

function assertOrder(source, labels, message) {
  const positions = labels.map((label) => source.indexOf(label));
  assert.ok(positions.every((position) => position >= 0), `${message}: missing label`);
  for (let index = 1; index < positions.length; index += 1) {
    assert.ok(positions[index - 1] < positions[index], message);
  }
}

for (const view of ["home", "sources", "breakdown", "limits"]) {
  assert.match(html, new RegExp(`data-view="${view}"`), `missing ${view} view`);
  assert.match(html, new RegExp(`data-tab="${view}"`), `missing ${view} tab`);
}

const tabbar = html.match(/<nav class="tabbar"[\s\S]*?<\/nav>/)?.[0] || "";
assertOrder(tabbar, ['data-tab="home"', 'data-tab="limits"', 'data-tab="breakdown"', 'data-tab="sources"'], "tab order should be home/limits/breakdown/sources");

for (const period of ["today", "week", "month"]) {
  assert.match(html, new RegExp(`data-period="${period}"`), `missing ${period} period control`);
}

assert.doesNotMatch(html + js, /data-period="all"/, "all period control should be removed");
assert.doesNotMatch(html + js, /title: "全部"/, "all period data should be removed");
assert.doesNotMatch(js, /const periods = \["today", "week", "month", "all"\]/, "swipe should only include today/week/month");
assert.match(js, /week: \{[\s\S]*trend: \[[\s\S]*\["周一"/, "week should use today-style bar data");
assert.match(js, /month: \{[\s\S]*trend: \[[\s\S]*\["05-07"/, "month should use daily bar data");
assert.match(js, /month: \{[\s\S]*trend: \[[\s\S]*\["06-05"/, "month should include latest daily bar");
assert.match(js, /date: wireframeData\.periods\.month\.trend[\s\S]*reverse\(\)/, "month date breakdown should be newest first");
assert.doesNotMatch(js, /\["第 1 周"/, "month should not aggregate by week");
assert.doesNotMatch(js, /\["第 2 周"/, "month should not aggregate by week");
assert.doesNotMatch(js, /\["第 3 周"/, "month should not aggregate by week");

const dimensionControl = html.match(/<div class="dimension-control"[\s\S]*?<\/div>/)?.[0] || "";
assertOrder(dimensionControl, ['data-dimension="date"', 'data-dimension="machine"', 'data-dimension="user"', 'data-dimension="model"', 'data-dimension="agent"'], "dimension order should be date/machine/user/model/agent");
assert.match(js, /dimension: "date"/, "breakdown should default to date");
assert.doesNotMatch(html + js, /data-dimension="account"|OS User/, "account dimension should be renamed to user");

for (const hook of [
  "trendCanvas",
  "breakdownList",
  "drilldownView",
  "limitReminder",
  "homeLimitWindows",
  "limitVariantPanel",
  "potionGauge",
  "agentLogo",
  "potionMeta",
  "subscription-name",
  "Claude 主账号",
  "Claude 备用账号",
  "Codex 主账号",
  "wireframeData",
]) {
  assert.match(html + js, new RegExp(hook), `missing ${hook}`);
}

assert.doesNotMatch(html + js, /data-limit-variant="cards"/, "cards variant should be removed");
assert.doesNotMatch(html + js, /data-limit-variant="timeline"/, "timeline variant should be removed");
assert.doesNotMatch(html, /id="limitsScore"/, "limits score should be removed");
assert.doesNotMatch(html, /id="limitCount"/, "limit count should be removed");
assert.doesNotMatch(html, /id="limitList"/, "duplicate limit list should be removed");
assert.doesNotMatch(html, /id="primaryLimit"/, "home limit usage summary should be removed");
assert.doesNotMatch(html, /id="healthText"/, "home source health card should be removed");
assert.doesNotMatch(html, /id="topSources"/, "home top sources card should be removed");
assert.doesNotMatch(html, /来源健康/, "home source health card should be removed");
assert.doesNotMatch(html, /主要来源/, "home top sources card should be removed");
assert.doesNotMatch(html, /额度窗口/, "home limits heading should be renamed");
assert.match(html, /刷新时间/, "refresh time heading missing");
assert.doesNotMatch(html, />额度状态</, "limits status heading should be removed");
assert.doesNotMatch(js, /<b>\$\{weekly\?\.remainingText/, "weekly percent should not render inside bottle");
assert.doesNotMatch(js, /<span>周<\/span>/, "weekly label should not render inside bottle");
assert.doesNotMatch(js, /<span>5h<\/span>/, "5h label should not render inside bottle");
assert.match(js, /统计时间：/, "statistics timestamp label missing");
assert.match(js, /刷新 \$\{weekly\?\.reset/, "weekly reset copy should say refresh");
assert.match(js, /Claude Max 5x/, "first Claude subscription missing");
assert.match(js, /Claude Pro/, "second Claude subscription missing");
assert.match(js, /ChatGPT Plus/, "Codex subscription missing");

assert.match(css, /--wire-bg:/, "missing wireframe color tokens");
assert.match(js, /function switchView/, "missing tab interaction");
assert.match(js, /function renderTrend/, "missing trend interaction");

console.log("ios-current-wireframe smoke OK");

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = dirname(fileURLToPath(import.meta.url));

function read(name) {
  return readFileSync(join(root, name), "utf8");
}

function assertOrder(source, labels, message) {
  const positions = labels.map((label) => source.indexOf(label));
  assert.ok(positions.every((position) => position >= 0), `${message}: missing item`);
  for (let index = 1; index < positions.length; index += 1) {
    assert.ok(positions[index - 1] < positions[index], message);
  }
}

const html = read("index.html");
const css = read("styles.css");
const js = read("app.js");
const all = `${html}\n${css}\n${js}`;

for (const file of ["styles.css", "app.js"]) {
  assert.match(html, new RegExp(file), `missing ${file}`);
}

for (const view of ["home", "limits", "breakdown", "sources"]) {
  assert.match(html, new RegExp(`data-view="${view}"`), `missing ${view} screen`);
  assert.match(html, new RegExp(`data-tab="${view}"`), `missing ${view} tab`);
}

const tabbar = html.match(/<nav class="tabbar"[\s\S]*?<\/nav>/)?.[0] || "";
assertOrder(tabbar, ['data-tab="home"', 'data-tab="limits"', 'data-tab="breakdown"', 'data-tab="sources"'], "tab order");

const dimensionControl = html.match(/<div class="dimension-tabs"[\s\S]*?<\/div>/)?.[0] || "";
assertOrder(dimensionControl, ['data-dimension="date"', 'data-dimension="machine"', 'data-dimension="user"', 'data-dimension="model"', 'data-dimension="agent"'], "dimension order");

for (const period of ["today", "week", "month"]) {
  assert.match(html, new RegExp(`data-period="${period}"`), `missing ${period} period`);
}

assert.doesNotMatch(all, /data-period="all"|全部|OS User|wire-card|dashed|quota-bottle/, "high fidelity should not keep removed wireframe affordances");
assert.match(js, /dimension: "date"/, "breakdown should default to Date");
assert.match(js, /month: \{[\s\S]*trend: \[[\s\S]*\["05-07"/, "month should keep daily trend");
assert.match(js, /date: hifiData\.periods\.month\.trend[\s\S]*reverse\(\)/, "month date breakdown should be newest first");
assert.match(css, /--surface:/, "missing high fidelity design token");
assert.match(css, /backdrop-filter:/, "missing iOS glass treatment");
assert.match(css, /quota-gauge/, "missing native-like quota gauge visual");
assert.match(css, /quota-progress/, "missing native-like quota progress visual");
assert.match(js, /function brandIcon/, "missing brand icon renderer");
assert.match(js, /brand-icon claude/, "missing Claude Code brand icon");
assert.match(js, /brand-icon codex/, "missing Codex brand icon");
assert.doesNotMatch(js, /ctx\.arc\(point\.x,\s*point\.y/, "bar chart should not add trend dots");
assert.doesNotMatch(js, /ctx\.strokeStyle = "#0a84ff"/, "bar chart should not draw a trend line");
assert.match(js, /function drawTrend/, "missing trend renderer");
assert.match(js, /function renderBreakdown/, "missing breakdown renderer");
assert.match(js, /function renderLimits/, "missing limits renderer");

console.log("ios-high-fidelity smoke OK");

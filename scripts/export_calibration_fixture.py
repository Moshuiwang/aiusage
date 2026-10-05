"""重新生成 ``cloudflare/native-worker/test/calibration_fixture.json``。

这份 fixture 是 #183-a（Worker 官方额度持续校准计算内核）离线测试用的真实数据快照，
快照截点为 2026-09-27T10:52Z。最初于 2026-09-27 导出；2026-10-06（#206 档位分族）因原始
导出已不在，按同一截点与口径从生产 D1（`aiusage-prod-db`）重新只读导出三条结果：

- `limit_window_history` → 官方额度读数（本脚本的 ``--lim`` 输入）
- `usage_hourly_facts` → 小时级 token 汇总（本脚本的 ``--facts`` 输入）
- `usage_hourly_models` → 小时 × 模型级 token 明细（本脚本的 ``--models`` 输入）

**fixture 一个字节都不许手写、不许手改**（AGENTS.md：手写 fixture 会和现实脱节，且脱节
方向正好是「实现者以为的样子」）。要更新它，只能重新导出三份原始查询结果再重跑本脚本
（截点过滤用 ``julianday`` 统一时区；D1 里的小时事实会被后续上报覆盖，截点所在的未结束
小时无法逐字节复现原快照，2026-10-06 重导出时 claude 2026-09-27 18:00 一小时即被修订）：

    cd cloudflare/native-worker
    npx wrangler d1 execute aiusage-prod-db --remote --json \\
      --command "SELECT source_id, provider, used_percent, reset_at, window_duration_minutes, \\
                        observed_at FROM limit_window_history WHERE window='week' \\
                 AND julianday(observed_at) <= julianday('2026-09-27T10:52:00Z')" > /tmp/lim.json
    npx wrangler d1 execute aiusage-prod-db --remote --json \\
      --command "SELECT fact_id, source_id, agent, window_start, window_end, input_tokens, \\
                        output_tokens, cache_creation_tokens, cache_read_tokens \\
                 FROM usage_hourly_facts \\
                 WHERE julianday(window_start) >= julianday('2026-09-14T00:00:00+08:00') \\
                   AND julianday(window_start) <= julianday('2026-09-27T10:52:00Z')" > /tmp/facts.json
    npx wrangler d1 execute aiusage-prod-db --remote --json \\
      --command "SELECT m.fact_id, m.model, m.input_tokens, m.output_tokens, m.cache_creation_tokens, \\
                        m.cache_read_tokens FROM usage_hourly_models m \\
                 JOIN usage_hourly_facts f ON f.fact_id = m.fact_id \\
                 WHERE julianday(f.window_start) >= julianday('2026-09-14T00:00:00+08:00') \\
                   AND julianday(f.window_start) <= julianday('2026-09-27T10:52:00Z')" > /tmp/models.json
    python3 scripts/export_calibration_fixture.py \\
      --lim /tmp/lim.json --facts /tmp/facts.json --models /tmp/models.json \\
      --out cloudflare/native-worker/test/calibration_fixture.json

本脚本做三件事，都是**脱敏 + 聚合**，不做任何拟合或校准计算（计算逻辑的唯一 owner 是
``cloudflare/native-worker/src/calibration/``）：

1. **脱敏**：`source_id` 映射成 `source-a` / `source-b` / ...（按首次出现顺序），
   丢弃一切机器名 / 主机名 / 用户名字段，只保留时间、provider/agent、模型族、
   token 各类型计数与官方额度读数。
2. **模型 → 族映射**：与 `src/calibration/constants.ts` 里的 `familyForModel` 规则保持一致
   （子串匹配，见下方 ``FAMILY_MATCHERS``；两处改动必须同步，否则 fixture 的族划分会跟
   内核实际使用的族划分脱钩）。映射不到任何已知族的模型（deepseek、antigravity 下的
   `unknown` 等）不计入任何已知族，但**仍然**计入 `usage_hourly_models` 的完整性合计
   （见下一条），因为它们是「有模型行、只是不追踪这个族」，不是「缺模型行」。
3. **unattributed 完整性补齐**：每条小时事实的 token 总量减去它所有 model 行的合计，
   差额（缺 model 行时是全额）落到伪族 `unattributed` 上——数据完整性核查发现部分来源
   （Codex mac-local 9/14–9/20、linux-biai-wangzp）大量缺 model 行，这个差额必须显式带进
   fixture，否则内核测不到「unattributed 占比过高要剔除区间」这条规则。

聚合粒度是 provider × model_family × window_start × window_end：同一小时同一族如果被
多个来源各报了一次，在这里加总（内核不区分 token 是哪个来源产生的，只区分账户 = provider）。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

TOKEN_TYPES = ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"]
UNATTRIBUTED_FAMILY = "unattributed"

# 必须与 cloudflare/native-worker/src/calibration/constants.ts 的 FAMILY_MATCHERS 保持一致。
FAMILY_MATCHERS: dict[str, list[tuple[str, "callable"]]] = {
    "claude": [
        ("opus", lambda m: "opus" in m),
        ("sonnet", lambda m: "sonnet" in m),
        ("haiku", lambda m: "haiku" in m),
        ("fable", lambda m: "fable" in m),
    ],
    "codex": [
        ("review", lambda m: "review" in m),
        ("astra", lambda m: "astra" in m),
        ("sol", lambda m: "-sol" in m),
        ("luna", lambda m: "luna" in m),
        ("terra", lambda m: "terra" in m),
    ],
    "antigravity": [
        ("flash", lambda m: "flash" in m),
        ("pro", lambda m: "pro" in m),
        ("claude-on-antigravity", lambda m: "claude" in m),
    ],
}


def family_for_model(provider: str, model_name: str) -> str | None:
    lower = model_name.lower()
    for family, match in FAMILY_MATCHERS.get(provider, []):
        if match(lower):
            return family
    return None


def load_results(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data[0]["results"]


def anonymize_source_ids(lim_rows: list[dict], fact_rows: list[dict]) -> dict[str, str]:
    seen: dict[str, str] = {}
    letters = "abcdefghijklmnopqrstuvwxyz"

    def register(sid: str) -> None:
        if sid not in seen:
            seen[sid] = f"source-{letters[len(seen)]}"

    for r in lim_rows:
        register(r["source_id"])
    for r in fact_rows:
        register(r["source_id"])
    return seen


def build_limit_observations(lim_rows: list[dict], source_map: dict[str, str]) -> list[dict]:
    out = []
    for r in lim_rows:
        out.append({
            "source_id": source_map[r["source_id"]],
            "provider": r["provider"],
            "observed_at": r["observed_at"],
            "reset_at": r["reset_at"],
            "used_percent": r["used_percent"],
            "window_duration_minutes": r["window_duration_minutes"],
        })
    return out


def build_hourly_family_facts(fact_rows: list[dict], model_rows: list[dict]) -> list[dict]:
    models_by_fact: dict[str, list[dict]] = defaultdict(list)
    for m in model_rows:
        models_by_fact[m["fact_id"]].append(m)

    # (provider, family, window_start, window_end) -> token type -> total
    agg: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    dropped_unmapped_models = 0
    facts_missing_model_rows = 0

    for f in fact_rows:
        provider = f["agent"]
        window_start = f["window_start"]
        window_end = f["window_end"]
        model_rows_for_fact = models_by_fact.get(f["fact_id"], [])
        if not model_rows_for_fact:
            facts_missing_model_rows += 1

        model_sum = {t: 0.0 for t in TOKEN_TYPES}
        for m in model_rows_for_fact:
            for t in TOKEN_TYPES:
                model_sum[t] += float(m.get(t) or 0)
            family = family_for_model(provider, m["model"])
            if family is None:
                dropped_unmapped_models += 1
                continue
            key = (provider, family, window_start, window_end)
            for t in TOKEN_TYPES:
                agg[key][t] += float(m.get(t) or 0)

        unattributed = {t: max(0.0, float(f.get(t) or 0) - model_sum[t]) for t in TOKEN_TYPES}
        if any(v > 0 for v in unattributed.values()):
            key = (provider, UNATTRIBUTED_FAMILY, window_start, window_end)
            for t in TOKEN_TYPES:
                agg[key][t] += unattributed[t]

    print(
        f"[export_calibration_fixture] facts_missing_model_rows={facts_missing_model_rows} "
        f"dropped_unmapped_model_rows={dropped_unmapped_models} (计入 unattributed 完整性合计，但不计入任何已知族)"
    )

    out = []
    for (provider, family, window_start, window_end), totals in sorted(agg.items()):
        out.append({
            "provider": provider,
            "model_family": family,
            "window_start": window_start,
            "window_end": window_end,
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_creation_tokens": totals["cache_creation_tokens"],
            "cache_read_tokens": totals["cache_read_tokens"],
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lim", required=True, type=Path, help="limit_window_history 的 wrangler --json 导出")
    parser.add_argument("--facts", required=True, type=Path, help="usage_hourly_facts 的 wrangler --json 导出")
    parser.add_argument("--models", required=True, type=Path, help="usage_hourly_models 的 wrangler --json 导出")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "cloudflare/native-worker/test/calibration_fixture.json",
    )
    args = parser.parse_args()

    lim_rows = load_results(args.lim)
    fact_rows = load_results(args.facts)
    model_rows = load_results(args.models)

    source_map = anonymize_source_ids(lim_rows, fact_rows)
    limit_observations = build_limit_observations(lim_rows, source_map)
    hourly_family_facts = build_hourly_family_facts(fact_rows, model_rows)

    fixture = {
        "_comment": (
            "由 scripts/export_calibration_fixture.py 生成，禁止手改。"
            "来源：aiusage-prod-db 截点 2026-09-27T10:52Z 的只读导出（limit_window_history / "
            "usage_hourly_facts / usage_hourly_models），2026-10-06 按同一截点重导出。重新生成见脚本头注释。"
        ),
        "limit_observations": limit_observations,
        "hourly_family_facts": hourly_family_facts,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[export_calibration_fixture] wrote {args.out} "
          f"({len(limit_observations)} limit_observations, {len(hourly_family_facts)} hourly_family_facts, "
          f"{len(source_map)} anonymized sources)")


if __name__ == "__main__":
    main()

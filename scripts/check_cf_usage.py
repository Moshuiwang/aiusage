#!/usr/bin/env python3
"""
Cloudflare 免费额度预算与用量巡检脚本
用于日常巡检、发布新版本后回归检查，确保 Workers、D1、R2 不超标。
符合 AGENTS.md 安全规范：不输出、不记录凭据与敏感密钥。
"""

import os
import re
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

ACCOUNT_ID = "419a1b80106632c3f0dd7aeccaebb6eb"
SCRIPT_NAME = "aiusage-api"
D1_DATABASE_ID = "be19e4de-4fa3-446c-8028-0d31ff0bb9f2"
R2_BUCKET_NAME = "aiusage-backups"

# Cloudflare 免费版每日/每月硬上限
FREE_LIMITS = {
    "worker_requests_per_day": 100_000,
    "worker_cpu_ms_per_request": 10.0,
    "d1_rows_read_per_day": 5_000_000,
    "d1_rows_written_per_day": 100_000,
    "d1_db_size_mb": 500.0,
    "r2_storage_gb": 10.0,
}

# #190 第 3 项：D1 24h rows_read / rows_written 判定阈值，与 check_status 的百分比口径一致。
D1_WARN_PCT = 50.0
D1_CRITICAL_PCT = 80.0


def build_d1_analytics_query() -> str:
    """`d1AnalyticsAdaptiveGroups` GraphQL 查询：24h 窗口内某个 database 的
    读/写行数总量（`sum.readQueries`/`sum.writeQueries` 是查询次数，
    `sum.rowsRead`/`sum.rowsWritten` 才是计费用的行数——D1 免费额度按行数算，
    不是按查询次数算，取错字段会把用量算小几个数量级）。"""
    return """
    query GetD1Usage($accountTag: String!, $databaseId: String!, $start: String!, $end: String!) {
      viewer {
        accounts(filter: {accountTag: $accountTag}) {
          d1AnalyticsAdaptiveGroups(
            limit: 1000
            filter: {databaseId: $databaseId, datetime_geq: $start, datetime_leq: $end}
          ) {
            sum { readQueries writeQueries rowsRead rowsWritten }
          }
        }
      }
    }
    """


def parse_d1_rows_read_written(response_json):
    """从 `d1AnalyticsAdaptiveGroups` GraphQL 响应里解析 24h rows_read / rows_written。

    拿不到就返回 (None, None)——调用方必须把 None 当"未知"处理，不能当 0 用
    （0 意味着"确实没读写"，未知意味着"不知道"，两者混淆会把"没查到数据"误判成
    "用量是零"，进而误判成"安全"）。

    GraphQL 一个 database 24h 内可能被分成多条 adaptive group 记录（按时间桶），
    要把它们的 sum 加总，不能只取第一条。任一分组缺该字段（缺失或 null）则该指标整体
    未知；响应带顶层 errors 时数据不可确认，两项都未知。
    """
    try:
        if response_json.get("errors"):
            return None, None
        accounts = response_json.get("data", {}).get("viewer", {}).get("accounts", [])
        if not accounts:
            return None, None
        groups = accounts[0].get("d1AnalyticsAdaptiveGroups", [])
        if not groups:
            return None, None
        sums = [group.get("sum") or {} for group in groups]

        def total(field):
            values = [summed.get(field) for summed in sums]
            if any(value is None for value in values):
                return None
            return sum(int(value) for value in values)

        return total("rowsRead"), total("rowsWritten")
    except (AttributeError, TypeError, ValueError, KeyError):
        return None, None


def d1_usage_percentages(rows_read, rows_written):
    """(rows_read, rows_written) -> (read_pct, write_pct)，None 原样传递（"未知"）。"""
    read_pct = None if rows_read is None else (rows_read / FREE_LIMITS["d1_rows_read_per_day"]) * 100
    write_pct = None if rows_written is None else (rows_written / FREE_LIMITS["d1_rows_written_per_day"]) * 100
    return read_pct, write_pct


def overall_conclusion(percentages):
    """按"最差项"给结论；percentages 里任意一项是 None（未知）都必须体现在结论里，
    不能因为其余指标都健康就宣称"全部安全"——D1 读写是本项目最容易触顶的指标
    （见 .claude/rules/cloudflare.md），拿不到它时"安全"这个结论本身就不成立。

    返回 (conclusion_text, has_unknown, has_critical, has_warning)，方便测试分别断言
    文案与判定逻辑，而不是只断言一句拼好的话（结构下限）。
    """
    known = [pct for pct in percentages.values() if pct is not None]
    has_unknown = any(pct is None for pct in percentages.values())
    has_critical = any(pct >= D1_CRITICAL_PCT for pct in known)
    has_warning = any(pct >= D1_WARN_PCT for pct in known)

    if has_critical:
        text = "⚠️ 结论: 警告！存在用量接近或超过 80% 免费上限的资源，需紧急优化！"
    elif has_warning:
        text = "💡 结论: 关注！部分资源用量已过半，建议排查高频调用或优化批次。"
    elif has_unknown:
        text = "❓ 结论: 未知！部分指标（D1 读写）无法确认，不能判定为全部安全，请人工核实。"
    else:
        text = "✅ 结论: 正常！所有 Cloudflare 核心资源用量均在安全绿色区间内。"
    return text, has_unknown, has_critical, has_warning

def get_cloudflare_token():
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if api_token:
        return api_token
    config_path = os.path.expanduser("~/Library/Preferences/.wrangler/config/default.toml")
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'oauth_token\s*=\s*"([^"]+)"', content)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None

def query_cf_api(url, token, data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(url, headers=headers, data=json.dumps(data).encode("utf-8") if data else None)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def format_num(n):
    return f"{n:,}"

def check_status(pct):
    if pct >= 80:
        return "🔴 严重警报 (>=80%)"
    if pct >= 50:
        return "🟡 重点关注 (>=50%)"
    return "🟢 安全正常 (<50%)"

def main():
    token = get_cloudflare_token()
    if not token:
        print("❓ Cloudflare 用量未知：未配置 CLOUDFLARE_API_TOKEN 或本机 Wrangler 登录凭据，未执行巡检。")
        sys.exit(2)

    now = datetime.now(timezone.utc)
    t_24h_ago = now - timedelta(days=1)
    t_7d_ago = now - timedelta(days=7)

    print("=" * 70)
    print(" Cloudflare 免费版用量与预算巡检报告 (Cloudflare Free Tier Budget Audit)")
    print(f" 巡检时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S 本地')})")
    print("=" * 70)

    # 1. Workers 指标 (GraphQL)
    graphql_url = "https://api.cloudflare.com/client/v4/graphql"
    query = """
    query GetWorkersUsage($accountTag: String!, $scriptName: String!, $start24h: String!, $start7d: String!, $end: String!) {
      viewer {
        accounts(filter: {accountTag: $accountTag}) {
          dayUsage: workersInvocationsAdaptive(
            limit: 1000
            filter: {
              scriptName: $scriptName
              datetime_geq: $start24h
              datetime_leq: $end
            }
          ) {
            sum { requests errors subrequests }
            quantiles { cpuTimeP50 cpuTimeP90 cpuTimeP99 }
          }
          weekUsage: workersInvocationsAdaptive(
            limit: 1000
            filter: {
              scriptName: $scriptName
              datetime_geq: $start7d
              datetime_leq: $end
            }
          ) {
            sum { requests errors subrequests }
            quantiles { cpuTimeP50 cpuTimeP90 cpuTimeP99 }
          }
        }
      }
    }
    """
    variables = {
        "accountTag": ACCOUNT_ID,
        "scriptName": SCRIPT_NAME,
        "start24h": t_24h_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start7d": t_7d_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": now.strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    worker_day_req = 0
    worker_day_err = 0
    worker_cpu_p50 = 0
    worker_week_req = 0
    try:
        gql_res = query_cf_api(graphql_url, token, {"query": query, "variables": variables})
        accounts = gql_res.get("data", {}).get("viewer", {}).get("accounts", [])
        if accounts:
            day_data = accounts[0].get("dayUsage", [])
            if day_data:
                worker_day_req = day_data[0].get("sum", {}).get("requests", 0)
                worker_day_err = day_data[0].get("sum", {}).get("errors", 0)
                worker_cpu_p50 = (day_data[0].get("quantiles", {}).get("cpuTimeP50", 0)) / 1000.0 # µs -> ms
            week_data = accounts[0].get("weekUsage", [])
            if week_data:
                worker_week_req = week_data[0].get("sum", {}).get("requests", 0)
    except Exception as e:
        print(f"⚠️ Workers 监控获取失败: {e}")

    # 2. D1 数据库指标
    d1_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{D1_DATABASE_ID}"
    d1_size_bytes = 0
    d1_num_tables = 0
    try:
        d1_res = query_cf_api(d1_url, token)
        result = d1_res.get("result", {})
        d1_size_bytes = result.get("file_size", 0)
        d1_num_tables = result.get("num_tables", 0)
    except Exception as e:
        print(f"⚠️ D1 信息获取失败: {e}")

    d1_size_mb = d1_size_bytes / (1024 * 1024)

    # 3. D1 24h 读写查询（#190 第 3 项：GraphQL d1AnalyticsAdaptiveGroups）。
    d1_rows_read, d1_rows_written = None, None
    try:
        d1_variables = {
            "accountTag": ACCOUNT_ID,
            "databaseId": D1_DATABASE_ID,
            "start": t_24h_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        d1_analytics_res = query_cf_api(
            graphql_url, token, {"query": build_d1_analytics_query(), "variables": d1_variables}
        )
        d1_rows_read, d1_rows_written = parse_d1_rows_read_written(d1_analytics_res)
    except Exception as e:
        print(f"⚠️ D1 24h 读写用量获取失败: {e}")
    if d1_rows_read is None or d1_rows_written is None:
        print("❓ D1 读写未知：GraphQL d1AnalyticsAdaptiveGroups 未返回可用数据，无法判定 D1 24h rows_read/rows_written 是否安全。")
    d1_read_pct, d1_write_pct = d1_usage_percentages(d1_rows_read, d1_rows_written)

    # 4. R2 存储
    r2_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/r2/buckets/{R2_BUCKET_NAME}/usage"
    r2_size_bytes = 0
    r2_objects = 0
    try:
        r2_res = query_cf_api(r2_url, token)
        r2_res_data = r2_res.get("result", {})
        r2_size_bytes = int(r2_res_data.get("payloadSize", 0))
        r2_objects = int(r2_res_data.get("objectCount", 0))
    except Exception as e:
        print(f"⚠️ R2 信息获取失败: {e}")
    r2_size_gb = r2_size_bytes / (1024 * 1024 * 1024)

    # 打印汇总表格
    print("\n[1] Workers 指标 (aiusage-api):")
    req_pct = (worker_day_req / FREE_LIMITS["worker_requests_per_day"]) * 100
    print(f"  - 24h 请求量: {format_num(worker_day_req)} / {format_num(FREE_LIMITS['worker_requests_per_day'])} ({req_pct:.2f}%) -> {check_status(req_pct)}")
    print(f"  - 7d 请求总量: {format_num(worker_week_req)} (日均 {worker_week_req // 7} 次)")
    print(f"  - 24h 报错数: {worker_day_err} 次")
    print(f"  - P50 CPU 耗时: {worker_cpu_p50:.2f} ms (上限: {FREE_LIMITS['worker_cpu_ms_per_request']} ms)")

    print("\n[2] D1 数据库存储 (aiusage-prod-db):")
    db_size_pct = (d1_size_mb / FREE_LIMITS["d1_db_size_mb"]) * 100
    print(f"  - 表数量: {d1_num_tables} 张")
    print(f"  - 存储空间: {d1_size_mb:.2f} MB / {FREE_LIMITS['d1_db_size_mb']} MB ({db_size_pct:.2f}%) -> {check_status(db_size_pct)}")
    if d1_rows_read is None:
        print("  - 24h rows_read: 未知（D1 读写未知，见上方警告）")
    else:
        print(f"  - 24h rows_read: {format_num(d1_rows_read)} / {format_num(FREE_LIMITS['d1_rows_read_per_day'])} ({d1_read_pct:.2f}%) -> {check_status(d1_read_pct)}")
    if d1_rows_written is None:
        print("  - 24h rows_written: 未知（D1 读写未知，见上方警告）")
    else:
        print(f"  - 24h rows_written: {format_num(d1_rows_written)} / {format_num(FREE_LIMITS['d1_rows_written_per_day'])} ({d1_write_pct:.2f}%) -> {check_status(d1_write_pct)}")

    print("\n[3] R2 备份桶存储 (aiusage-backups):")
    r2_pct = (r2_size_gb / FREE_LIMITS["r2_storage_gb"]) * 100
    print(f"  - 备份对象数: {r2_objects} 个")
    print(f"  - 存储空间: {r2_size_gb * 1024:.2f} MB / {FREE_LIMITS['r2_storage_gb'] * 1024:.0f} MB ({r2_pct:.2f}%) -> {check_status(r2_pct)}")

    print("\n" + "=" * 70)
    # 总体评估：D1 读写纳入判定——结论按最差项，D1 读写未知时不得判定为"全部安全"。
    conclusion, _has_unknown, _has_critical, _has_warning = overall_conclusion({
        "worker_requests": req_pct,
        "d1_db_size": db_size_pct,
        "r2_storage": r2_pct,
        "d1_rows_read": d1_read_pct,
        "d1_rows_written": d1_write_pct,
    })
    print(conclusion)
    print("=" * 70)

if __name__ == "__main__":
    main()

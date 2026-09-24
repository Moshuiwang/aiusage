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

def get_oauth_token():
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
    token = get_oauth_token()
    if not token:
        print("⚠️ 未找到本地 Wrangler OAuth 凭据（~/.wrangler）。若在非 Mac/非生产机环境，请回 Mac 侧执行。")
        sys.exit(0)

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

    # 3. D1 24h 读写查询 (wrangler d1 info 解析或直接输出)
    d1_size_mb = d1_size_bytes / (1024 * 1024)

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
    print("  * 注: 24h 读写行数可通过 `npx wrangler d1 info aiusage-prod-db` 查询（读上限 5M/天，写上限 100k/天）")

    print("\n[3] R2 备份桶存储 (aiusage-backups):")
    r2_pct = (r2_size_gb / FREE_LIMITS["r2_storage_gb"]) * 100
    print(f"  - 备份对象数: {r2_objects} 个")
    print(f"  - 存储空间: {r2_size_gb * 1024:.2f} MB / {FREE_LIMITS['r2_storage_gb'] * 1024:.0f} MB ({r2_pct:.2f}%) -> {check_status(r2_pct)}")

    print("\n" + "=" * 70)
    # 总体评估
    max_pct = max(req_pct, db_size_pct, r2_pct)
    if max_pct >= 80:
        print("⚠️ 结论: 警告！存在用量接近或超过 80% 免费上限的资源，需紧急优化！")
    elif max_pct >= 50:
        print("💡 结论: 关注！部分资源用量已过半，建议排查高频调用或优化批次。")
    else:
        print("✅ 结论: 正常！所有 Cloudflare 核心资源用量均在安全绿色区间内。")
    print("=" * 70)

if __name__ == "__main__":
    main()

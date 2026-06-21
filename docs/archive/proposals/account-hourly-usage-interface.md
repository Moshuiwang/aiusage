# Interface Design: Account Hourly Usage

## 目标

接口设计要让终端只上传结构化小时事实，服务端负责存储和聚合，展示端只读 API。

接口必须支持三层归因：

- 机器。
- OS 登录用户。
- AI 登录账号。

## Terminology

| 字段 | 含义 |
| --- | --- |
| `source_id` | 一个采集源的稳定 ID |
| `machine_id` | 机器稳定标识 |
| `machine_name` | UI 展示机器名 |
| `os_user` | 机器登录用户 |
| `agent` | `codex` / `claude_code` |
| `ai_account_id` | AI 账号稳定 ID，可以是 hash 或 provider id |
| `ai_account_label` | UI 展示账号，例如邮箱 |
| `attribution_confidence` | AI 账号归因可信度 |

## HTTP Ingest

新小时事实优先扩展现有 ingest 链路，不默认绕开现有 Web / iPhone 读取路径。

- 服务端可以先在现有 ingest endpoint 中接受 `usage_hourly_facts`。
- 如果需要新 endpoint，`POST /api/usage/hourly` 必须作为 versioned 扩展，并同步接入现有 `/api/summary` 和 `/api/mobile/summary`。
- 迁移期 UI 只读现有 summary 输出，不能出现“新数据已上报但用户看不到”的状态。
- 走现有 `/ingest` 时必须保留当前 top-level `host` / `machine` / `os_user` / `platform` 字段；嵌套 `device` 只能作为兼容扩展或未来新 endpoint 的 shape。

### Endpoint

优先接入现有 ingest endpoint：

```http
POST /ingest
Authorization: Bearer <token>
Content-Type: application/json
```

如果后续需要 usage 专用 endpoint，才新增：

```http
POST /api/usage/hourly
Authorization: Bearer <token>
Content-Type: application/json
```

### Request

```json
{
  "schema_version": 1,
  "source_id": "macbook-wang-codex",
  "host": "MacBook-Pro.local",
  "machine": "MacBook Pro",
  "os_user": "wangzhipeng",
  "platform": "darwin",
  "observed_at": "2026-06-11T14:30:00+08:00",
  "timezone": "Asia/Shanghai",
  "collector": {
    "name": "ai-usage-widget",
    "version": "0.2.0"
  },
  "device": {
    "machine_id": "macbook-pro-local",
    "machine_name": "MacBook Pro",
    "host": "MacBook-Pro.local",
    "platform": "darwin",
    "os_user": "wangzhipeng"
  },
  "usage_hourly_facts": [
    {
      "fact_id": "codex:codex:macbook-wang-codex:2026-06-11T13:00:00+08:00:2026-06-11T14:00:00+08:00:account_observed_usage_inferred:openai:acct_hash_or_provider_id:codex_token_events",
      "agent": "codex",
      "client": "codex",
      "window_start": "2026-06-11T13:00:00+08:00",
      "window_end": "2026-06-11T14:00:00+08:00",
      "ai_account": {
        "provider": "openai",
        "account_id": "acct_hash_or_provider_id",
        "label": "startimessocietegn@gmail.com",
        "display_name": "StarTimes",
        "subscription": null
      },
      "usage": {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 800,
        "reasoning_output_tokens": 30,
        "total_tokens": 2000
      },
      "model_breakdowns": [
        {
          "model": "gpt-5-codex",
          "input_tokens": 1000,
          "output_tokens": 200,
          "cache_creation_tokens": 0,
          "cache_read_tokens": 800,
          "reasoning_output_tokens": 30,
          "total_tokens": 2000
        }
      ],
      "event_count": 12,
      "session_count": 3,
      "attribution_confidence": "account_observed_usage_inferred",
      "provenance": "codex_token_events",
      "account_evidence": {
        "source": "codex_auth_claim",
        "observed_at": "2026-06-11T14:30:00+08:00",
        "window": "collection_time"
      },
      "sensitive_payload": false
    }
  ],
  "source_status": {
    "status": "ok",
    "error_type": null,
    "message": null
  }
}
```

### Required Fields

Top level:

- `schema_version`
- `source_id`
- `host`
- `machine`
- `os_user`
- `platform`
- `observed_at`
- `timezone`
- `device`
- `usage_hourly_facts`
- `source_status`

Device:

- `machine_id`
- `machine_name`
- `platform`
- `os_user`

Fact:

- `fact_id`
- `agent`
- `window_start`
- `window_end`
- `usage.total_tokens`
- `attribution_confidence`
- `provenance`

AI account:

- `provider`
- `account_id`
- `label`

如果账号无法识别：

```json
{
  "provider": "anthropic",
  "account_id": "unknown",
  "label": "unknown",
  "display_name": null,
  "subscription": null
}
```

并设置：

```json
{
  "attribution_confidence": "account_unknown"
}
```

### Response

```json
{
  "status": "accepted",
  "source_id": "macbook-wang-codex",
  "accepted_at": "2026-06-11T14:30:01+08:00",
  "facts_accepted": 1,
  "message": "ok"
}
```

### Error Response

```json
{
  "status": "error",
  "source_id": "macbook-wang-codex",
  "accepted_at": "2026-06-11T14:30:01+08:00",
  "error_type": "http_schema_invalid",
  "message": "usage_hourly_facts[0].window_start is required"
}
```

## Source Status Push

采集失败时也要上报 source 状态，避免 UI 把失败误认为 0 用量。

```json
{
  "schema_version": 1,
  "source_id": "macbook-wang-claude",
  "host": "MacBook-Pro.local",
  "machine": "MacBook Pro",
  "os_user": "wangzhipeng",
  "platform": "darwin",
  "observed_at": "2026-06-11T14:30:00+08:00",
  "timezone": "Asia/Shanghai",
  "device": {
    "machine_id": "macbook-pro-local",
    "machine_name": "MacBook Pro",
    "platform": "darwin",
    "os_user": "wangzhipeng"
  },
  "usage_hourly_facts": [],
  "source_status": {
    "status": "ok",
    "error_type": null,
    "message": null
  },
  "collector_status": {
    "claude_code_hourly": {
      "status": "failed",
      "error_type": "auth_status_failed",
      "message": "Claude auth status unavailable"
    }
  }
}
```

## Summary API

### Endpoint

现有产品入口保持：

```http
GET /api/summary?period=today
GET /api/mobile/summary?period=today
GET /api/mobile/summary?period=week
GET /api/mobile/summary?period=month
```

如果后续新增 usage 专用 endpoint，必须与上述接口输出口径一致：

```http
GET /api/usage/summary?period=last_hour
GET /api/usage/summary?period=today&granularity=hour
GET /api/usage/summary?period=week&granularity=day
GET /api/usage/summary?from=2026-06-01&to=2026-06-11&granularity=day
```

### Response

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-11T14:35:00+08:00",
  "timezone": "Asia/Shanghai",
  "period": {
    "id": "today",
    "start": "2026-06-11T00:00:00+08:00",
    "end": "2026-06-12T00:00:00+08:00"
  },
  "summary": {
    "total_tokens": 11361204,
    "input_tokens": 5200000,
    "output_tokens": 1200004,
    "cache_creation_tokens": 0,
    "cache_read_tokens": 4961200,
    "reasoning_output_tokens": 300000
  },
  "groups": {
    "by_ai_account": [
      {
        "provider": "openai",
        "label": "startimessocietegn@gmail.com",
        "total_tokens": 10600256,
        "strong_total_tokens": 0,
        "inferred_total_tokens": 10600256,
        "attribution_confidence": "account_observed_usage_inferred",
        "confidence_breakdown": [
          {
            "confidence": "account_observed_usage_inferred",
            "total_tokens": 10600256
          }
        ],
        "source_ids": ["macbook-wang-codex"]
      }
    ],
    "by_machine": [
      {
        "machine_id": "macbook-pro-local",
        "name": "MacBook Pro",
        "total_tokens": 11361204,
        "users": [
          {
            "os_user": "wangzhipeng",
            "account": "wangzhipeng",
            "display_name": "MacBook Pro / wangzhipeng",
            "total_tokens": 11361204,
            "source_ids": ["macbook-wang-codex", "macbook-wang-claude"]
          }
        ],
        "source_ids": ["macbook-wang-codex", "macbook-wang-claude"]
      }
    ],
    "by_os_user": [
      {
        "machine_id": "macbook-pro-local",
        "os_user": "wangzhipeng",
        "display_name": "MacBook Pro / wangzhipeng",
        "total_tokens": 11361204,
        "source_ids": ["macbook-wang-codex", "macbook-wang-claude"]
      }
    ],
    "by_agent": [
      {
        "agent": "codex",
        "total_tokens": 10600256
      },
      {
        "agent": "claude_code",
        "total_tokens": 760948
      }
    ]
  },
  "trend": {
    "granularity": "hour",
    "axis": ["13:00"],
    "points": [
      {
        "window_start": "2026-06-11T13:00:00+08:00",
        "window_end": "2026-06-11T14:00:00+08:00",
        "total_tokens": 11361204
      }
    ],
    "by_token_type": [
      {
        "type": "input_tokens",
        "label": "Input",
        "values": [5200000]
      },
      {
        "type": "output_tokens",
        "label": "Output",
        "values": [1200004]
      },
      {
        "type": "cache_creation_tokens",
        "label": "Cache Write",
        "values": [0]
      },
      {
        "type": "cache_read_tokens",
        "label": "Cache Read",
        "values": [4961200]
      }
    ]
  },
  "source_status": [
    {
      "source_id": "macbook-wang-codex",
      "machine_name": "MacBook Pro",
      "os_user": "wangzhipeng",
      "agent": "codex",
      "status": "ok",
      "last_seen_at": "2026-06-11T14:30:00+08:00"
    }
  ]
}
```

## Drilldown API

### By Account

```http
GET /api/usage/accounts/{account_id}?period=today
```

返回该 AI 账号在不同机器、OS 用户、agent、model 上的用量。

### By Machine

```http
GET /api/usage/machines/{machine_id}?period=today
```

返回该机器上不同 OS 用户、AI 账号、agent 的用量。

### By OS User

```http
GET /api/usage/os-users?machine_id=macbook-pro-local&os_user=wangzhipeng&period=today
```

返回该机器登录用户上下文中的 AI 用量。

## Validation Rules

服务端必须拒绝：

- 缺少 `source_id`。
- 缺少 device 机器信息。
- 缺少 OS 用户。
- 上传 token、refresh token、cookie。
- 上传 `.codex`、`.claude` 原始路径。
- 上传 prompt、response、tool output。
- `window_end <= window_start`。
- `total_tokens` 为负数。
- `input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens` 与 `total_tokens` 不一致，除非该 provenance 明确声明外部 total 口径。

服务端必须接受：

- 空 `usage_hourly_facts` + failed source status。
- `account_unknown` 账号。
- `mixed_account` attribution confidence。
- 同一 fact 重复上传并幂等覆盖。

## Health Model

`source_status` 表示整台设备 / source 本轮是否正常上报。

`collector_status` 表示 agent/client 级采集状态，例如：

```json
{
  "collector_status": {
    "codex_hourly": {
      "status": "ok",
      "error_type": null
    },
    "claude_code_hourly": {
      "status": "unsupported",
      "error_type": "client_not_verified"
    }
  }
}
```

agent/client 级失败不能覆盖 source 的整体 daily / limits 健康状态。

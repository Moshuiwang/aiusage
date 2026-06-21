# TP-V2-053 Production Mobile Summary Deploy

Version: V2
ID: TP-V2-053
Status: done
Type: deployment
Depends on: TP-V2-043, TP-V2-052
Parallel with: none

## Goal

Deploy the mobile summary API code to production so the iOS simulator can read real production data.

## Context

The iOS simulator can load `/api/mobile/summary` locally, but production `https://vpn2.chunbai.com:8443/api/mobile/summary` currently returns 404 because `vpn2` is running older server code without `mobile_summary.py`.

## Scope

- Back up production source files before changing them.
- Sync current `src/ai_usage_widget` server code to `/home/ubuntu/ai-usage-widget/src/ai_usage_widget`.
- Restart `ai-usage-server`.
- Verify production `/api/mobile/summary` for `today`, `week`, `month`, and `all`.
- Point the current iOS simulator to production and verify it renders production data.

## Out of Scope

- Do not modify production `data/usage.sqlite`.
- Do not rotate production tokens.
- Do not install to the physical iPhone.
- Do not add production settings UI in this task.

## Red Test

- Before deploy, production `/api/mobile/summary?period=week` returns 404.

## Implementation

- Use SSH alias `vpn2` and deployment directory `/home/ubuntu/ai-usage-widget`.
- Use `rsync` for source-only deploy.
- Keep secrets out of logs where possible.

## Acceptance Criteria

- Production `/api/mobile/summary` returns HTTP 200 for all four periods.
- The response contains mobile contract fields consumed by the iOS app.
- The current iOS simulator is configured with production base URL/token and screenshots show production data.

## Verification

```bash
curl -H "Authorization: Bearer <token>" https://vpn2.chunbai.com:8443/api/mobile/summary?period=week
xcrun simctl spawn <sim> defaults read com.wangzhipeng.aiusage.mobile AIUsageAPIBaseURL
```

## Handoff

- Pre-deploy production check confirmed `https://vpn2.chunbai.com:8443/api/mobile/summary?period=week` returned 404.
- Production source backup was created on `vpn2`:
  - `/home/ubuntu/ai-usage-widget/backups/src-ai_usage_widget-before-mobile-summary-20260603-163133.tgz`
- Synced local `src/ai_usage_widget` to `/home/ubuntu/ai-usage-widget/src/ai_usage_widget`.
- Restarted `ai-usage-server`; systemd reported active after restart.
- Verified production `https://vpn2.chunbai.com:8443/api/mobile/summary`:
  - `today`: 2026-06-03 to 2026-06-03, 244.1M tokens, hourly trend.
  - `week`: 2026-05-28 to 2026-06-03, 932.6M tokens, daily trend.
  - `month`: 2026-05-05 to 2026-06-03, 3874.9M tokens, daily trend.
  - `all`: all data through 2026-06-03, 3921.5M tokens, daily trend.
- Configured the current iOS simulator to read production:
  - `AIUsageAPIBaseURL=https://vpn2.chunbai.com:8443`
  - `AIUsagePeriod=week`
- Simulator production screenshots:
  - `tmp/ai-usage-simulator-production-today.png`
  - `tmp/ai-usage-simulator-production-week.png`
  - `tmp/ai-usage-simulator-production-month.png`
  - `tmp/ai-usage-simulator-production-all.png`
- Physical iPhone was not updated.

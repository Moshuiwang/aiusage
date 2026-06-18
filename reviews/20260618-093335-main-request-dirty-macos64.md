# AI Review Request

## Scope

Review target: current uncommitted macOS menu bar client implementation.

Branch: `main`
Default branch: `main`
Mode: local read-only Claude review
Selected depth: standard
Selected reviewer: Claude Code (`claude --model opus --effort xhigh`)

## Repo State

Relevant changed files:

- `.gitignore`
- `clients/macos/README.md`
- `clients/macos/Package.swift`
- `clients/macos/Sources/AIUsageMenuBarApp/AIUsageMenuBarApp.swift`
- `clients/macos/Sources/AIUsageMenuBarApp/MenuBarAppModel.swift`
- `clients/macos/Sources/AIUsageMenuBarApp/MenuBarPopoverView.swift`
- `clients/macos/Sources/AIUsageMenuBarApp/StatusBarController.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/MenuBarViewModel.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/MobileSummary.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/MobileSummaryClient.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/RuntimeConfiguration.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/RuntimePaths.swift`
- `clients/macos/Sources/AIUsageMenuBarCore/SummaryCache.swift`
- `clients/macos/Tests/AIUsageMenuBarCoreTests/Fixtures/mobile-summary.json`
- `clients/macos/Tests/AIUsageMenuBarCoreTests/MenuBarViewModelTests.swift`
- `clients/macos/Tests/AIUsageMenuBarCoreTests/MobileSummaryClientTests.swift`
- `clients/macos/Tests/test_install_menu_bar_app.py`
- `clients/macos/scripts/install_menu_bar_app.py`
- `docs/task-packages/v2/INDEX.md`
- `docs/task-packages/v2/TP-V2-064-macos-menu-bar-client.md`

Unrelated dirty files are out of scope:

- `mobile/ios-xcode/**`
- `mobile/ios/Sources/AIUsageMobileCore/MobileSummaryRuntimeConfig.swift`
- `mobile/ios/Tests/AIUsageMobileCoreTests/MobileRuntimeConfigurationTests.swift`
- `tests/test_ios_xcode_integration.py`
- `.codex/config.toml`

Verification already run:

```bash
cd clients/macos && swift test
cd clients/macos && swift build -c release
python3 -m unittest discover -s clients/macos/Tests -p 'test_*.py' -v
python3 clients/macos/scripts/install_menu_bar_app.py --server-url https://vpn2.chunbai.com:8443 --dry-run
git diff --check -- .gitignore clients/macos docs/task-packages/v2/INDEX.md docs/task-packages/v2/TP-V2-064-macos-menu-bar-client.md
```

Round 2 update after reviewer LOW-1:

- `clients/macos/Sources/AIUsageMenuBarApp/MenuBarAppModel.swift` now sequences refreshes and ignores stale responses when the selected period has changed.
- `clients/macos/Tests/AIUsageMenuBarAppTests/MenuBarAppModelTests.swift` covers rapid period switching where the older request completes first.
- `clients/macos/Package.swift` now includes `AIUsageMenuBarAppTests`.
- `cd clients/macos && swift test` passed after the fix.

Manual/local smoke already run:

- Installed app to `~/Applications/AI Usage Menu Bar.app`.
- Runtime config/cache path is `~/Library/Application Support/ai-usage-widget/macos-menu-bar`.
- Verified installed bundle executable exists.
- Verified `LSUIElement=true`.
- Launched app; process `AIUsageMenuBar` was running.
- Verified `/api/mobile/summary` for `today`, `week`, `month`, `all` returned HTTP 200 using local existing token. Do not read or output that token.

## Review Instructions

Read-only review. Report only findings tied to the scoped files above.

Focus on user-visible and operational risks:

- Menu bar App cannot load or refresh data.
- App or installer still triggers `Documents` access prompts at runtime.
- App accidentally executes collector/provider/SQLite or otherwise crosses client boundary.
- Token handling risk in repo files, command output, app config, or installer.
- Obvious low-resource issues, such as excessive refresh or persistent heavy rendering.
- Install script does not install a runnable LSUIElement app.
- Tests missing for critical scoped behavior.

Return findings first with severity, file/path, evidence, and impact. If there are no actionable findings, say so and list residual test gaps.

## Out Of Scope

- Do not review unrelated iOS dirty files.
- Do not review historical whole-repo architecture.
- Do not read or output `.env`, local token files, production account files, raw usage logs, or any secret values.
- Do not modify files.

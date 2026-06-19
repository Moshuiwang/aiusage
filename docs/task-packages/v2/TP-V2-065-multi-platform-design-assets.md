# TP-V2-065 Multi Platform Design Assets

Version: V2
ID: TP-V2-065
Status: ready
Type: implementation
Depends on: multi-platform design docs AI review
Parallel with: TP-V2-066, TP-V2-067

## Goal

Generate and wire the new dual-ring AI Usage icon and shared visual tokens for Web, macOS, iOS App, iOS Widget, and Watch.

## Context

The latest design package defines the brand mark as Claude orange outer ring and OpenAI blue inner ring on a dark radial background. Current iOS icon is known to be wrong.

## Scope

- Add reusable icon assets or rendering helpers for Web and SwiftUI clients.
- Replace iOS AppIcon assets.
- Provide asset outputs for macOS menu bar, iOS Widget, and Watch usage.
- Add tests or static checks proving generated assets exist and are referenced.

## Out of Scope

- Do not change usage collection, API auth, or production token config.
- Do not redesign the mark beyond the design package geometry.

## Red Test

- Add a failing static test that asserts AppIcon assets include the new dual-ring source and required iOS sizes.
- Add a failing static test that prevents placeholder SF Symbol icon usage in the iOS App, Widget, macOS popover header, and Watch header where the brand icon is required.

## Implementation

1. Build the icon source from the design package geometry.
2. Generate required raster sizes for iOS and macOS assets.
3. Add SwiftUI reusable brand icon view where raster asset is not appropriate.
4. Update Web static icon usage.

## Acceptance Criteria

- iOS App home screen icon uses the dual-ring mark.
- macOS popover and iOS Widget show the same mark.
- Web Dashboard nav uses the same mark.
- No production credentials or generated local config are committed.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd clients/macos && swift test
git diff --check
```

## Handoff

- Report generated asset paths.
- Attach before/after screenshots or rendered previews.
- State whether physical iPhone install was skipped or completed.

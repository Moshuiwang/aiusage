# Mobile App Prototype

This is a phone-sized Web prototype for the next iPhone App direction.

## Scope

- Four app views: Home, Sources, Breakdown, Limits.
- Mock fixture only: `fixture.json`.
- No production API calls, no SQLite reads, no collector commands.
- Every major display block carries a `data-provenance` hook for later mapping to Web API or snapshot fields.

## Local Preview

```bash
cd docs/prototypes/mobile-app
python3 -m http.server 8776 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8776/index.html
```

## Design Notes

- Home should answer today's usage, trustworthy limit state, top usage sources, and freshness.
- Sources focuses on data health and non-sensitive failure summaries.
- Breakdown keeps machine, OS user, agent, model, and date drilldown in one surface.
- Limits only strengthens observed windows; missing or unsupported windows stay explicit.
- Visual v4 follows the system appearance instead of adding an in-app theme toggle: the Web prototype uses `color-scheme`, `prefers-color-scheme`, semantic iOS-like color tokens, safe-area insets, and glass material approximations.
- The later SwiftUI implementation should map these surfaces to system `Color`, `Material`, safe areas, standard controls, and SF Symbols rather than hard-coded custom colors.
- Visual v6 keeps the iOS-style large title only on Home. System-level iOS Widget design is intentionally out of this App prototype and should be handled later in a separate WidgetKit surface.
- Visual v7 removes the Home-only navigation header from Sources / Breakdown / Limits and reduces their top area to compact content summaries.
- Visual v8 localizes secondary tab labels and list headings so the App prototype no longer reads like an English debug dashboard.
- Visual v9 localizes dynamic source and limits status text, including observed / pushed timestamps, status chips, remaining, and reset copy.
- Visual v10 localizes missing limit reasons and reset day labels.

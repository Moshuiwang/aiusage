from __future__ import annotations

import json
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Protocol

from .limits import LimitContractError, LimitWindow, parse_limit_window
from .snapshot_builder import build_snapshot
from .storage_sqlite import write_limit_windows


class LimitsProvider(Protocol):
    def collect(self) -> list[LimitWindow]:
        ...


@dataclass(frozen=True)
class ProviderRuntimeResult:
    provider: str
    status: str
    windows_written: int
    error_type: str | None = None


@dataclass(frozen=True)
class LimitsRuntimeResult:
    success: bool
    windows_written: int
    provider_results: list[ProviderRuntimeResult]


class FixtureLimitsProvider:
    def __init__(self, provider: str, payloads: Iterable[Dict[str, Any]]) -> None:
        self.provider = provider
        self.payloads = list(payloads)

    def collect(self) -> list[LimitWindow]:
        windows = [parse_limit_window(payload) for payload in self.payloads]
        for window in windows:
            if window.provider != self.provider:
                raise LimitContractError(
                    "limit_schema_invalid",
                    f"fixture provider mismatch: expected {self.provider}, got {window.provider}",
                )
        return windows


class LimitsRuntime:
    def __init__(
        self,
        *,
        db_path: str,
        latest_path: str,
        timezone: str,
        providers: Dict[str, LimitsProvider],
        now_provider=None,
    ) -> None:
        self.db_path = db_path
        self.latest_path = latest_path
        self.timezone = timezone
        self.providers = providers
        self.now_provider = now_provider or _default_now

    def collect(
        self,
        *,
        provider_names: list[str],
        rebuild_snapshot: bool,
        snapshot_date: str | None = None,
        dry_run: bool = False,
    ) -> LimitsRuntimeResult:
        if not provider_names:
            raise ValueError("no limits providers enabled")
        seen_at = self.now_provider()
        all_windows: list[LimitWindow] = []
        provider_results: list[ProviderRuntimeResult] = []

        for provider_name in provider_names:
            provider = self.providers.get(provider_name)
            if provider is None:
                raise ValueError(f"unsupported limits provider: {provider_name}")
            provider_label = str(getattr(provider, "provider_name", provider_name))
            source_id = str(getattr(provider, "source_id", provider_name))
            try:
                windows = [_normalize_window_source_id(window, source_id) for window in provider.collect()]
            except Exception:
                windows = [_failed_window(provider_label, seen_at, source_id=source_id)]
                all_windows.extend(windows)
                provider_results.append(
                    ProviderRuntimeResult(
                        provider=provider_name,
                        status="provider_failed",
                        windows_written=0 if dry_run else len(windows),
                        error_type="provider_failed",
                    )
                )
                continue

            all_windows.extend(windows)
            provider_results.append(
                ProviderRuntimeResult(
                    provider=provider_name,
                    status="ok",
                    windows_written=0 if dry_run else len(windows),
                    error_type=None,
                )
            )

        if dry_run:
            return LimitsRuntimeResult(
                success=all(result.status == "ok" for result in provider_results),
                windows_written=0,
                provider_results=provider_results,
            )

        write_limit_windows(self.db_path, all_windows, seen_at=seen_at)
        if rebuild_snapshot:
            build_snapshot(
                db_path=self.db_path,
                output_path=self.latest_path,
                date_str=snapshot_date or seen_at[:10],
                timezone_str=self.timezone,
                current_time_str=seen_at,
            )

        return LimitsRuntimeResult(
            success=all(result.status == "ok" for result in provider_results),
            windows_written=len(all_windows),
            provider_results=provider_results,
        )


def load_fixture_providers(path: str) -> Dict[str, LimitsProvider]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    providers_payload = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(providers_payload, dict):
        raise ValueError("limits fixture must contain a providers object")

    providers: Dict[str, LimitsProvider] = {}
    for provider, windows in providers_payload.items():
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("limits fixture provider names must be strings")
        if not isinstance(windows, list):
            raise ValueError(f"limits fixture provider {provider} must contain a list")
        providers[provider] = FixtureLimitsProvider(provider, windows)
    return providers


def _normalize_window_source_id(window: LimitWindow, source_id: str) -> LimitWindow:
    if window.source_id and window.source_id != window.provider:
        return window
    return replace(window, source_id=source_id)


def _failed_window(provider: str, observed_at: str, *, source_id: str | None = None) -> LimitWindow:
    return parse_limit_window(
        {
            "provider": provider,
            "source_id": source_id or provider,
            "window": "unknown",
            "used_percent": 0,
            "remaining_percent": 0,
            "reset_at": observed_at,
            "window_duration_minutes": 0,
            "observed_at": observed_at,
            "source_type": "provider_runtime",
            "confidence": "missing",
            "status": "provider_failed",
        }
    )


def _default_now() -> str:
    from datetime import datetime, timezone as dt_timezone

    return datetime.now(dt_timezone.utc).astimezone().isoformat()

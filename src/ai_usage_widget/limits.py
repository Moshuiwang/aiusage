from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable


REQUIRED_FIELDS = (
    "provider",
    "window",
    "reset_at",
    "observed_at",
)

LOCAL_ESTIMATE_SOURCE_TYPES = {
    "local_history_estimate",
    "ccusage_daily",
    "ccusage_blocks",
    "session_log_estimate",
}


class LimitContractError(ValueError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class LimitWindow:
    provider: str
    window: str
    used_percent: float
    remaining_percent: float
    reset_at: str
    window_duration_minutes: int
    observed_at: str
    source_type: str
    confidence: str
    status: str

    @property
    def is_official(self) -> bool:
        return (
            self.status == "ok"
            and self.confidence == "observed"
            and self.source_type not in LOCAL_ESTIMATE_SOURCE_TYPES
        )

    def to_snapshot_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "window": self.window,
            "used_percent": self.used_percent,
            "remaining_percent": self.remaining_percent,
            "reset_at": self.reset_at,
            "window_duration_minutes": self.window_duration_minutes,
            "observed_at": self.observed_at,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "status": self.status,
            "official": self.is_official,
        }


def parse_limit_window(payload: Dict[str, Any]) -> LimitWindow:
    if not isinstance(payload, dict):
        raise LimitContractError("limit_schema_invalid", "limit payload must be an object")

    _require_fields(payload, REQUIRED_FIELDS)

    provider = _require_non_empty_string(payload, "provider")
    window = _require_non_empty_string(payload, "window")
    reset_at = _require_iso_datetime(payload, "reset_at")
    observed_at = _require_iso_datetime(payload, "observed_at")

    used_percent = _optional_percent(payload, "used_percent")
    remaining_percent = _optional_percent(payload, "remaining_percent")
    window_duration_minutes = _optional_positive_int(payload, "window_duration_minutes")
    source_type = _optional_string(payload, "source_type", default="unknown")
    confidence = _optional_string(payload, "confidence", default="unknown")
    status = _optional_string(payload, "status", default="unknown")

    return LimitWindow(
        provider=provider,
        window=window,
        used_percent=used_percent,
        remaining_percent=remaining_percent,
        reset_at=reset_at,
        window_duration_minutes=window_duration_minutes,
        observed_at=observed_at,
        source_type=source_type,
        confidence=confidence,
        status=status,
    )


def _require_fields(payload: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise LimitContractError(
            "limit_schema_invalid",
            "missing required limit field: " + ", ".join(missing),
        )


def _require_non_empty_string(payload: Dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LimitContractError("limit_schema_invalid", f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(payload: Dict[str, Any], field: str, default: str) -> str:
    value = payload.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise LimitContractError("limit_schema_invalid", f"{field} must be a string")
    return value.strip()


def _require_iso_datetime(payload: Dict[str, Any], field: str) -> str:
    value = _require_non_empty_string(payload, field)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LimitContractError("limit_schema_invalid", f"{field} must be an ISO 8601 datetime") from exc
    return value


def _optional_percent(payload: Dict[str, Any], field: str) -> float:
    value = payload.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LimitContractError("limit_schema_invalid", f"{field} must be a number")
    numeric = float(value)
    if numeric < 0 or numeric > 100:
        raise LimitContractError("limit_schema_invalid", f"{field} must be between 0 and 100")
    return numeric


def _optional_positive_int(payload: Dict[str, Any], field: str) -> int:
    value = payload.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitContractError("limit_schema_invalid", f"{field} must be an integer")
    if value < 0:
        raise LimitContractError("limit_schema_invalid", f"{field} must be positive")
    return value

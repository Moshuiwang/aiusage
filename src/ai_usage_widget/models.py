from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    command: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None and self.exit_code == 0


@dataclass
class UsageItem:
    source_id: str
    machine: str
    account: str
    agent: str
    date: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    total_cost: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    model_breakdowns: List[Dict[str, Any]] = field(default_factory=list)

    def to_latest_dict(self) -> Dict[str, Any]:
        return {
            "machine": self.machine,
            "account": self.account,
            "agent": self.agent,
            "date": self.date,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class UsageHourlyItem:
    source_id: str
    machine: str
    account: str
    agent: str
    hour: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    total_cost: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageHourlyFact:
    fact_id: str
    source_id: str
    machine_id: str
    machine_name: str
    host: str
    os_user: str
    platform: str
    ai_provider: str
    ai_account_id: str
    ai_account_label: str
    ai_account_display_name: Optional[str]
    ai_account_subscription: Optional[str]
    agent: str
    client: str
    window_start: str
    window_end: str
    timezone: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    total_cost: Optional[float] = None
    event_count: int = 0
    session_count: int = 0
    attribution_confidence: str = "account_unknown"
    provenance: str = "unknown"
    account_evidence: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    model_breakdowns: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class UsageBlockItem:
    source_id: str
    machine: str
    account: str
    agent: str
    start_time: str
    end_time: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    total_cost: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizeResult:
    items: List[UsageItem] = field(default_factory=list)
    status: str = "ok"
    error_type: Optional[str] = None
    error_message: Optional[str] = None

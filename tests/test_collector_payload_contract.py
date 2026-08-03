"""Issue #64 A 组：采集端 ``/ingest`` payload 合同 fixture 的 owner 与防陈旧守卫。

#67 已决策服务端收敛为 Worker 单实现、Python ingest 定向废弃。但**采集端永远是
Python**（要读本机 ccusage / mswusage 与 OS 上下文），服务端是 TypeScript——所以
「采集端 payload ↔ 服务端 ingest」这条 wire contract 是**永久边界**，单实现消灭不掉，
只能治理。

治理方式和 #63 的 ``value_golden.json`` 守卫同构，但被守护的东西换成了 payload：

- fixture 的 owner 是 ``src/ai_usage_widget/pusher.py``——它是 ``/ingest`` payload 的
  唯一产出方。本模块用 fake executor 喂固定的 ccusage / mswusage 输出，驱动**真实的**
  ``DevicePusher.push()``，从 HTTP 客户端手里接住它真正发出去的那个 dict。
  **fixture 一个字节都不许手写**（AGENTS.md：手写 fixture 会和现实脱节，
  且脱节方向正好是「实现者以为的样子」）。
- 生成逻辑的 owner 是**本测试模块**（``FIXTURE_PATH`` + ``_collect_payloads()``），
  ``scripts/gen_collector_payload_fixture.py`` 反过来从这里 import，只负责写文件；
  和 Worker 侧服务端合同 golden 的做法同构（``cloudflare/native-worker/test/golden/``
  的收集器即 owner，``npm run cf:golden:gen`` 反过来调它们）。
- 消费方是 Worker 侧的 ``cloudflare/native-worker/test/ingest.test.ts``：
  它拿同一份 fixture 断言服务端能收下采集端真实发出的 payload。

本模块每次都重新生成一遍并与已提交的 fixture 逐字段比对：pusher 一旦多发、少发或改写
任何字段而 fixture 没跟上，这里立刻变红——**且失败信息会指出差在哪个 payload 的哪个字段**。

变红时的正确动作是**复核 diff 后重新生成**：

    PYTHONPATH=src python3 scripts/gen_collector_payload_fixture.py

而不是放宽这里的断言。重新生成后必须同时复核 Worker 侧断言是否还成立——
payload 变了而服务端没跟上，正是这条边界要拦的事故。

fixture 里的 ``request`` 块同样**不许手写**：``method`` / ``path`` / ``auth`` 全部来自
这次 push 真正发生的事——``path`` 取自 pusher 实际 POST 的 URL，``auth`` 由「这次请求的
headers 里到底有没有 ``Authorization``」推导。手写成 ``auth: True`` 会让 Worker 侧那条
``expect(record.request).toEqual({...auth: true})`` 退化成**两处字面量互相比对的恒真断言**，
什么都不验证（AGENTS.md：恒等式一旦选错对象，测试和实现会一起错）。
认证 token 只参与这个布尔判定，**其值绝不进入 fixture**，由
``test_fixture_never_carries_the_auth_token_value`` 守住。

确定性说明：payload 里唯一随运行时刻变化的字段是顶层 ``observed_at``
（``datetime.now()``），比对前抹成 ``<masked>``；``collector_release`` 依赖的环境变量
由本模块显式接管（``patch.dict(..., clear=True)``），因此换机器、换 shell 都不会漂。
``account_evidence.observed_at`` 来自报告里的固定 ``generated_at``，是真实数据，**不抹**。
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse

from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.models import CommandResult
from ai_usage_widget.pusher import DevicePusher, IngestHTTPClient


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "collector_payload_fixture.json"

GENERATOR_HINT = "PYTHONPATH=src python3 scripts/gen_collector_payload_fixture.py"

#: 摘除的历史字段探针。两侧（本模块 + Worker 侧 ingest.test.ts）读同一份，
#: 断言同一组可观测结果：都不报错、都不解析、都不落库。
LEGACY_PROBE_PATH = (
    REPO_ROOT / "cloudflare" / "native-worker" / "test" / "legacy_collector_payload_ccusage_daily_status.json"
)
#: #91 摘除的 ``ccusage_blocks_report`` 探针，结构与上面同构。
BLOCKS_PROBE_PATH = (
    REPO_ROOT / "cloudflare" / "native-worker" / "test" / "legacy_collector_payload_ccusage_blocks_report.json"
)
#: fixture 里 observed_at 被抹成 "<masked>"，回放前换成一个固定的合法时间戳。
LEGACY_PROBE_OBSERVED_AT = "2026-06-05T09:05:00+08:00"
#: 哨兵：``None`` 本身就是要测的绕过形状之一，不能拿它当「未传参」。
_UNSET = object()

#: payload 里唯一随运行时刻变化的**顶层**字段。只抹这一个，别的都必须逐字节可复现。
VOLATILE_TOP_LEVEL_FIELDS = ("observed_at",)
MASK = "<masked>"

#: 两端都必须有的 wire contract 字段。pusher 哪天悄悄不发其中之一，本模块要红。
REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "source_id",
    "host",
    "machine",
    "os_user",
    "platform",
    "timezone",
    "observed_at",
    "collection_window",
    "collection_status",
    "usage_daily",
    "collector_release",
)

#: 采集成功时额外必须携带的证据字段。
REQUIRED_OK_FIELDS = (
    "ccusage_daily_report",
    "ccusage_session_report",
    "mswusage_codex_hourly_report",
    "usage_hourly_facts",
    "usage_ledger_runs",
)

#: 采集失败时必须携带的失败说明字段。
REQUIRED_ERROR_FIELDS = ("error_type", "error_message")

#: 原始日志目录形态。payload 里出现即为越界（服务端 ingest 也按同一口径拒收）。
# 与服务端 `ingest.py` 的 scan_sensitive_values 逐条对齐，口径不能比它宽也不能比它严：
#   - 任何字符串**值**里出现 .claude / .codex → 拒（原始日志目录）
#   - 任何 dict 的 **key 名**里出现 ssh → 拒（SSH 参数）
# 注意 ssh 只查 key、不查值：把它并进 FORBIDDEN_PATH_MARKERS 会让守卫比服务端更严，
# 一个正常的值里带 "ssh" 就误报，那种噪音最后一定会被人关掉。
FORBIDDEN_PATH_MARKERS = (".claude", ".codex")
FORBIDDEN_KEY_MARKERS = ("ssh",)

MAX_DIFFS_REPORTED = 40
MAX_VALUE_CHARS = 200


# --- 固定输入：模拟本机 ccusage / mswusage 的 stdout ---------------------------
#
# 这些是**采集工具的输出**，不是 payload。payload 必须由 pusher 从这些输入算出来。

CCUSAGE_DAILY_STDOUT = json.dumps(
    {
        "daily": [
            {
                "period": "2026-06-04",
                "agent": "claude",
                "inputTokens": 1200,
                "outputTokens": 340,
                "cacheCreationTokens": 90,
                "cacheReadTokens": 4500,
                "totalTokens": 6130,
                "totalCost": 0.42,
                "modelsUsed": ["claude-opus-4"],
                "modelBreakdowns": [
                    {
                        "modelName": "claude-opus-4",
                        "inputTokens": 1200,
                        "outputTokens": 340,
                        "totalTokens": 6130,
                    }
                ],
            },
            {
                "period": "2026-06-04",
                "agent": "codex",
                "inputTokens": 800,
                "outputTokens": 260,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 1500,
                "totalTokens": 2560,
                "totalCost": 0.11,
                "modelsUsed": ["gpt-5-codex"],
            },
            # 没有 agent 的行：pusher 必须把它规范化成 agent="unknown"，
            # 而不是丢掉，也不是原样透传。
            {
                "period": "2026-06-05",
                "inputTokens": 40,
                "outputTokens": 10,
                "totalTokens": 50,
            },
        ],
        "totals": {"inputTokens": 2040, "outputTokens": 610, "totalTokens": 8740},
    },
    ensure_ascii=False,
    sort_keys=True,
)

CCUSAGE_SESSION_STDOUT = json.dumps(
    {
        "session": [
            {
                "sessionId": "fixture-session-1",
                "agent": "claude",
                "lastActivity": "2026-06-04",
                "totalTokens": 6130,
            }
        ]
    },
    ensure_ascii=False,
    sort_keys=True,
)

# `ccusage blocks` 已由 #91 停采：采集端不再跑该子进程，历史取值冻结在
# ``BLOCKS_PROBE_PATH`` 里（摘除前从真实 pusher 捕获），只服务于向后兼容探针。

# codex 报告里首条 hourly 早于 coverage.start，必须被 pusher 按覆盖窗剔除。
MSWUSAGE_CODEX_STDOUT = json.dumps(
    {
        "schema_version": 1,
        "source": "mswusage_codex",
        "timezone": "Asia/Shanghai",
        "generated_at": "2026-06-05T09:00:00+08:00",
        "provenance": "mswusage_codex_token_count",
        "collector": {
            "mode": "incremental",
            "lookback_hours": 48,
            "coverage": {
                "start": "2026-06-04T00:00:00+08:00",
                "end": "2026-06-05T00:00:00+08:00",
            },
        },
        "daily": [{"date": "2026-06-04", "agent": "codex", "total_tokens": 2500}],
        "hourly": [
            {
                "hour": "2026-06-03T23:00:00+08:00",
                "agent": "codex",
                "input_tokens": 111,
                "output_tokens": 11,
                "total_tokens": 122,
                "event_count": 1,
                "session_count": 1,
            },
            {
                "hour": "2026-06-04T09:00:00+08:00",
                "agent": "codex",
                "input_tokens": 600,
                "output_tokens": 180,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 900,
                "reasoning_output_tokens": 60,
                "total_tokens": 1680,
                "event_count": 12,
                "session_count": 2,
            },
            {
                "hour": "2026-06-04T10:00:00+08:00",
                "agent": "codex",
                "input_tokens": 200,
                "output_tokens": 80,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 600,
                "reasoning_output_tokens": 20,
                "total_tokens": 880,
                "event_count": 5,
                "session_count": 1,
            },
        ],
        "sessions": [{"session_id": "fixture-codex-session-1", "total_tokens": 2560}],
    },
    ensure_ascii=False,
    sort_keys=True,
)

# claude 报告里末条 hourly 不早于 coverage.end，必须被剔除（另一侧边界）。
MSWUSAGE_CLAUDE_STDOUT = json.dumps(
    {
        "schema_version": 1,
        "source": "mswusage_claude",
        "timezone": "Asia/Shanghai",
        "generated_at": "2026-06-05T09:00:05+08:00",
        "provenance": "mswusage_claude_assistant_usage",
        "collector": {
            "mode": "incremental",
            "lookback_hours": 48,
            "coverage": {
                "start": "2026-06-04T00:00:00+08:00",
                "end": "2026-06-05T00:00:00+08:00",
            },
        },
        "daily": [{"date": "2026-06-04", "agent": "claude", "total_tokens": 6130}],
        "hourly": [
            {
                "hour": "2026-06-04T09:00:00+08:00",
                "agent": "claude",
                "input_tokens": 1000,
                "output_tokens": 300,
                "cache_creation_tokens": 90,
                "cache_read_tokens": 4000,
                "reasoning_output_tokens": 0,
                "total_tokens": 5390,
                "event_count": 20,
                "session_count": 3,
            },
            {
                "hour": "2026-06-05T09:00:00+08:00",
                "agent": "claude",
                "input_tokens": 700,
                "output_tokens": 90,
                "total_tokens": 790,
                "event_count": 4,
                "session_count": 1,
            },
        ],
        "sessions": [],
    },
    ensure_ascii=False,
    sort_keys=True,
)


# --- 场景定义 ----------------------------------------------------------------

OK_SCENARIO = "ok-full-collection"
ERROR_SCENARIO = "error-ccusage-missing-tool"
#: ccusage 挂了但账本采集仍然可用 —— pusher 不走状态心跳，照常上报账本用量。
#: 这是**第三条真实产出路径**，#78 之前它是 payload 里唯一会出现 ``ccusage_daily_status``
#: 的地方，所以此前的两个场景都碰不到该字段，fixture 也就守不住它（见 #78）。
PARTIAL_SCENARIO = "partial-ccusage-missing-tool-ledger-ok"
SCENARIOS = (OK_SCENARIO, ERROR_SCENARIO, PARTIAL_SCENARIO)

#: 已从采集端摘除的顶层字段（#78 ``ccusage_daily_status``、#91 ``ccusage_blocks_report``）。
#: 老版本采集端仍会发，服务端两侧都必须当未知字段忽略；当前 pusher 则一个场景都不许再发。
DROPPED_LEGACY_FIELDS = ("ccusage_daily_status", "ccusage_blocks_report")

#: 探针文件 → 该字段摘除前**唯一**会发它的场景。场景钉错了，跨实现断言就名存实亡
#: （详见 ``test_probe_is_frozen_to_the_only_scenario_that_ever_sent_the_field``）。
#: - ``ccusage_daily_status``：只在 partial 场景（ccusage 挂了但账本可用）出现过；
#: - ``ccusage_blocks_report``：只在 ok 场景出现过——blocks 子进程只有 ccusage daily
#:   成功后才会跑，partial / error 场景根本采不到它。
LEGACY_PROBES = (
    (LEGACY_PROBE_PATH, PARTIAL_SCENARIO),
    (BLOCKS_PROBE_PATH, OK_SCENARIO),
)

#: 自升级 agent 会写入的环境变量。显式接管，避免本机 shell 里恰好有值时 fixture 漂移。
COLLECTOR_RELEASE_ENV_KEYS = (
    "AI_USAGE_BUILD_SHA",
    "AI_USAGE_LAST_UPGRADE_STATUS",
    "AI_USAGE_LAST_UPGRADE_FROM_VERSION",
    "AI_USAGE_LAST_UPGRADE_TO_VERSION",
    "AI_USAGE_LAST_UPGRADE_FINISHED_AT",
)

#: 两个场景的 config 都声明 ``token_env="AI_USAGE_TOKEN"``。给一个假值，是为了让
#: fixture 里的 ``request.auth`` 成为 **pusher 真实行为的证据**：pusher 只有在这个环境变量
#: 有值时才会发 ``Authorization`` 头（``pusher.py`` 第 431-436 行）。
#: 这个值只参与「headers 里有没有 Authorization」这一个布尔判定，
#: **绝不进入 fixture**（见 ``test_fixture_never_carries_the_auth_token_value``）。
#: 它不是任何真实凭据，字面量本身就写明了这一点。
AUTH_TOKEN_ENV_KEY = "AI_USAGE_TOKEN"
FAKE_AUTH_TOKEN = "fixture-fake-token-not-a-real-credential"

OK_ENV = {
    "AI_USAGE_BUILD_SHA": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    "AI_USAGE_LAST_UPGRADE_STATUS": "succeeded",
    "AI_USAGE_LAST_UPGRADE_FROM_VERSION": "0.2.0",
    "AI_USAGE_LAST_UPGRADE_TO_VERSION": "0.3.0",
    "AI_USAGE_LAST_UPGRADE_FINISHED_AT": "2026-06-05T08:59:00+08:00",
    AUTH_TOKEN_ENV_KEY: FAKE_AUTH_TOKEN,
}

# 错误场景故意不给任何版本环境变量：覆盖 collector_release 的常量兜底形态。
# token 仍然要给——采集失败也是要带认证上报的，这正是这条 wire contract 的一部分。
ERROR_ENV: dict[str, str] = {AUTH_TOKEN_ENV_KEY: FAKE_AUTH_TOKEN}

# 部分失败场景同样只给 token：版本块走常量兜底，与错误场景一致。
PARTIAL_ENV: dict[str, str] = {AUTH_TOKEN_ENV_KEY: FAKE_AUTH_TOKEN}

OK_CONFIG = DeviceConfig(
    schema_version=1,
    source_id="fixture-macbook-pro",
    host="macbook-pro.local",
    machine="macbook-pro",
    os_user="wangzhipeng",
    platform="darwin",
    timezone="Asia/Shanghai",
    server_url="https://ingest.example.invalid/ingest",
    timeout_seconds=30,
    token_env="AI_USAGE_TOKEN",
    ai_accounts={
        # 只声明 codex：claude 侧走「未确认本机来源」分支，一份 fixture 同时覆盖两种归属。
        "codex": {
            "provider": "openai",
            "account_id": "openai:fixture-work",
            "label": "Codex 工作账号",
            "display_name": "Fixture Codex",
            "subscription": "pro",
            "attribution_confidence": "account_confirmed",
            "evidence_source": "device_config",
        }
    },
    release_channel="stable",
)

PARTIAL_CONFIG = DeviceConfig(
    schema_version=1,
    source_id="fixture-desktop-partial",
    host="desktop-partial.internal",
    machine="desktop-partial",
    os_user="wangzp",
    platform="linux",
    timezone="Asia/Shanghai",
    server_url="https://ingest.example.invalid/ingest",
    timeout_seconds=30,
    token_env="AI_USAGE_TOKEN",
    ai_accounts=None,
    release_channel="stable",
)

ERROR_CONFIG = DeviceConfig(
    schema_version=1,
    source_id="fixture-linux-dev",
    host="linux-dev.internal",
    machine="linux-dev",
    os_user="wangzp",
    platform="linux",
    timezone="Asia/Shanghai",
    server_url="https://ingest.example.invalid/ingest",
    timeout_seconds=30,
    token_env="AI_USAGE_TOKEN",
    ai_accounts=None,
    release_channel="beta",
)

# 命令返回值按 pusher 的调用次序排列（FakeExecutor 按次序取）。
# #91 之后不再包含 `ccusage blocks`：pusher 多跑那条子进程时 _ScriptedExecutor 会直接
# raise（第 5 条命令越界），这正是「停采」的守卫之一。
OK_COMMAND_RESULTS = (
    CommandResult(stdout=CCUSAGE_DAILY_STDOUT, exit_code=0),
    CommandResult(stdout=CCUSAGE_SESSION_STDOUT, exit_code=0),
    CommandResult(stdout=MSWUSAGE_CODEX_STDOUT, exit_code=0),
    CommandResult(stdout=MSWUSAGE_CLAUDE_STDOUT, exit_code=0),
)

# ccusage 缺失 -> 不采 session；两个 ledger 也失败 -> 走 _push_source_status。
ERROR_COMMAND_RESULTS = (
    CommandResult(
        exit_code=None,
        error_type="missing_tool",
        error_message="[Errno 2] No such file or directory: 'ccusage'",
        command="ccusage daily --json --timezone Asia/Shanghai",
    ),
    CommandResult(
        stderr="ledger scan failed",
        exit_code=1,
        error_type="command_failed",
        error_message="command exited with code 1",
    ),
    CommandResult(
        stderr="ledger scan failed",
        exit_code=1,
        error_type="command_failed",
        error_message="command exited with code 1",
    ),
)

# ccusage 缺失 -> 不采 session/blocks；但两个 ledger 都成功 -> 照常上报账本用量，
# 不走 _push_source_status。这条路径的 payload 是 `collection_status: "ok"`，
# **没有** error_type / error_message —— #78 摘掉 ccusage_daily_status 之后，
# ccusage 本身的失败原因在这条路径上不再有任何承载字段（代价已由测试钉死）。
PARTIAL_COMMAND_RESULTS = (
    CommandResult(
        exit_code=None,
        error_type="missing_tool",
        error_message="[Errno 2] No such file or directory: 'ccusage'",
        command="ccusage daily --json --timezone Asia/Shanghai",
    ),
    CommandResult(stdout=MSWUSAGE_CODEX_STDOUT, exit_code=0),
    CommandResult(stdout=MSWUSAGE_CLAUDE_STDOUT, exit_code=0),
)

SCENARIO_SETUP = {
    OK_SCENARIO: (OK_CONFIG, OK_COMMAND_RESULTS, OK_ENV),
    ERROR_SCENARIO: (ERROR_CONFIG, ERROR_COMMAND_RESULTS, ERROR_ENV),
    PARTIAL_SCENARIO: (PARTIAL_CONFIG, PARTIAL_COMMAND_RESULTS, PARTIAL_ENV),
}


class _ScriptedExecutor:
    """按调用次序返回预置 ``CommandResult``，并记录真实 argv。

    调用次数超出预置结果时**直接 raise**，不再静默重复最后一条。
    静默重复会让「失败路径将来多跑一条命令」这种变化悄悄拿到上一条命令的结果，
    fixture 照样绿——那正是 harness 自己在骗人。
    """

    def __init__(self, results: tuple[CommandResult, ...]) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> CommandResult:
        self.calls.append(list(argv))
        index = len(self.calls) - 1
        if index >= len(self.results):
            raise AssertionError(
                f"pusher 执行了第 {len(self.calls)} 条采集命令，但本场景只预置了 "
                f"{len(self.results)} 条结果：{argv}\n"
                "采集命令序列变了，fixture 的含义随之改变，必须显式复核并补齐预置结果，"
                "不能让 harness 悄悄重复上一条命令的结果。"
            )
        return self.results[index]


class _CapturingHTTPClient(IngestHTTPClient):
    """接住 pusher 真正发出去的 payload 与 headers。

    fixture 的 ``payload`` 是这个 ``last_json``，``request`` 块由 ``last_url`` /
    ``last_headers`` 推导——两者都是这次 push 真正发生的事，没有一处是手写的。
    """

    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_json: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None
        self.last_method: str | None = None
        self.calls = 0

    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        self.calls += 1
        self.last_url = url
        self.last_json = data
        # 只留 header 名，**不留值**：token 值不许进入本对象，更不许进入 fixture。
        self.last_headers = {name: "<redacted>" for name in headers}
        # 基类 ``IngestHTTPClient.post`` 只有这一个 HTTP 动词（``method="POST"``），
        # 这里记录的是 pusher 实际调用到的那个方法，不是对 wire 的猜测。
        self.last_method = "POST"
        return 200, {"status": "accepted", "source_id": data.get("source_id"), "facts_accepted": 0}


class TestCollectorPayloadContractFixture(unittest.TestCase):
    """fixture 由 owner 模块产出，且必须能自动发现自己陈旧。"""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.regenerated = _collect_payloads()
        cls.by_name = {record["name"]: record for record in cls.regenerated}

    # --- 防陈旧守卫 ---------------------------------------------------------

    def test_committed_fixture_matches_freshly_generated_payloads(self) -> None:
        """已提交的 fixture 必须等于此刻 pusher 真正会发出的 payload。"""
        committed = self._load_committed_fixture()
        diffs = _diff_paths(committed, self.regenerated, "payloads")
        if diffs:
            self.fail(
                f"{_relative(FIXTURE_PATH)} 已经陈旧（{len(diffs)} 处差异），"
                "不再等于 pusher 当前发出的 payload——采集端与服务端 ingest 之间的 wire contract "
                "正在无人看守地漂移。\n"
                f"复核下列差异后重新生成：{GENERATOR_HINT}\n"
                "重新生成后必须同时复核 cloudflare/native-worker/test/ingest.test.ts 是否还成立。\n"
                + _format_diffs(diffs)
            )

    def test_fixture_covers_every_declared_scenario(self) -> None:
        """场景清单变了而 fixture 没跟上，同样算陈旧。"""
        committed = self._load_committed_fixture()
        self.assertEqual(
            [record["name"] for record in committed],
            list(SCENARIOS),
            f"fixture 覆盖的场景与 SCENARIOS 不一致，需要重新生成：{GENERATOR_HINT}",
        )

    def test_committed_fixture_masks_volatile_fields(self) -> None:
        """已提交的 fixture 里不许留下真实时间戳，否则守卫会天天随机红。"""
        committed = self._load_committed_fixture()
        for record in committed:
            with self.subTest(scenario=record["name"]):
                for field in VOLATILE_TOP_LEVEL_FIELDS:
                    self.assertEqual(record["payload"].get(field), MASK)

    # --- 生成逻辑自检（不依赖 fixture 文件是否存在）--------------------------

    def test_regeneration_is_deterministic(self) -> None:
        """守卫本身不许随机红：连续生成两次必须完全相同。

        固定采集输入 + 接管版本环境变量 + 抹掉顶层 observed_at，这三条只要有一条没做到，
        上面那条防陈旧断言就会变成噪音，很快会被人当成误报关掉。
        """
        diffs = _diff_paths(self.regenerated, _collect_payloads(), "payloads")
        if diffs:
            self.fail(
                f"重放结果不确定（{len(diffs)} 处差异），说明还有易变字段没被固定或抹掉：\n"
                + _format_diffs(diffs)
            )

    def test_payloads_come_from_the_pusher_not_from_this_module(self) -> None:
        """每个场景都必须真的走完一次 ``DevicePusher.push()`` 并发出 payload。"""
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                payload, executor, http_client, result = _push_once(scenario)
                self.assertEqual(http_client.calls, 1, "pusher 没有发出任何请求")
                self.assertIsInstance(payload, dict)
                self.assertEqual(http_client.last_url, SCENARIO_SETUP[scenario][0].server_url)
                self.assertTrue(result.get("success"), f"push 未成功：{result}")
                self.assertTrue(executor.calls, "pusher 没有执行任何采集命令")
                self.assertIn("ccusage", executor.calls[0])
                self.assertIn("daily", executor.calls[0])

    def test_ok_scenario_executes_the_declared_collection_commands_in_order(self) -> None:
        """采集命令次序是 fixture 的前提，次序错了 fixture 的含义就变了。

        #91 起 `ccusage blocks` 不许再出现在任何一次采集里：blocks 快照零消费者
        （读侧死代码已在 #90/PR #92 删除），继续采只是在浪费设备上的子进程与上报带宽。
        """
        _, executor, _, _ = _push_once(OK_SCENARIO)
        self.assertEqual(len(executor.calls), len(OK_COMMAND_RESULTS))
        self.assertEqual(executor.calls[0][:2], ["ccusage", "daily"])
        self.assertEqual(executor.calls[1][:2], ["ccusage", "session"])
        self.assertIn("mswusage-codex", executor.calls[2])
        self.assertIn("mswusage-claude", executor.calls[3])
        for call in executor.calls:
            self.assertNotIn(
                "blocks",
                call,
                "#91 已停采 ccusage blocks：pusher 不许再跑这条子进程",
            )

    def test_error_scenario_executes_exactly_the_declared_failure_path_commands(self) -> None:
        """失败路径的命令次数同样是 fixture 的前提，不能只守成功路径。

        ``_ScriptedExecutor`` 越界会 raise，但那只在「多跑」时触发；这里再钉死次数与次序，
        「少跑一条」（例如失败后不再采账本）也要红。
        """
        _, executor, _, _ = _push_once(ERROR_SCENARIO)
        self.assertEqual(
            len(executor.calls),
            len(ERROR_COMMAND_RESULTS),
            "失败路径执行的采集命令条数变了，fixture 的失败语义随之改变",
        )
        self.assertEqual(executor.calls[0][:2], ["ccusage", "daily"])
        # ccusage 缺失后不许再去要 session / blocks：那会把「工具不存在」放大成三次失败。
        for call in executor.calls[1:]:
            self.assertNotIn("ccusage", call)

    def test_partial_scenario_skips_ccusage_followups_but_still_reads_the_ledgers(self) -> None:
        """ccusage 挂了就不再要 session / blocks，但两个账本仍然必须采。

        少跑账本 = 丢真实用量，多跑 ccusage = 把一次失败放大成三次，两边都要红。
        """
        _, executor, _, _ = _push_once(PARTIAL_SCENARIO)
        self.assertEqual(len(executor.calls), len(PARTIAL_COMMAND_RESULTS))
        self.assertEqual(executor.calls[0][:2], ["ccusage", "daily"])
        for call in executor.calls[1:]:
            self.assertNotIn("ccusage", call)
        self.assertIn("mswusage-codex", executor.calls[1])
        self.assertIn("mswusage-claude", executor.calls[2])

    # --- request 块必须来自真实请求，不许手写 --------------------------------

    def test_request_block_is_derived_from_the_real_push(self) -> None:
        """``request`` 的三个字段都必须是这次 push 真正发生的事。

        关键证据是**它会随行为改变**：抽走 token 后 pusher 不再发 ``Authorization``，
        推导出的 ``auth`` 必须变成 ``False``。写死的 ``True`` 产不出这个结果，
        因此这条断言直接排除了「两处字面量互相比对」的恒真形态。
        """
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                config = SCENARIO_SETUP[scenario][0]
                _, _, http_client, _ = _push_once(scenario)
                request = _request_descriptor(http_client)

                self.assertEqual(request["method"], "POST")
                self.assertEqual(request["path"], urlparse(config.server_url).path)
                self.assertTrue(
                    request["auth"],
                    "配置了 token_env 且环境变量有值时，pusher 必须发 Authorization 头",
                )

                # 同一条推导逻辑，换一个真实存在的部署形态（设备没配 token）：结果必须翻转。
                env_without_token = {
                    key: value
                    for key, value in SCENARIO_SETUP[scenario][2].items()
                    if key != AUTH_TOKEN_ENV_KEY
                }
                _, _, unauthenticated, _ = _push_once(scenario, env=env_without_token)
                self.assertFalse(
                    _request_descriptor(unauthenticated)["auth"],
                    "环境变量里没有 token 时不该出现 Authorization 头——"
                    "auth 若仍为 True，说明它是写死的，不是推导出来的",
                )

    def test_fixture_never_carries_the_auth_token_value(self) -> None:
        """token 只参与布尔判定，其值不许出现在 fixture 或生成结果里。"""
        self.assertNotIn(FAKE_AUTH_TOKEN, FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn(
            FAKE_AUTH_TOKEN,
            json.dumps(self.regenerated, ensure_ascii=False, default=repr),
        )
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                _, _, http_client, _ = _push_once(scenario)
                self.assertNotIn(FAKE_AUTH_TOKEN, json.dumps(http_client.last_headers))

    def test_committed_fixture_request_block_matches_the_real_push(self) -> None:
        """已提交 fixture 里的 request 块也必须等于此刻真正会发出的请求。"""
        committed = {record["name"]: record["request"] for record in self._load_committed_fixture()}
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                _, _, http_client, _ = _push_once(scenario)
                self.assertEqual(
                    committed.get(scenario),
                    _request_descriptor(http_client),
                    f"fixture 的 request 块已陈旧，重新生成：{GENERATOR_HINT}",
                )

    def test_observed_at_is_a_real_timestamp_before_masking(self) -> None:
        """抹掉之前它必须是真的 ISO 8601 带时区时间戳，不是被 pusher 忘掉的空字段。"""
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                payload, _, _, _ = _push_once(scenario)
                observed_at = payload["observed_at"]
                self.assertIsInstance(observed_at, str)
                parsed = datetime.fromisoformat(observed_at)
                self.assertIsNotNone(parsed.tzinfo, "observed_at 必须带时区偏移")

    # --- wire contract 自检 -------------------------------------------------

    def test_every_payload_carries_the_required_wire_contract_fields(self) -> None:
        """pusher 哪天悄悄不发某个合同字段，这里必须红。"""
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                payload = self.by_name[scenario]["payload"]
                missing = [field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in payload]
                self.assertEqual(missing, [], f"{scenario} payload 缺少 wire contract 字段")
                self.assertIsInstance(payload["schema_version"], int)
                self.assertIsInstance(payload["usage_daily"], list)
                release = payload["collector_release"]
                self.assertIsInstance(release, dict)
                self.assertIn("collector_version", release)
                self.assertIn("parser_schema_version", release)
                self.assertIn("release_channel", release)

    def test_ok_payload_carries_the_full_collection_evidence(self) -> None:
        """成功采集的 payload 必须带上两份 ccusage 报告、小时事实和账本运行记录。

        #91 之前这里是三份——``ccusage_blocks_report`` 已停采，见 ``DROPPED_LEGACY_FIELDS``。
        """
        payload = self.by_name[OK_SCENARIO]["payload"]
        missing = [field for field in REQUIRED_OK_FIELDS if field not in payload]
        self.assertEqual(missing, [], "成功场景 payload 缺少采集证据字段")

        self.assertEqual(payload["collection_status"], "ok")
        self.assertNotIn("error_type", payload)

        # usage_daily 必须来自 ccusage，且无 agent 的行被规范化成 unknown。
        self.assertEqual(
            [(row["period"], row["agent"]) for row in payload["usage_daily"]],
            [("2026-06-04", "claude"), ("2026-06-04", "codex"), ("2026-06-05", "unknown")],
        )

        # 小时事实必须落在报告声明的覆盖窗内：窗外的两行必须被剔除。
        windows = sorted(
            (fact["agent"], fact["window_start"]) for fact in payload["usage_hourly_facts"]
        )
        self.assertEqual(
            windows,
            [
                ("claude", "2026-06-04T09:00:00+08:00"),
                ("codex", "2026-06-04T09:00:00+08:00"),
                ("codex", "2026-06-04T10:00:00+08:00"),
            ],
        )

        # 账本运行记录必须两个 agent 都有，且带可比对的摘要。
        runs = {run["agent"]: run for run in payload["usage_ledger_runs"]}
        self.assertEqual(sorted(runs), ["claude", "codex"])
        for agent, run in runs.items():
            self.assertIsInstance(run["facts_digest"], str)
            self.assertEqual(len(run["facts_digest"]), 64, f"{agent} facts_digest 必须是 sha256")
            self.assertIsInstance(run["collector"], dict)

        # 一份 fixture 同时覆盖「配置里确认的账号」与「未确认的本机来源」两种归属。
        confidences = {fact["agent"]: fact["attribution_confidence"] for fact in payload["usage_hourly_facts"]}
        self.assertEqual(confidences["codex"], "account_confirmed")
        self.assertEqual(confidences["claude"], "unconfirmed_local_source")

        # 版本块必须把自升级 agent 写入的信息一起报上去。
        release = payload["collector_release"]
        self.assertEqual(release["build_sha"], OK_ENV["AI_USAGE_BUILD_SHA"])
        self.assertEqual(release["last_upgrade"]["status"], "succeeded")
        self.assertEqual(release["release_channel"], "stable")

    def test_error_payload_reports_the_failure_and_never_fakes_usage(self) -> None:
        """采集失败时必须如实上报失败，且不许伪造任何用量。"""
        payload = self.by_name[ERROR_SCENARIO]["payload"]
        missing = [field for field in REQUIRED_ERROR_FIELDS if field not in payload]
        self.assertEqual(missing, [], "失败场景 payload 缺少失败说明字段")

        self.assertEqual(payload["usage_daily"], [])
        self.assertNotEqual(payload["collection_status"], "ok")
        self.assertEqual(payload["error_type"], "missing_tool")
        self.assertTrue(payload["error_message"])

        for field in REQUIRED_OK_FIELDS:
            self.assertNotIn(field, payload, f"失败场景不该出现采集证据字段 {field}")

        # 没有环境变量时版本块退回常量兜底，但仍然要报。
        release = payload["collector_release"]
        self.assertNotIn("build_sha", release)
        self.assertEqual(release["last_upgrade"], {"status": "never"})
        self.assertEqual(release["release_channel"], "beta")

    def test_partial_payload_reports_ledger_usage_while_ccusage_is_broken(self) -> None:
        """ccusage 挂了但账本可用时，pusher 必须照常上报账本用量，而不是退化成状态心跳。

        这条路径的存在本身就是 #78 的前提：它是**唯一**会带 ``ccusage_daily_status``
        的路径，前两个场景都碰不到，所以该字段此前一直没有任何 fixture 守护。
        """
        payload = self.by_name[PARTIAL_SCENARIO]["payload"]

        self.assertEqual(payload["collection_status"], "ok")
        self.assertEqual(payload["usage_daily"], [])
        # ccusage 两份报告一份都没有——它压根没跑起来（blocks 已由 #91 整体停采，
        # 由 test_pusher_no_longer_sends_the_dropped_legacy_fields 全场景守着）。
        for field in ("ccusage_daily_report", "ccusage_session_report"):
            self.assertNotIn(field, payload)
        # 但账本用量必须照常上报，否则「ccusage 装挂了」会连带丢掉真实用量。
        self.assertTrue(payload["usage_hourly_facts"])
        self.assertEqual(
            sorted(run["agent"] for run in payload["usage_ledger_runs"]),
            ["claude", "codex"],
        )

        # **摘除的代价，据实钉死**：这条路径的 payload 里没有任何字段承载「ccusage 为什么
        # 失败」——collection_status 是 ok，error_type / error_message 都不存在
        # （它们只由 _push_source_status 那条全失败路径产出）。#78 之前这个原因由
        # ccusage_daily_status 携带，但它在生产用的 Worker 上零命中、本来就被静默丢弃。
        # 这条断言不是在庆祝，而是让「代价」有一个会随行为变化的守卫：哪天有人补了替代
        # 承载字段，这里会红，届时必须显式复核而不是顺手改掉。
        self.assertNotIn("error_type", payload)
        self.assertNotIn("error_message", payload)

    def test_pusher_no_longer_sends_the_dropped_legacy_fields(self) -> None:
        """采集端不许再发已摘除的字段（任何场景、任何失败形态）。

        #78 摘 ``ccusage_daily_status``，#91 摘 ``ccusage_blocks_report``。
        守卫覆盖**全部三条产出路径**，不只正面路径：成功、全失败心跳、部分失败。
        「断言字段不在 payload 里」不是恒真：payload 来自真实 ``DevicePusher.push()``，
        把 pusher 的采集段加回去这里就红（#91 交付时已实测过一次变异证据）。
        """
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                payload = self.by_name[scenario]["payload"]
                for field in DROPPED_LEGACY_FIELDS:
                    self.assertNotIn(
                        field,
                        payload,
                        f"{scenario}: {field} 已从采集端摘除（#78 / #91），"
                        "服务端两侧都只会把它当未知字段静默忽略，发出去没有任何意义",
                    )

    def test_payload_never_carries_raw_log_directory_paths(self) -> None:
        """采集端不得把 ``~/.claude`` / ``~/.codex`` 这类原始日志路径塞进 payload。"""
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                leaked = _find_forbidden_markers(self.by_name[scenario]["payload"], "payload")
                self.assertEqual(leaked, [], "payload 里出现了原始日志目录形态的字符串")

    # --- 内部工具 -----------------------------------------------------------

    def _load_committed_fixture(self) -> list[dict[str, Any]]:
        if not FIXTURE_PATH.exists():
            self.fail(
                f"采集端 payload 合同 fixture 不存在：{_relative(FIXTURE_PATH)}\n"
                "「采集端 Python ↔ 服务端 TS」这条 wire contract 目前没有任何 fixture 守护。\n"
                f"生成方式（fixture 必须由 owner 模块 pusher.py 产出，不许手写）：{GENERATOR_HINT}"
            )
        return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class TestDroppedLegacyFieldIsIgnoredByBothImplementations(unittest.TestCase):
    """向后兼容：老版本采集端仍会发已摘除的字段，两侧都必须忽略它。

    覆盖两个历史字段：#78 的 ``ccusage_daily_status`` 与 #91 的 ``ccusage_blocks_report``，
    探针清单见 ``LEGACY_PROBES``。这是**跨实现**测试的 Python 半边。Worker 半边在
    ``cloudflare/native-worker/test/ingest.test.ts``（「老版本采集端仍在发的 …」两条用例），
    读的是**同一批**探针定义并断言**同一组可观测结果**：

    1. 请求被接受，不报错（Python 不抛 ``IngestValidationError``，Worker 返回 200）；
    2. 字段不被解析（Python 的 ``IngestRequest`` 上没有这个属性；Worker 的
       ``IngestRequest`` 声明里没有这个字段）、不落库（Worker 侧断言 D1 可观测结果
       与不带该字段时逐行相等）。

    探针 payload 不是手写的：基座取自 owner 模块 ``pusher.py`` 产出的 fixture
    （探针各自钉死的场景那条记录），再叠加冻结在探针文件里的字段取值。
    那份取值本身是摘除前从真实 pusher 捕获的，当前 pusher 已经产不出它，
    所以它只能冻结、不能重新生成——这一点在探针文件里写明了。
    """

    maxDiff = None

    def test_probe_is_not_vacuous(self) -> None:
        """探针的基座里不许已经带着那个字段，否则探针没有在验证「额外的 legacy 字段」。

        注意不要断言「拼好的 payload 里有该字段」——``_legacy_probe_payload`` 就是
        ``payload[field] = value``，那样的断言由构造恒成立，什么都没守（#96 审查抓到）。
        真正非恒真的对象是**基座**：当前 pusher 产出的 fixture 场景必须已经不发该字段，
        探针叠加上去才构成「老采集端多发一个字段」的形态。
        """
        probed_fields = []
        for path, _expected_scenario in LEGACY_PROBES:
            probe = _legacy_probe(path)
            with self.subTest(field=probe["field"]):
                self.assertIn(probe["field"], DROPPED_LEGACY_FIELDS)
                self.assertNotIn(probe["field"], _fixture_record(probe["scenario"])["payload"])
            probed_fields.append(probe["field"])
        # 结构下限：每个已摘除字段都必须有自己的探针，缺一个就有一个字段没人守。
        self.assertEqual(sorted(probed_fields), sorted(DROPPED_LEGACY_FIELDS))

    def test_probe_is_frozen_to_the_only_scenario_that_ever_sent_the_field(self) -> None:
        """探针必须钉在摘除前唯一会发该字段的场景上。

        这条曾经写成「基座必须等于 pusher 此刻会发的 payload」，那是**恒真断言**：
        基座是 ``_legacy_probe_payload()`` 去掉该字段得来的，而后者本身就是
        ``_fixture_record(scenario)["payload"]`` 加上该字段，两边构造上是同一个对象的拷贝，
        ``_diff_paths`` 永远为空。基座「来自 owner 模块」由构造保证，不需要也无法用断言证明。

        真正会失效的是**场景选择**：探针若指向别的场景，它就不再重放「老采集端真的会发
        这个字段」的那条路径，下面的跨实现断言会退化成「对一个本来就不带该字段的场景
        验证两侧都忽略它」——依旧全绿，但什么都没验证。
        ``ccusage_daily_status`` 只在 partial 场景（ccusage 挂了但账本可用）出现过；
        ``ccusage_blocks_report`` 只在 ok 场景出现过（blocks 子进程只有 ccusage daily
        成功后才会跑）。
        """
        for path, expected_scenario in LEGACY_PROBES:
            probe = _legacy_probe(path)
            with self.subTest(field=probe["field"]):
                self.assertIn(probe["scenario"], SCENARIOS)
                self.assertEqual(
                    probe["scenario"],
                    expected_scenario,
                    f"{probe['field']} 的探针必须重放 {expected_scenario} 场景：摘除前 pusher "
                    "只在那个场景发该字段，换成别的场景这条跨实现覆盖就名存实亡",
                )

    def test_python_ingest_accepts_and_ignores_the_dropped_field(self) -> None:
        """Python 侧：不报错、不解析、不带进 ``IngestRequest``。

        **每一个形状都要过**，不只老采集端正常发出的那个：Worker 对未知顶层字段是
        「无论什么形状都忽略」，Python 侧只要对某个形状还会拒收，两个实现就不一致。
        `bypass_values` 里的形状正是被删掉的那些校验器当年会拒收的——
        只断言正面形状的话，把校验原样加回来这条断言照样绿（真踩过：#78 变异 2a
        一开始没能让这里变红）。
        """
        from ai_usage_widget.ingest import validate_ingest_payload

        for path, _expected_scenario in LEGACY_PROBES:
            probe = _legacy_probe(path)
            shapes = [probe["value"], *probe["bypass_values"]]
            self.assertGreater(len(shapes), 1, "绕过形状清单不能为空，否则只覆盖了正面路径")

            for shape in shapes:
                with self.subTest(field=probe["field"], shape=shape):
                    payload = _legacy_probe_payload(probe, shape)
                    payload["observed_at"] = LEGACY_PROBE_OBSERVED_AT

                    req = validate_ingest_payload(payload)

                    self.assertEqual(req.source_id, payload["source_id"])
                    self.assertFalse(
                        hasattr(req, probe["field"]),
                        f"IngestRequest 仍然带着 {probe['field']}——Python 侧还在解析这个字段，"
                        "与生产用的 Worker（把它当未知字段忽略）行为不一致",
                    )
                    # 账本用量必须照常被解析：忽略历史字段不等于连用量一起丢掉。
                    self.assertEqual(len(req.usage_hourly_facts), len(payload["usage_hourly_facts"]))


def _fixture_record(name: str) -> dict[str, Any]:
    records = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for record in records:
        if record["name"] == name:
            return record
    raise AssertionError(f"fixture 里没有场景 {name}，需要重新生成：{GENERATOR_HINT}")


def _legacy_probe(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _legacy_probe_payload(probe: dict[str, Any], shape: Any = _UNSET) -> dict[str, Any]:
    """拼出「老版本采集端会发出的 payload」：当前基座 + 冻结的历史字段。

    ``shape`` 用于换上 ``bypass_values`` 里的绕过形状；不传就是老采集端正常发出的那个。
    """
    payload = dict(_fixture_record(probe["scenario"])["payload"])
    payload[probe["field"]] = probe["value"] if shape is _UNSET else shape
    return payload


def _collect_payloads() -> list[dict[str, Any]]:
    """驱动真实 ``DevicePusher.push()``，产出 fixture 的全部记录。

    ``scripts/gen_collector_payload_fixture.py`` 从这里 import，
    保证「生成」与「校验」共用同一份逻辑——否则两边会各自漂移，
    最后产出一对自洽的错误。
    """
    records = []
    for scenario in SCENARIOS:
        payload, _, http_client, _ = _push_once(scenario)
        records.append(
            {
                "name": scenario,
                "request": _request_descriptor(http_client),
                "payload": _mask_volatile(payload),
            }
        )
    return records


def _request_descriptor(http_client: _CapturingHTTPClient) -> dict[str, Any]:
    """从**这次真正发生的请求**推导 wire 描述，一个字段都不许手写。

    - ``method``：pusher 实际调用的客户端方法（``IngestHTTPClient`` 只有 POST）。
    - ``path``：pusher 实际 POST 的 URL 的 path，不是「大家都知道是 /ingest」。
    - ``auth``：这次请求的 headers 里到底有没有 ``Authorization``。

    写死成 ``auth: True`` 会让 Worker 侧的 ``toEqual`` 变成两处字面量互相比对，
    永远为真、什么都不验证。
    """
    if http_client.last_url is None or http_client.last_headers is None:
        raise AssertionError("pusher 没有发出任何请求，无法推导 request 描述")
    return {
        "method": http_client.last_method,
        "path": urlparse(http_client.last_url).path,
        "auth": "Authorization" in http_client.last_headers,
    }


def _push_once(
    scenario: str,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], _ScriptedExecutor, _CapturingHTTPClient, dict[str, Any]]:
    """跑一次采集 + 上报，返回 pusher 真正发出的 payload。

    ``env`` 只在**证明推导逻辑真的会随行为改变**时才显式传入（例如故意抽走 token）。
    fixture 生成路径永远走场景自带的 env，否则 fixture 会随调用方漂移。
    """
    config, results, scenario_env = SCENARIO_SETUP[scenario]
    executor = _ScriptedExecutor(results)
    http_client = _CapturingHTTPClient()
    pusher = DevicePusher(
        config,
        executor=executor,
        http_client=http_client,
        retry_attempts=1,
        retry_sleep=lambda _seconds: None,
    )
    # clear=True：本机 shell 里恰好有 AI_USAGE_* 或 token 时不许影响 fixture。
    with patch.dict(os.environ, scenario_env if env is None else env, clear=True):
        result = pusher.push()
    payload = http_client.last_json
    if not isinstance(payload, dict):
        raise AssertionError(f"{scenario}: pusher 没有发出 payload（push 返回 {result}）")
    return payload, executor, http_client, result


def _mask_volatile(payload: dict[str, Any]) -> dict[str, Any]:
    """只抹顶层的运行时刻字段。

    刻意不做递归按名抹除：``account_evidence.observed_at`` 同名，但它来自报告里的
    固定 ``generated_at``，是真实数据，抹掉等于让 fixture 停止守护它。
    """
    masked = dict(payload)
    for field in VOLATILE_TOP_LEVEL_FIELDS:
        if field in masked:
            masked[field] = MASK
    return masked


def _find_forbidden_markers(value: Any, path: str) -> list[str]:
    if isinstance(value, str):
        lowered = value.lower()
        return [f"{path}: {marker}" for marker in FORBIDDEN_PATH_MARKERS if marker in lowered]
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            lowered_key = str(key).lower()
            # key 名专属规则：服务端只对 key 查 ssh，不对值查。
            found.extend(
                f"{path}.<key:{key}>: {marker}"
                for marker in FORBIDDEN_KEY_MARKERS
                if marker in lowered_key
            )
            found.extend(_find_forbidden_markers(str(key), f"{path}.<key:{key}>"))
            found.extend(_find_forbidden_markers(item, f"{path}.{key}"))
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found.extend(_find_forbidden_markers(item, f"{path}[{index}]"))
        return found
    return []


def _diff_paths(committed: Any, regenerated: Any, path: str) -> list[str]:
    """逐字段比对，返回「差在哪个 payload 的哪个字段」的可读清单。"""
    if isinstance(committed, dict) and isinstance(regenerated, dict):
        diffs: list[str] = []
        for key in sorted(set(committed) | set(regenerated)):
            child = f"{path}.{key}"
            if key not in committed:
                diffs.append(f"{child}: fixture 缺失该字段，pusher 现在会发出 {_brief(regenerated[key])}")
            elif key not in regenerated:
                diffs.append(f"{child}: fixture 里多出该字段，pusher 已不再发出（fixture={_brief(committed[key])}）")
            else:
                diffs.extend(_diff_paths(committed[key], regenerated[key], child))
        return diffs

    if isinstance(committed, list) and isinstance(regenerated, list):
        diffs = []
        if len(committed) != len(regenerated):
            diffs.append(f"{path}: 长度不同，fixture={len(committed)} regenerated={len(regenerated)}")
        for index in range(min(len(committed), len(regenerated))):
            label = _element_label(committed[index], index)
            diffs.extend(_diff_paths(committed[index], regenerated[index], f"{path}[{label}]"))
        return diffs

    if committed != regenerated or type(committed) is not type(regenerated):
        return [f"{path}: fixture={_brief(committed)} regenerated={_brief(regenerated)}"]
    return []


def _element_label(element: Any, index: int) -> str:
    if isinstance(element, dict):
        for key in ("name", "fact_id", "agent", "period", "hour", "window_start"):
            value = element.get(key)
            if isinstance(value, str):
                return f"{index}:{value}"
    return str(index)


def _brief(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=repr)
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS] + f"...(共 {len(text)} 字符)"
    return text


def _format_diffs(diffs: list[str]) -> str:
    shown = diffs[:MAX_DIFFS_REPORTED]
    lines = [f"  - {line}" for line in shown]
    if len(diffs) > len(shown):
        lines.append(f"  ...(另有 {len(diffs) - len(shown)} 处差异未列出，共 {len(diffs)} 处)")
    return "\n".join(lines)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    unittest.main()

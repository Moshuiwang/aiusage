"""采集端本地 outbox：断网不丢数的最小可靠投递能力（Issue #73）。

## 这个模块解决的用户问题

在它之前，采集端只有「进程内重试 3 次 + 每轮回扫 48 小时」。设备断网超过 48 小时、
本机 `~/.codex` / `~/.claude` 日志被回收、或长期离线之后恢复，这段时间的用量事实就
**永久消失**了——用户的历史数据实际上依赖「故障别超过 48 小时」的运气。

本模块提供一个持久缓冲：payload 先落本地 SQLite，送达并拿到明确 ACK 之后才删除。

## 它**不是**什么（边界，越过就是范围蔓延）

- 不是设备端的 D1 镜像，不是本地 facts 全量档案。**历史权威永远在云端 D1。**
  这里只存「还没送达的那些 payload」，送达即删。
- 不做任何口径计算：payload 进来什么样、出去还是什么样，一个字节都不改写。

## 磁盘上限：为什么选「拒绝新增」而不是「丢最旧」

上限触发时只有两种可能：拒绝新增，或丢弃最旧。本模块选**拒绝新增**（抛 `OutboxFull`）。

1. 「丢最旧」就是静默丢历史——**而这正是本 Issue 存在的理由**。为了防丢数而引入的机制，
   自身默认行为却是丢数，等于把问题从「48 小时窗口」搬到「磁盘容量窗口」，用户依然要
   赌运气，而且赌的这件事更不可见。
2. 队列里的条目**越旧越不可替代**。最新那一小时的原始日志大概率还躺在本机磁盘上，
   下一轮采集能重新读出来；而最旧那些条目对应的日志早已被工具回收，outbox 里这份就是
   世界上仅剩的一份。丢掉可再生的、保住不可再生的，是这两者之间唯一讲得通的取舍。
3. 「丢最旧」造成的是**历史中段的空洞**，事后无法从任何地方察觉；「拒绝新增」造成的是
   **当次上报显式失败**（`error_type="outbox_full"`），运维立刻看得见、可以处置。
   在「静默错」和「响亮地停下」之间，永远选后者。

代价要说清楚：上限打满且服务端长期不可用时，新数据确实进不来。这是有意的——那时候的
正确动作是排查网络或导出积压（`export_undelivered`），不是让机器自己决定牺牲哪段历史。

终态失败的 payload 进死信表（`dead_letter`），**同样计入磁盘上限**，不给它开一条不受控
增长的后门；它需要人工导出或清理，而不是被悄悄回收。

## 原子性

写 outbox 与 ACK 状态必须原子，否则「已删条目 + 没记回执」这种半状态就是一次静默丢失。
实现方式是 **SQLite 显式事务**（`isolation_level=None` + `BEGIN IMMEDIATE` / `COMMIT`，
异常时 `ROLLBACK`）：

- `enqueue()`：dedupe 删旧 + 插新 + 计数，一个事务；
- `ack()`：删条目 + 记投递回执，一个事务；
- `dead_letter()` / `purge_expired()` / `discard_undelivered()` 同理。

没有选文件 rename 方案：outbox 需要「按顺序取、按 id 单条删、按 dedupe_key 替换、
按 expires_at 过期」这些查询，用目录 + rename 表达要自己重造一个索引，而 SQLite 的
事务与崩溃恢复是现成且经过验证的。

## 每 OS 用户一库

库文件落 config 指定的数据目录（默认 `data/`，已 gitignore）。每个 OS 用户在自己的
账户上下文里跑采集、写自己的库，不跨用户读写。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from .version_contract import UNSUPPORTED_ERROR_TYPE


#: 默认磁盘上限。够缓冲上千次上报，同时不会在小机器上吃掉可观空间。
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

#: limit observations 的默认 TTL：过期就重新采集，不盲目补发旧值。
DEFAULT_LIMIT_TTL_SECONDS = 6 * 3600.0

DEFAULT_BACKOFF_BASE_SECONDS = 30.0
#: 退避封顶。断网几天之后不该出现「下次重试在 3 天后」这种自锁。
DEFAULT_BACKOFF_CAP_SECONDS = 900.0

DEFAULT_MAX_FLUSH_BATCH = 500

#: 默认库文件。**必须是绝对路径**（配置里可以写 `~`，解析时展开）。
#: 相对路径是这里唯一真正危险的配置错误：采集由 LaunchAgent / systemd 拉起，cwd 通常是
#: `/` 或 `$HOME`，和人在仓库根手工执行时不是同一个目录——同一台机器会开出两个库，
#: 缓冲了三天的数据从此没人再读，而且账面上完全看不出来。配置解析阶段直接拒绝。
#: 放在 `$HOME` 下也顺便让「每 OS 用户一库」变成结构上成立，而不是靠约定。
DEFAULT_OUTBOX_PATH = "~/.ai-usage/collector_outbox.sqlite"

KIND_USAGE = "usage"
KIND_LIMITS = "limits"

#: 一次投递的三种结局。
DELIVERED = "delivered"
RETRY = "retry"
TERMINAL = "terminal"

#: 合同级失败：同一份 payload 重发多少次都不会被收下，重试只会白白卡住队列。
#: 401 / 403 / 429 / 5xx **不在**此列——它们是「现在不行」，不是「永远不行」，
#: 判成终态就等于把 outbox 要防的丢失亲手实现了一遍。
TERMINAL_STATUS_CODES = frozenset({400, 409, 413, 422})


class OutboxError(RuntimeError):
    """outbox 相关错误的基类。"""


class OutboxFull(OutboxError):
    """磁盘上限已满，拒绝新增（不丢最旧，理由见模块 docstring）。"""


class OutboxNotDrained(OutboxError):
    """还有未交付的数据，不允许当作已排空处理。"""


@dataclass(frozen=True)
class OutboxConfig:
    """设备配置里的 `outbox` 块。

    `enabled=False` 但配置块存在，表示「已回退到直推」——pusher 据此知道要先确认
    磁盘上没有未排空的数据。整个配置块缺失才表示这台设备从来没启用过 outbox。
    """

    enabled: bool = False
    path: str = DEFAULT_OUTBOX_PATH
    max_bytes: int = DEFAULT_MAX_BYTES
    limit_ttl_seconds: float = DEFAULT_LIMIT_TTL_SECONDS
    max_flush_batch: int = DEFAULT_MAX_FLUSH_BATCH


@dataclass(frozen=True)
class OutboxEntry:
    entry_id: int
    kind: str
    payload: dict
    created_at: float
    attempts: int
    last_error: Optional[str]
    expires_at: Optional[float]


def classify_delivery(
    status_code: Optional[int],
    response: Optional[dict],
    *,
    exception: Optional[BaseException] = None,
) -> str:
    """判定一次投递的结局：`DELIVERED` / `RETRY` / `TERMINAL`。

    只看「这份 payload 再发一次还有没有可能被收下」，不看错误好不好看。
    """
    if exception is not None:
        return RETRY
    data = response or {}
    if isinstance(data, dict) and data.get("error_type") == UNSUPPORTED_ERROR_TYPE:
        # 服务端可以用 200 带 error_type 表达版本不兼容；本次上报根本没写入，
        # 而且重发同一份永远不会变。要先升级采集端。
        return TERMINAL
    if status_code == 200:
        return DELIVERED
    if status_code in TERMINAL_STATUS_CODES:
        return TERMINAL
    return RETRY


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        dedupe_key TEXT,
        payload TEXT NOT NULL,
        payload_bytes INTEGER NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        next_attempt_at REAL NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS outbox_ready ON outbox (next_attempt_at, id)",
    "CREATE INDEX IF NOT EXISTS outbox_dedupe ON outbox (kind, dedupe_key)",
    """
    CREATE TABLE IF NOT EXISTS dead_letter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        payload_bytes INTEGER NOT NULL,
        created_at REAL NOT NULL,
        failed_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

_COUNTERS = ("enqueued_total", "delivered_total", "expired_total", "dead_letter_total")


def _record_signature(records: Any) -> list[str]:
    """未交付记录集合的可比对指纹。

    只取 `state` + payload 本身：`attempts` / `last_error` 会在导出之后继续变化
    （重试仍在发生），拿它们比对会让「导出后马上丢弃」也对不上，把守卫变成噪音，
    最后一定会被人绕过去。真正要守的是「有没有哪条数据没进导出文件」。
    """
    if not isinstance(records, list):
        return ["<not-a-list>"]
    signatures = []
    for record in records:
        if not isinstance(record, dict):
            signatures.append("<not-a-record>")
            continue
        signatures.append(
            json.dumps(
                [record.get("state"), record.get("payload")],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return sorted(signatures)


class CollectorStore:
    """采集端本地 outbox + checkpoint/meta + 磁盘上限。

    线程/进程模型：每 OS 用户一库、同一时刻一个采集进程（上层已有 `FileLock`）。
    并发访问时靠 `BEGIN IMMEDIATE` 拿写锁，最坏情况是 `sqlite3.OperationalError`，
    调用方按普通失败处理，数据仍在磁盘上。
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        limit_ttl_seconds: float = DEFAULT_LIMIT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
    ) -> None:
        self.path = Path(path).expanduser()
        self.max_bytes = int(max_bytes)
        self.limit_ttl_seconds = float(limit_ttl_seconds)
        self.clock = clock
        self.backoff_base_seconds = float(backoff_base_seconds)
        self.backoff_cap_seconds = float(backoff_cap_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None：关掉 sqlite3 的隐式事务管理，事务边界由本模块显式控制，
        # 否则「删条目 + 记回执」会被拆成两个自动提交，崩在中间就是一次静默丢失。
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            self._conn.execute(statement)

    # --- 生命周期 -----------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: OutboxConfig,
        *,
        clock: Callable[[], float] = time.time,
    ) -> "CollectorStore":
        return cls(
            config.path,
            max_bytes=config.max_bytes,
            limit_ttl_seconds=config.limit_ttl_seconds,
            clock=clock,
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "CollectorStore":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # --- 写入 ---------------------------------------------------------------

    def enqueue(
        self,
        payload: dict,
        *,
        kind: str = KIND_USAGE,
        dedupe_key: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
    ) -> int:
        """把一份 payload 持久化进 outbox，返回条目 id。

        `dedupe_key` 只给 limit observations 用：同一个 key 的旧观测会被最新的替换，
        因为额度是「当前状态」，补发一小时前的旧值毫无意义。usage facts **绝不 dedupe**,
        每条都是不同覆盖窗口的事实，任何「只留最新」都是丢数据。

        `ttl_seconds` 同理只给 limit observations 用：过期就重新采集。
        usage facts 不设 TTL，持久补推直到明确 ACK 或终态合同错误。

        磁盘放不下时抛 `OutboxFull`，**不丢弃任何已有条目**。
        """
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_bytes = len(encoded.encode("utf-8"))
        now = float(self.clock())
        expires_at = now + float(ttl_seconds) if ttl_seconds else None

        with self._transaction():
            used_bytes = self._used_bytes_locked()
            replaced_bytes = 0
            if dedupe_key is not None:
                row = self._conn.execute(
                    "SELECT COALESCE(SUM(payload_bytes), 0) AS total FROM outbox"
                    " WHERE kind = ? AND dedupe_key = ?",
                    (kind, dedupe_key),
                ).fetchone()
                replaced_bytes = int(row["total"])
            projected = used_bytes + payload_bytes - replaced_bytes
            if projected > self.max_bytes:
                raise OutboxFull(
                    "本地 outbox 已达磁盘上限，拒绝新增（不丢弃已缓冲的历史）："
                    f"已用 {used_bytes} 字节 / 上限 {self.max_bytes} 字节，"
                    f"本次需要 {payload_bytes} 字节。请先恢复网络排空积压，"
                    f"或导出后处理：{self.path}"
                )
            if dedupe_key is not None:
                self._conn.execute(
                    "DELETE FROM outbox WHERE kind = ? AND dedupe_key = ?", (kind, dedupe_key)
                )
            entry_id = self._insert_entry(
                kind=kind,
                dedupe_key=dedupe_key,
                encoded=encoded,
                payload_bytes=payload_bytes,
                created_at=now,
                expires_at=expires_at,
            )
            self._bump_counter("enqueued_total", 1)
        return entry_id

    def ack(self, entry_id: int) -> None:
        """明确 ACK：删除条目并记一笔投递回执，两者同一个事务。

        送达之后顺手清掉全部退避——一条送达就证明网络回来了，
        其余条目没有理由继续各等各的。
        """
        with self._transaction():
            self._conn.execute("DELETE FROM outbox WHERE id = ?", (entry_id,))
            self._record_ack_receipt(entry_id)
            self._conn.execute("UPDATE outbox SET next_attempt_at = 0")

    def record_failure(self, entry_id: int, error: str) -> float:
        """可重试失败：累计尝试次数并施加指数退避（封顶），返回下次可尝试时刻。"""
        now = float(self.clock())
        with self._transaction():
            row = self._conn.execute(
                "SELECT attempts FROM outbox WHERE id = ?", (entry_id,)
            ).fetchone()
            attempts = (int(row["attempts"]) if row else 0) + 1
            delay = min(
                self.backoff_base_seconds * (2 ** (attempts - 1)),
                self.backoff_cap_seconds,
            )
            next_attempt_at = now + delay
            self._conn.execute(
                "UPDATE outbox SET attempts = ?, last_error = ?, next_attempt_at = ? WHERE id = ?",
                (attempts, error, next_attempt_at, entry_id),
            )
        return next_attempt_at

    def dead_letter(self, entry_id: int, reason: str) -> None:
        """终态失败：移出待补推队列，但**连同 payload 一起留档**。

        终态意味着「重发多少次都不会被收下」，继续占着队头只会卡住后面的历史。
        但直接删掉就是静默丢弃，所以进死信表，可导出、可人工处置，
        并计入磁盘上限（不给不受控增长留后门）。
        """
        now = float(self.clock())
        with self._transaction():
            row = self._conn.execute("SELECT * FROM outbox WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                return
            self._conn.execute(
                "INSERT INTO dead_letter (kind, payload, payload_bytes, created_at, failed_at,"
                " attempts, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["kind"],
                    row["payload"],
                    row["payload_bytes"],
                    row["created_at"],
                    now,
                    row["attempts"],
                    reason,
                ),
            )
            self._conn.execute("DELETE FROM outbox WHERE id = ?", (entry_id,))
            self._bump_counter("dead_letter_total", 1)

    def clear_backoff(self) -> None:
        with self._transaction():
            self._conn.execute("UPDATE outbox SET next_attempt_at = 0")

    def purge_expired(self) -> int:
        """清掉过期的 limit observations，返回条数，并**计数**（过期丢弃也不许无声）。"""
        now = float(self.clock())
        with self._transaction():
            rows = self._conn.execute(
                "SELECT COUNT(*) AS total FROM outbox WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            ).fetchone()
            removed = int(rows["total"])
            if removed:
                self._conn.execute(
                    "DELETE FROM outbox WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
                )
                self._bump_counter("expired_total", removed)
        return removed

    # --- 读取 ---------------------------------------------------------------

    def pending(
        self,
        *,
        limit: Optional[int] = None,
        ignore_backoff: bool = False,
        kind: Optional[str] = None,
    ) -> list[OutboxEntry]:
        """当前**可以尝试投递**的条目，最旧优先。

        默认排除退避中的条目与已过期的 limit observations。
        `ignore_backoff=True` 用于排空 / 导出 / 巡检这类「我要看全部」的场景。

        `kind` 是**补推方必须传**的：用量事实与额度观测共用同一个库，但走两个不同的
        ingest 端点。不过滤就会把用量事实 POST 到 `/ingest-limits`（服务端 400 →
        判成终态 → 进死信表），一条已经安全落盘的历史就此永远不会再补推——
        方向正好和 outbox 要解决的问题相反。
        排空 / 导出 / 巡检则**必须不传**：漏看一种 kind 等于放行未交付数据。
        """
        now = float(self.clock())
        sql = "SELECT * FROM outbox WHERE (expires_at IS NULL OR expires_at > ?)"
        params: list[Any] = [now]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if not ignore_backoff:
            sql += " AND next_attempt_at <= ?"
            params.append(now)
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._to_entry(row) for row in self._conn.execute(sql, params)]

    def pending_count(self) -> int:
        """还没交付的条目总数——**包含退避中的**。

        退避中的条目不是「消失了」，只是这一轮不该重试；把它算作 0
        会让排空检查放行一批还没送出去的数据。
        """
        now = float(self.clock())
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM outbox WHERE (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ).fetchone()
        return int(row["total"])

    def dead_letter_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS total FROM dead_letter").fetchone()["total"])

    def dead_letters(self) -> list[dict]:
        return [
            {
                "kind": row["kind"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
                "failed_at": row["failed_at"],
                "attempts": row["attempts"],
                "reason": row["reason"],
            }
            for row in self._conn.execute("SELECT * FROM dead_letter ORDER BY id ASC")
        ]

    def used_bytes(self) -> int:
        return self._used_bytes_locked()

    def stats(self) -> dict:
        counters = {name: 0 for name in _COUNTERS}
        for row in self._conn.execute("SELECT key, value FROM meta"):
            if row["key"] in counters:
                counters[row["key"]] = int(row["value"])
        counters.update(
            {
                "pending": self.pending_count(),
                "dead_letters": self.dead_letter_count(),
                "used_bytes": self.used_bytes(),
                "max_bytes": self.max_bytes,
                "path": str(self.path),
            }
        )
        return counters

    # --- 排空 / 回退 --------------------------------------------------------

    def undelivered_count(self) -> int:
        """未交付总量 = 待补推（含退避中）+ 死信。回退演练的判据。"""
        return self.pending_count() + self.dead_letter_count()

    def assert_drained(self) -> None:
        """确认没有未交付数据，否则抛 `OutboxNotDrained`。

        回退到直推之前必须过这一关：**不允许静默丢弃**。退避中的条目和死信同样算
        「还没交付」——只看 `pending()` 会把它们漏掉，那正是最容易发生的静默丢失。
        """
        pending = self.pending_count()
        dead = self.dead_letter_count()
        if pending or dead:
            raise OutboxNotDrained(
                f"本地 outbox 还有 {pending + dead} 条未交付数据"
                f"（待补推 {pending} 条、终态留档 {dead} 条），不允许直接回退到直推。\n"
                f"排空方式二选一：恢复网络后继续上报直到清空；"
                f"或导出后显式丢弃（export_undelivered / discard_undelivered）。\n"
                f"库文件：{self.path}"
            )

    def export_undelivered(self, dest: str | os.PathLike[str]) -> int:
        """把全部未交付数据（含退避中与死信）导出成 JSON，返回条数。

        导出**不删除任何东西**：导出即丢弃是另一种静默丢失。
        清空要显式调用 `discard_undelivered(exported_to=...)`。
        """
        records = self._undelivered_records()
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        temp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        # rename 是原子的：要么看到完整导出，要么看不到文件，不会出现半份导出被当成已排空。
        os.replace(temp, destination)
        return len(records)

    def discard_undelivered(self, *, exported_to: str | os.PathLike[str]) -> int:
        """清空未交付数据。**前提是这批数据确实已经被导出**。

        没有「无条件清空」的入口：那等于给静默丢弃开一扇门。而「导出文件存在」也**不等于**
        「这批数据被导出过」——导出之后又攒了几条，或者拿上一轮的陈旧导出文件来清空，
        都会让从没被导出的数据一起消失。所以这里逐条比对导出内容与当前未交付集合，
        对不上就拒绝，让人重新导出。
        """
        destination = Path(exported_to)
        if not destination.exists():
            raise OutboxNotDrained(
                f"拒绝清空 outbox：导出文件不存在（{destination}）。"
                "先 export_undelivered() 拿到可恢复的副本，再丢弃。"
            )
        try:
            exported = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OutboxNotDrained(
                f"拒绝清空 outbox：导出文件读不出来（{destination}）：{exc}"
            ) from None
        current = self._undelivered_records()
        if _record_signature(exported) != _record_signature(current):
            raise OutboxNotDrained(
                f"拒绝清空 outbox：导出文件与当前未交付数据不一致"
                f"（导出 {len(exported) if isinstance(exported, list) else '?'} 条，"
                f"当前 {len(current)} 条）。\n"
                "很可能是导出之后又缓冲了新数据，或者用了上一轮的旧导出文件。"
                "请重新 export_undelivered() 之后再丢弃。"
            )
        with self._transaction():
            removed = self.pending_count() + self.dead_letter_count()
            self._conn.execute("DELETE FROM outbox")
            self._conn.execute("DELETE FROM dead_letter")
            self._set_meta("last_export_path", str(destination))
            self._set_meta("last_export_at", str(float(self.clock())))
        return removed

    # --- 内部实现 -----------------------------------------------------------

    def _undelivered_records(self) -> list[dict]:
        """未交付数据的可导出表示（待补推 + 死信），导出与校验共用同一份逻辑。"""
        records: list[dict] = [
            {
                "state": "pending",
                "kind": entry.kind,
                "created_at": entry.created_at,
                "attempts": entry.attempts,
                "last_error": entry.last_error,
                "payload": entry.payload,
            }
            for entry in self.pending(ignore_backoff=True)
        ]
        records.extend({"state": "dead_letter", **record} for record in self.dead_letters())
        return records

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _insert_entry(
        self,
        *,
        kind: str,
        dedupe_key: Optional[str],
        encoded: str,
        payload_bytes: int,
        created_at: float,
        expires_at: Optional[float],
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO outbox (kind, dedupe_key, payload, payload_bytes, created_at,"
            " expires_at, attempts, last_error, next_attempt_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 0)",
            (kind, dedupe_key, encoded, payload_bytes, created_at, expires_at),
        )
        return int(cursor.lastrowid)

    def _record_ack_receipt(self, entry_id: int) -> None:
        self._bump_counter("delivered_total", 1)
        self._set_meta("last_ack_at", str(float(self.clock())))
        self._set_meta("last_ack_entry_id", str(entry_id))

    def _bump_counter(self, key: str, delta: int) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(meta.value AS INTEGER) + ? AS TEXT)",
            (key, str(delta), delta),
        )

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )

    def _used_bytes_locked(self) -> int:
        row = self._conn.execute(
            "SELECT (SELECT COALESCE(SUM(payload_bytes), 0) FROM outbox)"
            " + (SELECT COALESCE(SUM(payload_bytes), 0) FROM dead_letter) AS total"
        ).fetchone()
        return int(row["total"])

    def _to_entry(self, row: sqlite3.Row) -> OutboxEntry:
        return OutboxEntry(
            entry_id=int(row["id"]),
            kind=str(row["kind"]),
            payload=json.loads(row["payload"]),
            created_at=float(row["created_at"]),
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
            expires_at=float(row["expires_at"]) if row["expires_at"] is not None else None,
        )

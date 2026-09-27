"""AI 账户不可逆指纹（#181）。

目标：把「同一账户在不同机器上出现」这件事变成可核对的，同时绝不让邮箱、token 等
凭据原文进入上报 payload、日志或测试输出。

设计边界（#181 报告里写明的保守选择）：

- 这里只做两件纯计算/纯解析的事：从本地配置对象里挑出**非秘密的账户稳定标识**
  （Claude 的 ``oauthAccount.accountUuid``、Codex 的 ``tokens.account_id`` 等），
  以及把 ``(provider, stable_account_id)`` 算成一个不可逆指纹。
- 读文件的便捷函数（``claude_account_fingerprint`` / ``codex_account_fingerprint``）
  **要求调用方显式传入路径**，不提供"自动猜 ``~/.claude.json``"之类的零配置默认值。
  这不是偷懒：本仓库里所有 provider 的凭据文件路径（``--codex-auth-file``、
  ``--claude-auth-file``、``CLAUDE_CONFIG_DIR`` 等）都是显式配置，从没有过自动探测
  真实 HOME 目录的默认值——这里延续同一惯例，也避免任何未显式配置的调用路径
  在开发机/CI 上意外去碰真实的 ``~/.claude``、``~/.codex``。
- 任何一步读不到、解析不出、字段缺失，都返回 ``None``（降级，不猜，不抛异常）。
  调用方据此保持现有占位值，不中断采集。
- 只覆盖 Claude / Codex：两者都有本机可读的静态凭据文件。Antigravity 没有这样的文件，
  唯一途径是活跑的 language server RPC；接线会给主采集链路新增一次进程探测和网络往返，
  属于另一个行为面，这里按最简实现原则不做，也不留猜字段名的死代码——需要时按真实
  RPC 响应样本重新实现（#181 报告里的已知缺口）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


#: 指纹计算的领域分隔前缀。改这个值等于让所有历史指纹失效，不要随手改。
FINGERPRINT_SALT = "aiusage-account-v1"

#: 指纹里十六进制摘要的长度（截断 sha256）。
FINGERPRINT_HEX_LENGTH = 24


def compute_account_fingerprint(provider: str, stable_account_id: str) -> str:
    """把 ``(provider, stable_account_id)`` 算成一条不可逆指纹。

    指纹格式固定为 ``fp:<provider>:<24 位十六进制>``，其中十六进制部分是
    ``sha256("aiusage-account-v1:" + provider + ":" + stable_account_id)`` 的前
    ``FINGERPRINT_HEX_LENGTH`` 位。同一账户在任何机器上算出的指纹永远相同；
    换一个账户或换一个 provider，指纹几乎必然不同。该哈希不可逆——拿到指纹
    推不出 ``stable_account_id`` 原文。
    """
    provider_clean = (provider or "").strip()
    stable_clean = (stable_account_id or "").strip()
    if not provider_clean or not stable_clean:
        raise ValueError("compute_account_fingerprint requires non-empty provider and stable_account_id")
    material = f"{FINGERPRINT_SALT}:{provider_clean}:{stable_clean}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:FINGERPRINT_HEX_LENGTH]
    return f"fp:{provider_clean}:{digest}"


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_claude_stable_account_id(config: Any) -> str | None:
    """从 Claude Code 本地配置对象（``~/.claude.json`` 反序列化结果）里取账户稳定 ID。

    只认 ``oauthAccount.accountUuid``（顶层 ``accountUuid`` 作为兜底）——这是账户
    UUID，不是邮箱或 token。配置形状不对、字段缺失或为空字符串都返回 ``None``。
    """
    if not isinstance(config, dict):
        return None
    oauth_account = config.get("oauthAccount")
    if isinstance(oauth_account, dict):
        value = _clean_string(oauth_account.get("accountUuid"))
        if value:
            return value
    return _clean_string(config.get("accountUuid"))


def read_codex_stable_account_id(auth: Any) -> str | None:
    """从 Codex CLI ``auth.json`` 反序列化结果里取账户稳定 ID（``tokens.account_id`` 等）。"""
    if not isinstance(auth, dict):
        return None
    tokens = auth.get("tokens")
    if isinstance(tokens, dict):
        for key in ("account_id", "accountId"):
            value = _clean_string(tokens.get(key))
            if value:
                return value
    for key in ("account_id", "accountId"):
        value = _clean_string(auth.get(key))
        if value:
            return value
    account = auth.get("account")
    if isinstance(account, dict):
        for key in ("account_id", "accountId", "id"):
            value = _clean_string(account.get(key))
            if value:
                return value
    return None


def _read_json_file(path: str | Path) -> Any:
    """尽力读一份本地 JSON 文件；任何 I/O 或解析失败都返回 ``None``，不抛异常。"""
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def claude_account_fingerprint(config_path: str | Path) -> str | None:
    """读取指定路径的 Claude 本地配置文件并算出指纹；读不到/解析不出返回 ``None``。

    ``config_path`` 必须由调用方显式给出——本函数不猜测 ``~/.claude.json``。
    """
    payload = _read_json_file(config_path)
    stable_id = read_claude_stable_account_id(payload)
    if not stable_id:
        return None
    return compute_account_fingerprint("claude", stable_id)


def codex_account_fingerprint(auth_path: str | Path) -> str | None:
    """读取指定路径的 Codex ``auth.json`` 并算出指纹；读不到/解析不出返回 ``None``。

    ``auth_path`` 必须由调用方显式给出——本函数不猜测 ``~/.codex/auth.json``。
    """
    payload = _read_json_file(auth_path)
    stable_id = read_codex_stable_account_id(payload)
    if not stable_id:
        return None
    return compute_account_fingerprint("codex", stable_id)

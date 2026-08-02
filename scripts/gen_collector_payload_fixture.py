"""重新生成 ``cloudflare/native-worker/test/collector_payload_fixture.json``。

这份 fixture 是「采集端 Python ↔ 服务端 TypeScript」这条 **wire contract** 的合同证据。
#67 之后服务端收敛为 Worker 单实现，但采集端永远是 Python（必须读本机 ccusage /
mswusage 与 OS 上下文），所以这条边界是**永久的跨语言边界**，消灭不掉，只能治理。

fixture 的 owner 是 ``src/ai_usage_widget/pusher.py``——``/ingest`` payload 的唯一产出方。
本脚本不自己拼 payload：生成逻辑的 owner 是 ``tests/test_collector_payload_contract.py``
（``FIXTURE_PATH`` + ``_collect_payloads()``），它用 fake executor 喂固定的 ccusage /
mswusage 输出，驱动**真实的** ``DevicePusher.push()``，从 HTTP 客户端手里接住它真正发出去
的那个 dict。本脚本只负责把那份产物写到磁盘。同一个行为只允许有一份实现，否则「生成」与
「校验」会各自漂移，最后产出一对自洽的错误。

**fixture 一个字节都不许手写、不许手改**（AGENTS.md：手写 fixture 会和现实脱节，且脱节
方向正好是「实现者以为的样子」）。要改它，只能先改 pusher，再跑这个脚本。

消费方有两个：

- ``cloudflare/native-worker/test/ingest.test.ts``：拿同一份 fixture 断言服务端确实能收下
  采集端真实发出的 payload。
- ``tests/test_collector_payload_contract.py``：每次都重新生成一遍并与已提交的 fixture
  逐字段比对，让 fixture 能**自动发现自己陈旧**。

只有在 pusher 的 payload 形状**确实**要变时才跑这个脚本：

    PYTHONPATH=src python3 scripts/gen_collector_payload_fixture.py

跑完必须逐条复核
``git diff -- cloudflare/native-worker/test/collector_payload_fixture.json``——
**改 fixture 等于改一条 wire contract**：多一个字段、少一个字段或改掉一个既有值，都意味着
服务端 ingest 要跟着变。复核完还必须确认 Worker 侧 ``ingest.test.ts`` 是否仍然成立，
payload 变了而服务端没跟上，正是这条边界要拦的事故。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from test_collector_payload_contract import FIXTURE_PATH, _collect_payloads  # noqa: E402


def main() -> None:
    records = _collect_payloads()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(records)} records to {FIXTURE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

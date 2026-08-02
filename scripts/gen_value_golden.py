"""重新生成 ``cloudflare/native-worker/test/value_golden.json``。

golden 是 Python 读模型（``snapshot_builder`` + ``mobile_summary``）在固定 fixture、
固定时间、固定时区下的输出快照，唯一消费方是
``cloudflare/native-worker/test/parity.test.ts``——Native Worker 拿它做跨实现 parity。

生成逻辑的 owner 是 ``tests/test_value_golden_freshness.py``（``GOLDEN_PATH`` +
``_collect_records()``），本脚本只负责把它的产物写到磁盘：同一个行为只允许有一份实现，
否则「生成」与「校验」会各自漂移，最后产出一对自洽的错误。

只有在读模型的输出**确实**要变时才跑这个脚本：

    PYTHONPATH=src python3 scripts/gen_value_golden.py

跑完必须逐条复核 `git diff -- cloudflare/native-worker/test/value_golden.json`——
golden 里改掉一个既有值，等于悄悄改掉一条跨实现验收标准。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from test_value_golden_freshness import GOLDEN_PATH, _collect_records  # noqa: E402


def main() -> None:
    records = _collect_records()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(records)} records to {GOLDEN_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

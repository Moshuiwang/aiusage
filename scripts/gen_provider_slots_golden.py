"""重新生成 provider_slots 跨实现 golden（Issue #61 验收 6）。

golden 是**验收预期**，不是实现快照：初版逐条手写，两侧实现都必须匹配它。
只有在预期本身确实要改时才跑这个脚本，跑完必须逐条复核 `git diff`——
golden 里改掉一个值，等于改掉一条验收标准。

    PYTHONPATH=src python3 scripts/gen_provider_slots_golden.py

消费方：
- tests/test_provider_slots_parity.py（Python 读模型）
- cloudflare/native-worker/test/provider-slots-parity.test.ts（Native Worker）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from test_provider_slots_parity import GOLDEN_PATH, _collect_records  # noqa: E402


def main() -> None:
    records = _collect_records()
    GOLDEN_PATH.write_text(
        json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(records)} records to {GOLDEN_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

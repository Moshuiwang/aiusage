"""双 harness reviewer 的核心检查项不能静默漂移。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEWER_FILES = (
    ROOT / ".claude/agents/reviewer.md",
    ROOT / ".codex/agents/reviewer.toml",
)
EXPECTED_ANCHORS = {
    "scope-integrity",
    "contract-stability",
    "security-boundary",
    "test-strength",
    "artifact-conservation",
}


class ReviewerGovernanceTests(unittest.TestCase):
    def test_both_reviewers_declare_the_same_core_anchors(self) -> None:
        declared_by_file: dict[str, set[str]] = {}

        for path in REVIEWER_FILES:
            content = path.read_text(encoding="utf-8")
            declared_by_file[str(path.relative_to(ROOT))] = {
                anchor for anchor in EXPECTED_ANCHORS if f"[{anchor}]" in content
            }

        for path, anchors in declared_by_file.items():
            self.assertEqual(EXPECTED_ANCHORS, anchors, f"{path} 核心检查锚点漂移")


if __name__ == "__main__":
    unittest.main()

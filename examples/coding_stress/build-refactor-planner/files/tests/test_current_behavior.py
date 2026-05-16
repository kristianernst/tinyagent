# ruff: noqa: E402,I001

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flowforge.parser import parse_backlog
from flowforge.reporting import render_summary


class CurrentBehaviorTests(unittest.TestCase):
    def test_summary_counts_existing_statuses(self) -> None:
        items = parse_backlog(Path("data/backlog.txt").read_text(encoding="utf-8"))
        summary = render_summary(items)

        self.assertIn("total_items: 6", summary)
        self.assertIn("todo: 3", summary)
        self.assertIn("doing: 1", summary)
        self.assertIn("done: 1", summary)
        self.assertIn("blocked: 1", summary)


if __name__ == "__main__":
    unittest.main()

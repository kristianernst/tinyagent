# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flowforge.parser import parse_backlog
from flowforge.planner import plan_milestone
from flowforge.reporting import render_json, render_markdown


def sample_items():
    return parse_backlog(Path("data/backlog.txt").read_text(encoding="utf-8"))


class TargetBehaviorTests(unittest.TestCase):
    def test_parser_keeps_dependencies_tags_and_defaults(self) -> None:
        items = {item.key: item for item in sample_items()}

        self.assertEqual(items["FF-101"].depends_on, ("FF-100",))
        self.assertEqual(items["FF-101"].tags, ("backend", "data"))
        self.assertEqual(items["FF-105"].depends_on, ())
        self.assertEqual(items["FF-105"].tags, ("frontend", "ux"))

    def test_plan_respects_dependencies_capacity_and_blocked_work(self) -> None:
        plan = plan_milestone(sample_items(), capacity_by_owner={"ana": 4, "bo": 5, "cy": 3})

        self.assertEqual([[item.key for item in wave.items] for wave in plan.waves], [["FF-103", "FF-101", "FF-105"], ["FF-102"]])
        self.assertEqual([item.key for item in plan.done], ["FF-100"])
        self.assertEqual([item.key for item in plan.blocked], ["FF-104"])
        self.assertEqual(plan.waves[0].remaining_capacity["ana"], 2)
        self.assertEqual(plan.waves[0].remaining_capacity["bo"], 0)
        self.assertEqual(plan.waves[0].remaining_capacity["cy"], 1)

    def test_renderers_include_waves_and_blocked_items(self) -> None:
        plan = plan_milestone(sample_items(), capacity_by_owner={"ana": 4, "bo": 5, "cy": 3})

        markdown = render_markdown(plan)
        self.assertIn("## Wave 1", markdown)
        self.assertIn("FF-101", markdown)
        self.assertIn("## Blocked", markdown)
        self.assertIn("FF-104", markdown)

        payload = json.loads(render_json(plan))
        self.assertEqual(payload["waves"][0]["items"][0]["key"], "FF-103")
        self.assertEqual(payload["blocked"][0]["key"], "FF-104")


if __name__ == "__main__":
    unittest.main()

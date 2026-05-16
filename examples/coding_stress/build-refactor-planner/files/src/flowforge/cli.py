"""FlowForge CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from flowforge.parser import parse_backlog
from flowforge.reporting import render_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flowforge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    summary = subparsers.add_parser("summary")
    summary.add_argument("backlog")
    args = parser.parse_args(argv)

    if args.command == "summary":
        items = parse_backlog(Path(args.backlog).read_text(encoding="utf-8"))
        print(render_summary(items), end="")
        return 0
    parser.error("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

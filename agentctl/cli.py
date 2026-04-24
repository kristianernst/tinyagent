"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse

from agentd import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="Control the tinyagent harness.",
    )
    parser.add_argument("--version", action="version", version=f"agentctl {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="Run an agent task.")
    subparsers.add_parser("replay", help="Replay a recorded agent run.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    parser.error(f"command '{args.command}' is not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from agentd import __version__
from agentd.events import ConsoleTextSink, JsonlStreamSink, debug_level_from_env
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider, ProviderError
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.providers.openai_compat import OpenAICompatibleProvider
from agentd.replay import replay_run
from agentd.state import ModelResponse, ToolCall
from agentd.tools import default_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="Control the tinyagent harness.",
    )
    parser.add_argument("--version", action="version", version=f"agentctl {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="Run an agent task.")
    run_parser.add_argument("task", help="Task for the agent.")
    run_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    run_parser.add_argument("--workspace", default=".")
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--output-dir", type=Path)
    run_parser.add_argument(
        "--stream",
        choices=["off", "text", "jsonl"],
        default="off",
        help="Stream model progress live while preserving the run trace.",
    )
    run_parser.add_argument(
        "--debug",
        type=int,
        help="Live stream verbosity. Defaults to TINYAGENT_DEBUG or 0.",
    )

    replay_parser = subparsers.add_parser("replay", help="Replay a recorded agent run.")
    replay_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        try:
            debug_level = _debug_level(args.debug)
        except ValueError as exc:
            print(f"debug error: {exc}")
            return 2
        try:
            model = _model_for(args.provider, args.task)
        except ProviderError as exc:
            print(f"provider error: {exc}")
            return 1
        kernel = Kernel(
            model=model,
            profile=ApexCoderProfile(),
            tools=default_tools(),
            policy=default_policy(),
            stream=args.stream != "off",
            event_sink=_stream_sink(args.stream, debug_level),
        )
        state = kernel.run(args.task, workspace=args.workspace, run_id=args.run_id, output_dir=args.output_dir)
        if args.stream == "jsonl":
            return 1 if state.failed else 0
        if args.stream == "text" and state.final_output:
            print()
        print(f"run_id: {state.run_id}")
        print(f"output_dir: {state.output_dir}")
        print(f"status: {'failed' if state.failed else 'completed'}")
        if state.failed:
            print(f"failure: {state.failure_reason}")
            return 1
        if state.final_output and args.stream != "text":
            print(state.final_output)
        return 0

    if args.command == "replay":
        print(replay_run(args.run_path), end="")
        return 0

    parser.error(f"unknown command '{args.command}'")
    return 2


def _model_for(provider: str, task: str):
    if provider == "fake":
        return FakeModelProvider(_fake_responses(task))
    if provider == "openai-compatible":
        return OpenAICompatibleProvider.from_env()
    raise ValueError(f"Unknown provider: {provider}")


def _debug_level(level: int | None) -> int:
    if level is None:
        return debug_level_from_env()
    if level < 0:
        raise ValueError("--debug must be non-negative.")
    return level


def _stream_sink(mode: str, debug_level: int):
    if mode == "text":
        return ConsoleTextSink(sys.stdout)
    if mode == "jsonl":
        return JsonlStreamSink(sys.stdout, debug_level=debug_level)
    return None


def _fake_responses(task: str) -> list[ModelResponse]:
    path = _first_mentioned_file(task)
    if path is None:
        return [ModelResponse(content="Fake run finished.", finish_reason="stop")]
    return [
        ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"sed -n '1,120p' {path}"}),)),
        ModelResponse(content=f"Fake run finished after reading {path}.", finish_reason="stop"),
    ]


def _first_mentioned_file(task: str) -> str | None:
    match = re.search(r"(?P<path>[\w./-]+\.[A-Za-z0-9_+-]+)", task)
    return match.group("path") if match else None


if __name__ == "__main__":
    raise SystemExit(main())

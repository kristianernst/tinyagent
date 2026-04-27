"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from agentd import __version__
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider, OpenAICompatibleProvider, ProviderError
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
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
            model = _model_for(args.provider, args.task)
        except ProviderError as exc:
            print(f"provider error: {exc}")
            return 1
        kernel = Kernel(
            model=model,
            profile=ApexCoderProfile(),
            tools=default_tools(),
            policy=default_policy(),
        )
        state = kernel.run(args.task, workspace=args.workspace, run_id=args.run_id, output_dir=args.output_dir)
        print(f"run_id: {state.run_id}")
        print(f"output_dir: {state.output_dir}")
        print(f"status: {'failed' if state.failed else 'finished'}")
        if state.failed:
            print(f"failure: {state.failure_reason}")
            return 1
        if state.summary:
            print(state.summary)
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

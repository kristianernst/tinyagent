"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import re
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agentd import __version__
from agentd.eval_runner import default_eval_output_dir, render_eval_report, run_eval_suite
from agentd.events import ConsoleTextSink, JsonlStreamSink, debug_level_from_env
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider, ProviderError
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.providers.openai_compat import OpenAICompatibleProvider
from agentd.replay import replay_run
from agentd.run_control import CancelToken, RunCancelled
from agentd.run_record import load_run_record, render_run_inspection
from agentd.state import ApprovalRequest, ApprovalResolution, ModelResponse, RunState, ToolCall
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
    run_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="auto")
    run_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    run_parser.add_argument("--sandbox-mode", choices=["none"], default="none")
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

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a recorded agent run.")
    inspect_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")

    eval_parser = subparsers.add_parser("eval", help="Run a local eval suite.")
    eval_parser.add_argument("suite_path", type=Path, help="Directory containing eval cases.")
    eval_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    eval_parser.add_argument("--output-dir", type=Path)
    eval_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="current")
    eval_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    eval_parser.add_argument("--sandbox-mode", choices=["none"], default="none")
    eval_parser.add_argument(
        "--stream",
        choices=["off", "text", "jsonl"],
        default="off",
        help="Stream model progress live while preserving each run trace.",
    )
    eval_parser.add_argument(
        "--debug",
        type=int,
        help="Live stream verbosity. Defaults to TINYAGENT_DEBUG or 0.",
    )

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
            approval_handler=_CliApprovalHandler() if args.approval_mode == "on-request" else None,
            stream=args.stream != "off",
            event_sink=_stream_sink(args.stream, debug_level),
            workspace_mode=args.workspace_mode,
            approval_mode=args.approval_mode,
            sandbox_mode=args.sandbox_mode,
        )
        cancel_token = CancelToken()
        try:
            with _sigint_cancel(cancel_token):
                state = kernel.run(
                    args.task,
                    workspace=args.workspace,
                    run_id=args.run_id,
                    output_dir=args.output_dir,
                    cancel_token=cancel_token,
                    workspace_mode=args.workspace_mode,
                    approval_mode=args.approval_mode,
                    sandbox_mode=args.sandbox_mode,
                )
        except RunCancelled:
            print("run cancelled: sigint")
            return 130
        if args.stream == "jsonl":
            if state.cancelled:
                return 130
            return 1 if state.failed else 0
        if args.stream == "text" and state.final_output:
            print()
        print(f"run_id: {state.run_id}")
        print(f"output_dir: {state.output_dir}")
        print(f"status: {'cancelled' if state.cancelled else 'failed' if state.failed else 'completed'}")
        if state.cancelled:
            print(f"cancellation: {state.cancel_reason or 'cancelled'}")
            return 130
        if state.failed:
            print(f"failure: {state.failure_reason}")
            return 1
        if state.final_output and args.stream != "text":
            print(state.final_output)
        return 0

    if args.command == "replay":
        print(replay_run(args.run_path), end="")
        return 0

    if args.command == "inspect":
        print(render_run_inspection(load_run_record(args.run_path)), end="")
        return 0

    if args.command == "eval":
        try:
            debug_level = _debug_level(args.debug)
        except ValueError as exc:
            print(f"debug error: {exc}")
            return 2
        output_dir = args.output_dir or default_eval_output_dir(args.suite_path)
        cancel_token = CancelToken()
        try:
            with _sigint_cancel(cancel_token):
                eval_run = run_eval_suite(
                    args.suite_path,
                    output_dir=output_dir,
                    model_factory=lambda task: _model_for(args.provider, task),
                    profile=ApexCoderProfile(),
                    tools=default_tools(),
                    policy=default_policy(),
                    stream=args.stream != "off",
                    event_sink=_stream_sink(args.stream, debug_level),
                    cancel_token=cancel_token,
                    workspace_mode=args.workspace_mode,
                    approval_mode=args.approval_mode,
                    sandbox_mode=args.sandbox_mode,
                )
        except RunCancelled:
            print("eval cancelled: sigint")
            return 130
        except (OSError, ValueError, ProviderError) as exc:
            print(f"eval error: {exc}")
            return 1
        report = render_eval_report(eval_run)
        print(report, end="")
        return 0 if all(result.success for result in eval_run.results) else 1

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


class _CliApprovalHandler:
    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution:
        del state
        print(f"approval requested: {request.action_kind} {request.tool_name}", file=sys.stderr)
        if request.command:
            print(f"command: {request.command}", file=sys.stderr)
        print(f"reason/risk: {request.risk}", file=sys.stderr)
        raw = input("Approve? [y]es once, [r]un, [n]o: ").strip().lower()
        if raw in {"y", "yes"}:
            return ApprovalResolution(request.approval_id, "approved", scope="once", reason="cli_approved_once")
        if raw in {"r", "run"}:
            return ApprovalResolution(request.approval_id, "approved", scope="run", reason="cli_approved_run")
        return ApprovalResolution(request.approval_id, "denied", reason="cli_denied")


@contextmanager
def _sigint_cancel(token: CancelToken) -> Iterator[None]:
    previous = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum, frame):
        del signum, frame
        already_cancelled = token.cancelled
        token.signal_count += 1
        token.cancel("sigint", escalate=already_cancelled)

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


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

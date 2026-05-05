"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agentd import __version__
from agentd.config import VariantSpec
from agentd.eval_runner import (
    check_eval_comparison_thresholds,
    check_eval_thresholds,
    default_eval_output_dir,
    render_eval_comparison,
    render_eval_report,
    run_eval_comparison,
    run_eval_suite,
)
from agentd.events import ConsoleTextSink, JsonlStreamSink, debug_level_from_env
from agentd.kernel import Kernel
from agentd.models import ProviderError
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.providers.factory import ProviderSpec, provider_for
from agentd.replay import replay_run
from agentd.run_control import CancelToken, RunCancelled
from agentd.run_graph import fork_run
from agentd.run_record import load_run_record, render_run_inspection
from agentd.runtime import create_runtime_server
from agentd.state import ApprovalRequest, ApprovalResolution, RunState
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
    run_parser.add_argument("--sandbox-mode", choices=["none", "container", "native", "worktree"], default="none")
    run_parser.add_argument("--reasoning-json", help="JSON object passed as the provider's top-level reasoning parameter.")
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

    fork_parser = subparsers.add_parser("fork", help="Create fork metadata from a recorded run event.")
    fork_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")
    fork_parser.add_argument("--at", required=True, help="Event id or sequence to fork from.")
    fork_parser.add_argument("--output-dir", type=Path)

    serve_parser = subparsers.add_parser("serve", help="Serve live and recorded runs over HTTP.")
    serve_parser.add_argument("--workspace", default=".")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--run-root", type=Path)
    serve_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    serve_parser.add_argument("--model")
    serve_parser.add_argument("--reasoning-json", help="JSON object passed as the provider's top-level reasoning parameter.")
    serve_parser.add_argument("--stream", action="store_true", help="Stream model deltas through the runtime event stream.")
    serve_parser.add_argument(
        "--debug",
        type=int,
        help="SSE event verbosity. Defaults to TINYAGENT_DEBUG or 0.",
    )
    serve_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="current")
    serve_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    serve_parser.add_argument("--sandbox-mode", choices=["none", "container", "native", "worktree"], default="none")

    eval_parser = subparsers.add_parser("eval", help="Run a local eval suite.")
    eval_parser.add_argument("suite_path", type=Path, help="Directory containing eval cases.")
    eval_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    eval_parser.add_argument("--reasoning-json", help="JSON object passed as the provider's top-level reasoning parameter.")
    eval_parser.add_argument("--output-dir", type=Path)
    eval_parser.add_argument("--thresholds", type=Path)
    eval_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="current")
    eval_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    eval_parser.add_argument("--sandbox-mode", choices=["none", "container", "native", "worktree"], default="none")
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
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "eval" and argv[1] == "compare":
        return _main_eval_compare(argv[2:])

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
            model = _model_for(args.provider, args.task, reasoning_json=args.reasoning_json)
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
        except (OSError, ValueError) as exc:
            print(f"run error: {exc}")
            return 1
        if args.stream == "jsonl":
            if state.cancelled:
                return 130
            return 1 if state.failed else 0
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

    if args.command == "fork":
        try:
            path = fork_run(args.run_path, args.at, output_dir=args.output_dir)
        except (OSError, ValueError) as exc:
            print(f"fork error: {exc}")
            return 1
        print(f"fork_dir: {path}")
        return 0

    if args.command == "serve":
        try:
            debug_level = _debug_level(args.debug)
            server = create_runtime_server(
                Path(args.workspace),
                host=args.host,
                port=args.port,
                run_root=args.run_root,
                provider=args.provider,
                model_name=args.model,
                reasoning=_parse_reasoning_json(args.reasoning_json),
                stream=args.stream,
                debug_level=debug_level,
                workspace_mode=args.workspace_mode,
                approval_mode=args.approval_mode,
                sandbox_mode=args.sandbox_mode,
            )
        except (ProviderError, ValueError) as exc:
            print(f"serve error: {exc}")
            return 1
        print(f"serving tinyagent runtime on http://{args.host}:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
        finally:
            server.server_close()
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
                    model_factory=lambda task: _model_for(args.provider, task, reasoning_json=args.reasoning_json),
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
        threshold_failures = check_eval_thresholds(eval_run, args.thresholds) if args.thresholds else []
        for failure in threshold_failures:
            print(f"threshold failed: {failure}")
        return 0 if all(result.success for result in eval_run.results) and not threshold_failures else 1

    parser.error(f"unknown command '{args.command}'")
    return 2


def _main_eval_compare(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agentctl eval compare", description="Compare named eval variants.")
    parser.add_argument("suite_path", type=Path, help="Directory containing eval cases.")
    parser.add_argument("--variant", action="append", required=True, help="NAME or NAME=config.toml.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--thresholds", type=Path)
    args = parser.parse_args(argv)
    cancel_token = CancelToken()
    try:
        variants = [VariantSpec.parse(value) for value in args.variant]
        output_dir = args.output_dir or _default_eval_compare_output_dir(args.suite_path)
        with _sigint_cancel(cancel_token):
            comparison = run_eval_comparison(
                args.suite_path,
                output_dir=output_dir,
                variants=variants,
                model_factory=lambda config, task: _model_for(config.provider, task, model_name=config.model),
                profile_factory=lambda config: ApexCoderProfile(visible_tool_names=config.visible_tools or None),
                tools_factory=lambda _config: default_tools(),
                policy_factory=lambda _config: default_policy(),
                cancel_token=cancel_token,
            )
    except RunCancelled:
        print("eval compare cancelled: sigint")
        return 130
    except (OSError, ValueError, ProviderError) as exc:
        print(f"eval compare error: {exc}")
        return 1
    print(render_eval_comparison(comparison), end="")
    threshold_failures = check_eval_comparison_thresholds(comparison, args.thresholds) if args.thresholds else []
    for failure in threshold_failures:
        print(f"threshold failed: {failure}")
    failed_variants = [run.variant_name for run in comparison.variants if any(not result.success for result in run.results)]
    if cancel_token.cancelled:
        return 130 if cancel_token.reason == "sigint" else 1
    return 0 if not failed_variants and not threshold_failures and not cancel_token.cancelled else 1


def _default_eval_compare_output_dir(suite_path: Path) -> Path:
    default_dir = default_eval_output_dir(suite_path)
    return default_dir.with_name(f"{default_dir.name}-compare")


def _model_for(provider: str, task: str, *, model_name: str | None = None, reasoning_json: str | None = None):
    return provider_for(
        ProviderSpec(kind=provider, model=model_name, reasoning=_parse_reasoning_json(reasoning_json)),
        task,
        env=os.environ,
    )  # type: ignore[arg-type]


def _parse_reasoning_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"--reasoning-json must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError("--reasoning-json must be a JSON object.")
    return parsed


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


if __name__ == "__main__":
    raise SystemExit(main())

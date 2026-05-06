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
from uuid import uuid4

from tinyagent import __version__
from tinyagent.app.product import ProductHome, WorkspaceStore, render_doctor
from tinyagent.app.server import create_product_runtime_server
from tinyagent.core.config import VariantSpec
from tinyagent.core.events import ConsoleTextSink, JsonlStreamSink, debug_level_from_env
from tinyagent.core.ids import validate_run_id
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import ProviderError
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.providers.factory import ProviderSpec, provider_for
from tinyagent.core.run_control import CancelToken, RunCancelled
from tinyagent.core.state import ApprovalRequest, ApprovalResolution, Message, RunState
from tinyagent.core.tools import default_tools
from tinyagent.evals.runner import (
    check_eval_comparison_thresholds,
    check_eval_thresholds,
    default_eval_output_dir,
    render_eval_comparison,
    render_eval_report,
    run_eval_comparison,
    run_eval_suite,
)
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.replay import replay_run
from tinyagent.runtime.run_graph import fork_run
from tinyagent.runtime.run_record import load_run_record, render_run_inspection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tinyagent",
        description="Control the tinyagent product.",
    )
    parser.add_argument("--version", action="version", version=f"tinyagent {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="Run an agent task.")
    run_parser.add_argument("task", help="Task for the agent.")
    run_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    run_parser.add_argument("--workspace", default=".")
    run_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="auto")
    run_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    run_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")
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

    init_parser = subparsers.add_parser("init", help="Register the current folder as a tinyagent workspace.")
    init_parser.add_argument("--workspace", default=".")
    init_parser.add_argument("--name")
    init_parser.add_argument("--trust", action="store_true")
    init_parser.add_argument("--project-config", action="store_true")

    config_parser = subparsers.add_parser("config", help="Inspect tinyagent product configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_subparsers.add_parser("path", help="Print the active config.toml path.")

    doctor_parser = subparsers.add_parser("doctor", help="Check local tinyagent setup.")
    doctor_parser.add_argument("--workspace", default=".")
    doctor_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    doctor_parser.add_argument("--port", type=int, default=8765)

    workspaces_parser = subparsers.add_parser("workspaces", help="Manage registered workspaces.")
    workspaces_subparsers = workspaces_parser.add_subparsers(dest="workspaces_command")
    workspaces_subparsers.add_parser("list", help="List registered workspaces.")
    show_parser = workspaces_subparsers.add_parser("show", help="Show a registered workspace.")
    show_parser.add_argument("workspace_id")
    remove_parser = workspaces_subparsers.add_parser("remove", help="Remove a workspace from the registry.")
    remove_parser.add_argument("workspace_id")

    conversations_parser = subparsers.add_parser("conversations", help="Manage conversations in the current workspace.")
    conversations_parser.add_argument("--workspace", default=".")
    conversations_subparsers = conversations_parser.add_subparsers(dest="conversations_command")
    conversations_subparsers.add_parser("list", help="List conversations.")
    conversation_show = conversations_subparsers.add_parser("show", help="Show a conversation.")
    conversation_show.add_argument("conversation_id")
    conversation_archive = conversations_subparsers.add_parser("archive", help="Archive a conversation.")
    conversation_archive.add_argument("conversation_id")

    replay_parser = subparsers.add_parser("replay", help="Replay a recorded agent run.")
    replay_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a recorded agent run.")
    inspect_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")

    fork_parser = subparsers.add_parser("fork", help="Create fork metadata from a recorded run event.")
    fork_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")
    fork_parser.add_argument("--at", required=True, help="Event id or sequence to fork from.")
    fork_parser.add_argument("--output-dir", type=Path)

    serve_parser = subparsers.add_parser("serve", help="Serve live and recorded runs over HTTP.")
    serve_parser.add_argument("--workspace", help="Register an initial workspace before serving.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
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
    serve_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")

    eval_parser = subparsers.add_parser("eval", help="Run a local eval suite.")
    eval_parser.add_argument("suite_path", type=Path, help="Directory containing eval cases.")
    eval_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    eval_parser.add_argument("--reasoning-json", help="JSON object passed as the provider's top-level reasoning parameter.")
    eval_parser.add_argument("--output-dir", type=Path)
    eval_parser.add_argument("--thresholds", type=Path)
    eval_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="current")
    eval_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    eval_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")
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

    if args.command == "config":
        if args.config_command == "path":
            home = ProductHome.from_env()
            try:
                home.ensure()
            except OSError as exc:
                print(f"config error: {exc}")
                return 1
            print(home.config_path)
            return 0
        parser.error("config requires a subcommand")

    if args.command == "doctor":
        report, ok = render_doctor(
            ProductHome.from_env(),
            workspace=Path(args.workspace),
            provider=args.provider,
            port=args.port,
        )
        print(report, end="")
        return 0 if ok else 1

    if args.command == "init":
        home = ProductHome.from_env()
        try:
            record = WorkspaceStore(home).register(
                Path(args.workspace),
                name=args.name,
                trust="trusted" if args.trust else "untrusted",
            )
            if args.project_config:
                project_config = Path(record.root) / ".tinyagent" / "config.toml"
                project_config.parent.mkdir(parents=True, exist_ok=True)
                if not project_config.exists():
                    project_config.write_text("version = 1\n")
        except (OSError, ValueError) as exc:
            print(f"init error: {exc}")
            return 1
        print("registered workspace")
        print(f"  name: {record.name}")
        print(f"  id: {record.workspace_id}")
        print(f"  root: {record.root}")
        return 0

    if args.command == "workspaces":
        store = WorkspaceStore(ProductHome.from_env())
        if args.workspaces_command == "list":
            rows = store.list()
            if not rows:
                print("No workspaces registered.")
                return 0
            for record in rows:
                print(f"{record.workspace_id}\t{record.name}\t{record.root}")
            return 0
        if args.workspaces_command == "show":
            try:
                print(json.dumps(store.load(args.workspace_id).to_json_dict(), indent=2, sort_keys=True))
            except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
                print(f"workspaces error: {exc}")
                return 1
            return 0
        if args.workspaces_command == "remove":
            try:
                removed = store.remove(args.workspace_id)
            except ValueError as exc:
                print(f"workspaces error: {exc}")
                return 1
            print(f"removed: {str(removed).lower()}")
            return 0
        parser.error("workspaces requires a subcommand")

    if args.command == "conversations":
        home = ProductHome.from_env()
        try:
            record = WorkspaceStore(home).register(Path(args.workspace), trust="untrusted")
            store = ConversationStore(home.workspaces_dir / record.workspace_id / "conversations")
            if args.conversations_command == "list":
                rows = store.list(workspace=Path(record.root))
                if not rows:
                    print("No conversations.")
                    return 0
                for conversation in rows:
                    print(f"{conversation['conversation_id']}\t{conversation['status']}\t{conversation['turn_count']}\t{conversation['title']}")
                return 0
            if args.conversations_command == "show":
                conversation = store.load(args.conversation_id)
                payload = {
                    "conversation": conversation.to_json_dict(),
                    "turns": store.turns(args.conversation_id),
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.conversations_command == "archive":
                archived = store.archive(args.conversation_id)
                print(f"archived: {archived.conversation_id}")
                return 0
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            print(f"conversations error: {exc}")
            return 1
        parser.error("conversations requires a subcommand")

    product_workspace_record = None
    try:
        if not (args.command in {"replay", "inspect"} and _is_existing_path(args.run_path)):
            home = ProductHome.from_env()
            home.ensure()
            store = WorkspaceStore(home)
            if args.command == "run" and args.run_id is not None and args.output_dir is None:
                validate_run_id(args.run_id)
            if args.command == "run" or (args.command == "serve" and args.workspace):
                product_workspace_record = store.register(Path(args.workspace), trust="untrusted")
                if not _has_cli_option(argv, "--provider") and product_workspace_record.default_provider:
                    args.provider = product_workspace_record.default_provider
                args.workspace = product_workspace_record.root
                args.conversation_root = home.workspaces_dir / product_workspace_record.workspace_id / "conversations"
                if args.command == "run":
                    args.run_id = args.run_id or f"run_{uuid4().hex}"
                    if args.output_dir is None:
                        args.output_dir = store.run_root(product_workspace_record.workspace_id) / args.run_id
                    args.conversation_id = f"conv_{uuid4().hex}"
                    args.turn_id = f"turn_{uuid4().hex}"
            if args.command in {"replay", "inspect"} and _looks_like_run_id(args.run_path):
                args.run_path = store.find_run(str(args.run_path))
    except OSError as exc:
        print(f"product home error: {exc}")
        return 1
    except ValueError as exc:
        print(f"workspace error: {exc}")
        return 1

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
        state: RunState | None = None
        conversation_store: ConversationStore | None = None
        conversation_id = getattr(args, "conversation_id", None)
        turn_id = getattr(args, "turn_id", None)
        if conversation_id and turn_id:
            conversation_store = ConversationStore(args.conversation_root)
            conversation_store.ensure(workspace=Path(args.workspace), conversation_id=conversation_id, title=args.task[:80])
            conversation_store.record_turn_started(
                conversation_id=conversation_id,
                turn_id=turn_id,
                run_id=args.run_id,
                run_path=args.output_dir,
                workspace=Path(args.workspace),
                user_message=Message(role="user", content=args.task),
            )
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
        finally:
            if state is not None and conversation_store is not None and conversation_id and turn_id:
                conversation_store.record_run_turn(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    user_content=args.task,
                    state=state,
                )
        if args.stream == "jsonl":
            if state.cancelled:
                return 130
            return 1 if state.failed else 0
        print(f"run_id: {state.run_id}")
        if conversation_id:
            print(f"conversation_id: {conversation_id}")
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
            server = create_product_runtime_server(
                ProductHome.from_env(),
                host=args.host,
                port=args.port,
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
    parser = argparse.ArgumentParser(prog="tinyagent eval compare", description="Compare named eval variants.")
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


def _has_cli_option(argv: list[str], option: str) -> bool:
    return any(value == option or value.startswith(f"{option}=") for value in argv)


def _looks_like_run_id(path: Path) -> bool:
    value = str(path)
    candidate = Path(value).expanduser()
    return (
        not candidate.exists()
        and not candidate.is_absolute()
        and "/" not in value
        and "\\" not in value
        and not value.startswith(".")
    )


def _is_existing_path(path: Path) -> bool:
    return Path(path).expanduser().exists()


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

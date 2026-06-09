"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from tinyagent import __version__
from tinyagent.app.product import ProductHome, WorkspaceStore, render_doctor
from tinyagent.app.server import create_product_runtime_server
from tinyagent.app.update import DEFAULT_UPDATE_CHANNEL, UpdateManager, install_shims, render_update_status, version_payload
from tinyagent.core.auto_review import AutoReviewApprovalHandler
from tinyagent.core.events import ConsoleTextSink, Event, JsonlStreamSink, debug_level_from_env
from tinyagent.core.evolution import accept_candidate, create_prompt_experiment, create_skill_experiment, render_experiment_report
from tinyagent.core.ids import validate_run_id
from tinyagent.core.kernel import Kernel
from tinyagent.core.memory import MemoryStore
from tinyagent.core.models import ProviderError
from tinyagent.core.permission_profiles import PERMISSION_PROFILE_NAMES, permission_profile_for
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import profile_for
from tinyagent.core.providers.factory import DEFAULT_PROVIDER_REGISTRY, ProviderSpec, provider_for
from tinyagent.core.resources import ResourceLoader, ResourceLoaderConfig
from tinyagent.core.run_control import CancelToken, RunCancelled
from tinyagent.core.skills.drafts import draft_from_run, eval_draft, install_draft, list_drafts, reject_draft, show_draft
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
from tinyagent.evals.variants import VariantSpec
from tinyagent.extensions.workspace_snapshot import create_workspace_snapshot, restore_workspace_snapshot
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
    install_parser = subparsers.add_parser("install", help="Install a standalone alpha payload into the product home.")
    install_parser.add_argument("--manifest", required=True, help="Manifest URL or local manifest path.")
    install_parser.add_argument("--channel", default=DEFAULT_UPDATE_CHANNEL)
    install_parser.add_argument("--bin-dir", type=Path, default=Path("~/.local/bin"))
    install_parser.add_argument("--json", action="store_true")

    version_parser = subparsers.add_parser("version", help="Print product version and install metadata.")
    version_parser.add_argument("--json", action="store_true")

    update_parser = subparsers.add_parser("update", help="Check, apply, and rollback standalone tinyagent updates.")
    update_subparsers = update_parser.add_subparsers(dest="update_command")
    update_status = update_subparsers.add_parser("status", help="Show last update state.")
    update_status.add_argument("--json", action="store_true")
    update_check = update_subparsers.add_parser("check", help="Check the alpha release channel for an update.")
    update_check.add_argument("--manifest", help="Manifest URL or local manifest path.")
    update_check.add_argument("--channel", default=DEFAULT_UPDATE_CHANNEL)
    update_check.add_argument("--json", action="store_true")
    update_apply = update_subparsers.add_parser("apply", help="Apply a verified standalone update.")
    update_apply.add_argument("--manifest", help="Manifest URL or local manifest path.")
    update_apply.add_argument("--channel", default=DEFAULT_UPDATE_CHANNEL)
    update_apply.add_argument("--json", action="store_true")
    update_apply.add_argument("--force-managed", action="store_true", help=argparse.SUPPRESS)
    update_rollback = update_subparsers.add_parser("rollback", help="Switch back to the previously active version.")
    update_rollback.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run", help="Run an agent task.")
    run_parser.add_argument("task", help="Task for the agent.")
    run_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    run_parser.add_argument("--model")
    run_parser.add_argument("--workspace", default=".")
    run_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="auto")
    run_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    run_parser.add_argument("--session-mode", choices=["normal", "plan"], default="normal")
    run_parser.add_argument("--approvals-reviewer", choices=["user", "auto_review"], default="user")
    run_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")
    run_parser.add_argument("--permission-profile", choices=PERMISSION_PROFILE_NAMES)
    run_parser.add_argument("--profile", help="Profile to run, e.g. tiny-coder or tiny-pi.")
    run_parser.add_argument("--memory", action="store_true", help="Enable explicit file-backed memory context.")
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
    run_parser.add_argument("--output-format", choices=["text", "json"], default="text", help="Render the final run summary.")

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
    doctor_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
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

    snapshot_parser = subparsers.add_parser("snapshot", help="Create or restore opt-in workspace snapshots.")
    snapshot_subparsers = snapshot_parser.add_subparsers(dest="snapshot_command")
    snapshot_create = snapshot_subparsers.add_parser("create", help="Create a workspace snapshot for explicit paths.")
    snapshot_create.add_argument("paths", nargs="+")
    snapshot_create.add_argument("--workspace", default=".")
    snapshot_create.add_argument("--snapshot-root", type=Path)
    snapshot_create.add_argument("--label", default="manual")
    snapshot_create.add_argument("--json", action="store_true")
    snapshot_restore = snapshot_subparsers.add_parser("restore", help="Restore a workspace snapshot manifest.")
    snapshot_restore.add_argument("manifest", type=Path)
    snapshot_restore.add_argument("--workspace", default=".")
    snapshot_restore.add_argument("--json", action="store_true")

    serve_parser = subparsers.add_parser("serve", help="Serve live and recorded runs over HTTP.")
    serve_parser.add_argument("--workspace", help="Register an initial workspace before serving.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
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
    serve_parser.add_argument("--session-mode", choices=["normal", "plan"], default="normal")
    serve_parser.add_argument("--approvals-reviewer", choices=["user", "auto_review"], default="user")
    serve_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")
    serve_parser.add_argument("--permission-profile", choices=PERMISSION_PROFILE_NAMES)
    serve_parser.add_argument("--profile", default="tiny-coder", help="Default runtime profile.")
    serve_parser.add_argument("--memory", action="store_true", help="Enable explicit file-backed memory context.")
    serve_parser.add_argument("--print-json", action="store_true", help="Print machine-readable server metadata before serving.")

    tui_parser = subparsers.add_parser("tui", help="Launch the Bun/OpenTUI terminal client.")
    tui_parser.add_argument("task", nargs="*", help="Optional task to start after the TUI connects.")
    tui_parser.add_argument("--server", help="Connect to an existing tinyagent server.")
    tui_parser.add_argument("--workspace", default=".")
    tui_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    tui_parser.add_argument("--model")
    tui_parser.add_argument("--profile")
    tui_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="on-request")

    eval_parser = subparsers.add_parser("eval", help="Run a local eval suite.")
    eval_parser.add_argument("suite_path", type=Path, help="Directory containing eval cases.")
    eval_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    eval_parser.add_argument("--model")
    eval_parser.add_argument("--reasoning-json", help="JSON object passed as the provider's top-level reasoning parameter.")
    eval_parser.add_argument("--output-dir", type=Path)
    eval_parser.add_argument("--thresholds", type=Path)
    eval_parser.add_argument("--workspace-mode", choices=["auto", "worktree", "current"], default="current")
    eval_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    eval_parser.add_argument("--session-mode", choices=["normal", "plan"], default="normal")
    eval_parser.add_argument("--approvals-reviewer", choices=["user", "auto_review"], default="user")
    eval_parser.add_argument("--sandbox-mode", choices=["none", "container", "native"], default="none")
    eval_parser.add_argument("--permission-profile", choices=PERMISSION_PROFILE_NAMES)
    eval_parser.add_argument("--profile", default="tiny-coder", help="Profile to run, e.g. tiny-coder or tiny-pi.")
    eval_parser.add_argument("--memory", action="store_true", help="Enable explicit file-backed memory context.")
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

    skills_parser = subparsers.add_parser("skills", help="Manage reviewable skill drafts.")
    skills_parser.add_argument("--workspace", default=".")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    draft_parser = skills_subparsers.add_parser("draft-from-run", help="Create a reviewable skill draft from a completed run.")
    draft_parser.add_argument("run_path", type=Path)
    draft_parser.add_argument("--debug-artifacts", action="store_true")
    skills_subparsers.add_parser("list-drafts", help="List skill drafts.")
    show_draft_parser = skills_subparsers.add_parser("show-draft", help="Show a skill draft SKILL.md.")
    show_draft_parser.add_argument("draft_id")
    eval_draft_parser = skills_subparsers.add_parser("eval-draft", help="Run a baseline-vs-draft eval comparison.")
    eval_draft_parser.add_argument("draft_id")
    eval_draft_parser.add_argument("--suite", required=True, type=Path)
    eval_draft_parser.add_argument("--output-dir", type=Path)
    eval_draft_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    eval_draft_parser.add_argument("--profile", default="tiny-coder")
    install_draft_parser = skills_subparsers.add_parser("install-draft", help="Install a reviewed draft into project skills.")
    install_draft_parser.add_argument("draft_id")
    install_draft_parser.add_argument("--replace", action="store_true")
    reject_draft_parser = skills_subparsers.add_parser("reject-draft", help="Move a draft to the rejected archive.")
    reject_draft_parser.add_argument("draft_id")

    memory_parser = subparsers.add_parser("memory", help="Read and write explicit memory files.")
    memory_parser.add_argument("--workspace", default=".")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command")
    memory_read = memory_subparsers.add_parser("read", help="Read a memory file.")
    memory_read.add_argument("name")
    memory_append = memory_subparsers.add_parser("append", help="Append text to a memory file.")
    memory_append.add_argument("name")
    memory_append.add_argument("text")
    memory_open = memory_subparsers.add_parser("open", help="Print the path to a memory file.")
    memory_open.add_argument("name")

    evolve_parser = subparsers.add_parser("evolve", help="Create out-of-tree evolution experiments.")
    evolve_parser.add_argument("--workspace", default=".")
    evolve_subparsers = evolve_parser.add_subparsers(dest="evolve_command")
    evolve_skill = evolve_subparsers.add_parser("skill", help="Scaffold a skill evolution experiment.")
    evolve_skill.add_argument("skill_id")
    evolve_skill.add_argument("--suite", required=True, type=Path)
    evolve_prompt = evolve_subparsers.add_parser("prompt", help="Scaffold a prompt evolution experiment.")
    evolve_prompt.add_argument("prompt_id")
    evolve_prompt.add_argument("--suite", required=True, type=Path)
    evolve_report = evolve_subparsers.add_parser("report", help="Show an evolution report.")
    evolve_report.add_argument("experiment_id")
    evolve_accept = evolve_subparsers.add_parser("accept", help="Accept a reviewed candidate.")
    evolve_accept.add_argument("candidate_id")

    agent_parser = subparsers.add_parser("agent", help="Run machine-readable agent transports.")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command")
    stdio_parser = agent_subparsers.add_parser("stdio", help="Serve a JSON-RPC session over stdin/stdout.")
    stdio_parser.add_argument("--workspace", default=".")
    stdio_parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    stdio_parser.add_argument("--model")
    stdio_parser.add_argument("--profile", default="tiny-coder")
    stdio_parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="yolo")
    stdio_parser.add_argument("--session-mode", choices=["normal", "plan"], default="normal")
    stdio_parser.add_argument("--protocol", choices=["tinyagent", "acp"], default="tinyagent")

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "eval" and argv[1] == "compare":
        return _main_eval_compare(argv[2:])

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        argv = ["tui"]
        args = parser.parse_args(argv)

    product_config: dict[str, Any] = {}
    if args.command in {"agent", "eval", "run", "serve", "tui"}:
        try:
            config_home, product_config = _load_product_config()
            _apply_config_defaults(args, argv, product_config)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"config error: {exc}")
            return 1

    if args.command == "install":
        home = ProductHome.from_env()
        manager = UpdateManager(home, current_version="0.0.0", install_kind="standalone")
        try:
            status = manager.apply(channel=args.channel, manifest_source=args.manifest, force_managed=True)
            shims = install_shims(home, args.bin_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"install error: {exc}")
            return 1
        payload = {"status": status.to_json_dict(), "shims": [str(path) for path in shims]}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"installed tinyagent {status.active_version or status.latest_version}")
            for path in shims:
                print(f"shim: {path}")
        return 0

    if args.command == "version":
        home = ProductHome.from_env()
        payload = version_payload(home)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"tinyagent {payload['version']}")
            print(f"channel: {payload['channel']}")
            print(f"install_kind: {payload['install_kind']}")
            print(f"home: {payload['home']}")
        return 0

    if args.command == "update":
        manager = UpdateManager(ProductHome.from_env())
        try:
            if args.update_command == "status":
                status = manager.status()
            elif args.update_command == "check":
                status = manager.check(channel=args.channel, manifest_source=args.manifest)
            elif args.update_command == "apply":
                status = manager.apply(channel=args.channel, manifest_source=args.manifest, force_managed=args.force_managed)
            elif args.update_command == "rollback":
                status = manager.rollback()
            else:
                parser.error("update requires a subcommand")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"update error: {exc}")
            return 1
        if getattr(args, "json", False):
            print(json.dumps(status.to_json_dict(), sort_keys=True))
        else:
            print(render_update_status(status), end="")
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
        doctor_home = ProductHome.from_env()
        try:
            doctor_home.ensure()
            product_config = doctor_home.load_config()
            _apply_config_defaults(args, argv, product_config)
        except OSError:
            product_config = {}
        except (ValueError, json.JSONDecodeError):
            product_config = {}
        report, ok = render_doctor(
            doctor_home,
            workspace=Path(args.workspace),
            provider=args.provider,
            port=args.port,
            env=_provider_env_for_config(product_config),
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
                    print(
                        f"{conversation['conversation_id']}\t{conversation['status']}\t{conversation['turn_count']}\t{conversation['title']}"
                    )
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

    if args.command == "snapshot":
        try:
            if args.snapshot_command == "create":
                workspace = Path(args.workspace).expanduser().resolve()
                snapshot_root = args.snapshot_root or workspace / ".tinyagent" / "snapshots" / f"snapshot-{uuid4().hex[:12]}"
                result = create_workspace_snapshot(workspace, snapshot_root, args.paths, label=args.label)
                payload = result.to_json_dict()
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(f"snapshot_manifest: {result.manifest_path}")
                    print(f"paths: {len(result.paths)}")
                return 0
            if args.snapshot_command == "restore":
                result = restore_workspace_snapshot(Path(args.workspace).expanduser().resolve(), args.manifest)
                payload = result.to_json_dict()
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(f"restored: {len(result.restored)}")
                    print(f"deleted: {len(result.deleted)}")
                return 0
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            print(f"snapshot error: {exc}")
            return 1
        parser.error("snapshot requires a subcommand")

    product_workspace_record = None
    try:
        if not (args.command in {"replay", "inspect"} and _is_existing_path(args.run_path)):
            home = ProductHome.from_env()
            home.ensure()
            store = WorkspaceStore(home)
            if args.command == "run" and args.run_id is not None and args.output_dir is None:
                validate_run_id(args.run_id)
            if args.command == "run" or (args.command == "serve" and args.workspace) or (args.command == "tui" and not args.server):
                product_workspace_record = store.register(Path(args.workspace), trust="untrusted")
                config_provider = _config_provider(product_config)
                if (
                    not _has_cli_option(argv, "--provider")
                    and product_workspace_record.default_provider
                    and (product_workspace_record.default_provider != "fake" or not config_provider)
                ):
                    args.provider = product_workspace_record.default_provider
                config_profile = _config_default(product_config, "profile")
                if (
                    args.command in {"run", "tui"}
                    and not _has_cli_option(argv, "--profile")
                    and product_workspace_record.default_profile
                    and (product_workspace_record.default_profile != "tiny-coder" or not config_profile)
                ):
                    args.profile = product_workspace_record.default_profile
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
            model = _model_for(
                args.provider,
                args.task,
                model_name=args.model,
                reasoning_json=args.reasoning_json,
                product_config=product_config,
            )
        except ProviderError as exc:
            print(f"provider error: {exc}")
            return 1
        try:
            profile = profile_for(args.profile)
        except ValueError as exc:
            print(f"run error: {exc}")
            return 1
        (
            workspace_mode,
            approval_mode,
            sandbox_mode,
            policy,
            permission_profile,
            enforce_policy_in_yolo,
            deny_yolo_approvals,
        ) = _security_settings(args, argv)
        kernel = Kernel(
            model=model,
            profile=profile,
            tools=default_tools(),
            policy=policy,
            resources=ResourceLoader(ResourceLoaderConfig(memory_enabled=args.memory)).load(
                Path(args.workspace),
                runtime_capabilities=profile.runtime_capabilities,
            ),
            approval_handler=_approval_handler_for(approval_mode, args.approvals_reviewer, model),
            stream=args.stream != "off",
            event_sink=_stream_sink(args.stream, debug_level, output_format=args.output_format),
            workspace_mode=workspace_mode,
            approval_mode=approval_mode,
            session_mode=args.session_mode,
            sandbox_mode=sandbox_mode,
            permission_profile=permission_profile,
            enforce_policy_in_yolo=enforce_policy_in_yolo,
            deny_yolo_approvals=deny_yolo_approvals,
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
                    workspace_mode=workspace_mode,
                    approval_mode=approval_mode,
                    session_mode=args.session_mode,
                    sandbox_mode=sandbox_mode,
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
        status = "cancelled" if state.cancelled else "failed" if state.failed else "completed"
        if args.output_format == "json":
            print(
                json.dumps(
                    {
                        "run_id": state.run_id,
                        "conversation_id": conversation_id or "",
                        "output_dir": str(state.output_dir),
                        "status": status,
                        "final_output": state.final_output,
                        "usage": _usage_summary(state),
                        "failure": state.failure_reason if state.failed else "",
                        "cancel_reason": state.cancel_reason if state.cancelled else "",
                    },
                    sort_keys=True,
                )
            )
            if state.cancelled:
                return 130
            return 1 if state.failed else 0
        print(f"run_id: {state.run_id}")
        if conversation_id:
            print(f"conversation_id: {conversation_id}")
        print(f"output_dir: {state.output_dir}")
        print(f"status: {status}")
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
            workspace_mode, approval_mode, sandbox_mode, _policy, permission_profile, _enforce_policy_in_yolo, _deny_yolo_approvals = (
                _security_settings(args, argv)
            )
            server = create_product_runtime_server(
                config_home,
                host=args.host,
                port=args.port,
                provider=args.provider,
                model_name=args.model,
                reasoning=(
                    _parse_reasoning_json(args.reasoning_json)
                    if args.reasoning_json is not None
                    else _config_reasoning(product_config)
                ),
                model_env=_provider_env_for_config(product_config),
                stream=args.stream,
                debug_level=debug_level,
                workspace_mode=workspace_mode,
                approval_mode=approval_mode,
                session_mode=args.session_mode,
                approvals_reviewer=args.approvals_reviewer,
                sandbox_mode=sandbox_mode,
                permission_profile=permission_profile,
                profile=args.profile,
                profile_override=_has_cli_option(argv, "--profile"),
                memory_enabled=args.memory,
            )
        except (ProviderError, ValueError) as exc:
            print(f"serve error: {exc}")
            return 1
        url = f"http://{args.host}:{server.server_port}"
        if args.print_json:
            print(json.dumps({"host": args.host, "port": server.server_port, "url": url}), flush=True)
        else:
            print(f"serving tinyagent runtime on {url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
        finally:
            server.server_close()
        return 0

    if args.command == "tui":
        return _run_tui_launcher(
            server=args.server,
            workspace=args.workspace,
            provider=args.provider,
            model=args.model,
            profile=args.profile,
            approval_mode=args.approval_mode,
            task=" ".join(args.task).strip(),
        )

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
                try:
                    profile = profile_for(args.profile)
                except ValueError as exc:
                    print(f"eval error: {exc}")
                    return 1
                workspace_mode, approval_mode, sandbox_mode, policy, permission_profile, enforce_policy_in_yolo, deny_yolo_approvals = (
                    _security_settings(args, argv)
                )
                eval_run = run_eval_suite(
                    args.suite_path,
                    output_dir=output_dir,
                    model_factory=lambda task: _model_for(
                        args.provider,
                        task,
                        model_name=args.model,
                        reasoning_json=args.reasoning_json,
                        product_config=product_config,
                    ),
                    profile=profile,
                    tools=default_tools(),
                    policy=policy,
                    resources=ResourceLoader(ResourceLoaderConfig(memory_enabled=args.memory)).load(
                        args.suite_path,
                        runtime_capabilities=profile.runtime_capabilities,
                    ),
                    stream=args.stream != "off",
                    event_sink=_stream_sink(args.stream, debug_level),
                    cancel_token=cancel_token,
                    workspace_mode=workspace_mode,
                    approval_mode=approval_mode,
                    session_mode=args.session_mode,
                    approvals_reviewer=args.approvals_reviewer,
                    sandbox_mode=sandbox_mode,
                    permission_profile=permission_profile,
                    enforce_policy_in_yolo=enforce_policy_in_yolo,
                    deny_yolo_approvals=deny_yolo_approvals,
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

    if args.command == "skills":
        workspace = Path(args.workspace).expanduser().resolve()
        try:
            if args.skills_command == "draft-from-run":
                draft = draft_from_run(args.run_path, workspace=workspace, debug_artifacts=args.debug_artifacts)
                print(f"created skill draft: {draft.draft_id}")
                print(draft.path)
                return 0
            if args.skills_command == "list-drafts":
                for draft in list_drafts(workspace=workspace):
                    print(f"{draft.draft_id}\t{draft.name}\t{draft.source_run_id}\t{draft.status}")
                return 0
            if args.skills_command == "show-draft":
                print(show_draft(args.draft_id, workspace=workspace), end="")
                return 0
            if args.skills_command == "eval-draft":
                profile = profile_for(args.profile)
                output_dir = args.output_dir or workspace / ".tinyagent" / "evolution" / "experiments" / f"draft-{args.draft_id}-eval"
                comparison = eval_draft(
                    args.draft_id,
                    workspace=workspace,
                    suite_path=args.suite,
                    output_dir=output_dir,
                    model_factory=lambda task: _model_for(args.provider, task, product_config=product_config),
                    profile=profile,
                    tools=default_tools(),
                    policy=default_policy(),
                )
                print(render_eval_comparison(comparison), end="")
                return 0
            if args.skills_command == "install-draft":
                path = install_draft(args.draft_id, workspace=workspace, replace=args.replace)
                print(f"installed skill: {path}")
                return 0
            if args.skills_command == "reject-draft":
                path = reject_draft(args.draft_id, workspace=workspace)
                print(f"rejected skill draft: {path}")
                return 0
        except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
            print(f"skills error: {exc}")
            return 1
        parser.error("skills subcommand required")

    if args.command == "memory":
        store = MemoryStore(Path(args.workspace))
        try:
            if args.memory_command == "read":
                print(store.read(args.name).content, end="")
                return 0
            if args.memory_command == "append":
                item = store.append(args.name, args.text)
                print(item.path)
                return 0
            if args.memory_command == "open":
                item = store.ensure(args.name)
                print(item.path)
                return 0
        except (OSError, ValueError) as exc:
            print(f"memory error: {exc}")
            return 1
        parser.error("memory subcommand required")

    if args.command == "agent":
        if args.agent_command == "stdio":
            return _main_agent_stdio(args, product_config)
        parser.error("agent subcommand required")

    if args.command == "evolve":
        workspace = Path(args.workspace).expanduser().resolve()
        try:
            if args.evolve_command == "skill":
                experiment = create_skill_experiment(workspace=workspace, skill_id=args.skill_id, suite_path=args.suite)
                print(f"created evolution experiment: {experiment.experiment_id}")
                print(experiment.path)
                return 0
            if args.evolve_command == "prompt":
                experiment = create_prompt_experiment(workspace=workspace, prompt_id=args.prompt_id, suite_path=args.suite)
                print(f"created evolution experiment: {experiment.experiment_id}")
                print(experiment.path)
                return 0
            if args.evolve_command == "report":
                print(render_experiment_report(workspace=workspace, experiment_id=args.experiment_id), end="")
                return 0
            if args.evolve_command == "accept":
                path = accept_candidate(workspace=workspace, candidate_id=args.candidate_id)
                print(f"accepted candidate: {path}")
                return 0
        except (OSError, KeyError, ValueError, FileExistsError, FileNotFoundError) as exc:
            print(f"evolve error: {exc}")
            return 1
        parser.error("evolve subcommand required")

    parser.error(f"unknown command '{args.command}'")
    return 2


class _JsonRpcEventSink:
    def __init__(self, *, protocol: str) -> None:
        self.protocol = protocol

    def emit(self, event: Event) -> None:
        _write_jsonrpc(
            {
                "jsonrpc": "2.0",
                "method": "session.event",
                "params": {
                    "protocol": self.protocol,
                    "event": event.to_json_dict(),
                },
            }
        )


def _main_agent_stdio(args: argparse.Namespace, product_config: dict[str, Any] | None = None) -> int:
    session_id = f"session_{uuid4().hex}"
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_jsonrpc(_jsonrpc_error(None, -32700, f"parse error: {exc.msg}"))
            continue
        response = _handle_agent_stdio_request(request, args, session_id, product_config or {})
        _write_jsonrpc(response)
    return 0


def _handle_agent_stdio_request(
    request: dict[str, object],
    args: argparse.Namespace,
    session_id: str,
    product_config: dict[str, Any] | None = None,
) -> dict[str, object]:
    request_id = request.get("id")
    method = str(request.get("method") or "")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if method == "session.start":
        return _jsonrpc_result(
            request_id,
            {
                "session_id": session_id,
                "protocol": args.protocol,
                "capabilities": {
                    "prompt": True,
                    "cancel": True,
                    "approval_resolve": True,
                    "event_notifications": True,
                },
            },
        )
    if method == "session.cancel":
        return _jsonrpc_result(request_id, {"cancelled": False, "reason": "stdio prototype runs prompts synchronously"})
    if method == "approval.resolve":
        return _jsonrpc_result(request_id, {"resolved": False, "reason": "no pending approval in stdio prototype"})
    if method != "session.prompt":
        return _jsonrpc_error(request_id, -32601, f"method not found: {method}")
    task = str(params.get("task") or params.get("prompt") or "").strip()
    if not task:
        return _jsonrpc_error(request_id, -32602, "session.prompt requires params.task or params.prompt")
    try:
        model = _model_for(args.provider, task, model_name=args.model, reasoning_json=None, product_config=product_config or {})
        profile = profile_for(args.profile)
        workspace = Path(args.workspace).expanduser().resolve()
        run_id = str(params.get("run_id") or f"run_stdio_{uuid4().hex}")
        output_dir = workspace / ".tinyagent" / "runs" / run_id
        kernel = Kernel(
            model=model,
            profile=profile,
            tools=default_tools(),
            policy=default_policy(),
            resources=ResourceLoader(ResourceLoaderConfig(memory_enabled=False)).load(
                workspace,
                runtime_capabilities=profile.runtime_capabilities,
            ),
            approval_handler=None,
            stream=True,
            event_sink=_JsonRpcEventSink(protocol=args.protocol),
            workspace_mode="current",
            approval_mode=args.approval_mode,
            session_mode=args.session_mode,
        )
        state = kernel.run(task, workspace=workspace, run_id=run_id, output_dir=output_dir)
    except (OSError, ValueError, ProviderError) as exc:
        return _jsonrpc_error(request_id, -32000, str(exc))
    status = "cancelled" if state.cancelled else "failed" if state.failed else "completed"
    return _jsonrpc_result(
        request_id,
        {
            "session_id": session_id,
            "run_id": state.run_id,
            "status": status,
            "output_dir": str(state.output_dir),
            "final_output": state.final_output,
        },
    )


def _jsonrpc_result(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _usage_summary(state: RunState) -> dict[str, int]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    latency_ms = 0
    usage_events = 0
    for event in state.events:
        if event.type != "model.usage":
            continue
        usage_events += 1
        data = event.data
        input_value = int(data.get("input_tokens") or data.get("prompt_tokens") or 0)
        output_value = int(data.get("output_tokens") or data.get("completion_tokens") or 0)
        input_tokens += input_value
        output_tokens += output_value
        total_tokens += int(data.get("total_tokens") or input_value + output_value)
        latency_ms += int(data.get("latency_ms") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model_calls": usage_events or state.model_call_count,
        "latency_ms": latency_ms,
    }


def _write_jsonrpc(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def main_tui(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(prog="tinyagent-tui", description="Launch the tinyagent terminal UI.")
    parser.add_argument("task", nargs="*", help="Optional task to start after the TUI connects.")
    parser.add_argument("--server", help="Connect to an existing tinyagent server.")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--provider", choices=DEFAULT_PROVIDER_REGISTRY.kinds(), default="fake")
    parser.add_argument("--model")
    parser.add_argument("--profile")
    parser.add_argument("--approval-mode", choices=["never", "on-request", "yolo"], default="on-request")
    args = parser.parse_args(argv)
    return _run_tui_launcher(
        server=args.server,
        workspace=args.workspace,
        provider=args.provider,
        model=args.model,
        profile=args.profile,
        approval_mode=args.approval_mode,
        task=" ".join(args.task).strip(),
    )


def _run_tui_launcher(
    *,
    server: str | None,
    workspace: str,
    provider: str,
    model: str | None,
    profile: str | None,
    approval_mode: str,
    task: str = "",
) -> int:
    bun = shutil.which("bun")
    if bun is None:
        print("tui error: Bun is required to run the OpenTUI client. Install Bun, then retry `tinyagent tui`.")
        return 1
    source_tui_root = Path(__file__).resolve().parents[1] / "tui"
    packaged_tui_root = Path(__file__).resolve().parent / "tui"
    if source_tui_root.exists():
        tui_root = source_tui_root
        entrypoint = tui_root / "src" / "main.ts"
    else:
        tui_root = packaged_tui_root
        entrypoint = tui_root / "dist" / "main.js"
        if not entrypoint.exists():
            entrypoint = tui_root / "src" / "main.ts"
    if not entrypoint.exists():
        print(f"tui error: TUI package not found at {tui_root}")
        return 1
    cmd = [bun, str(entrypoint.relative_to(tui_root))]
    if server:
        cmd.extend(["--server", server])
    else:
        resolved_workspace = str(Path(workspace).expanduser().resolve())
        cmd.extend(["--workspace", resolved_workspace, "--provider", provider])
    if model:
        cmd.extend(["--model", model])
    if profile:
        cmd.extend(["--profile", profile])
    if approval_mode:
        cmd.extend(["--approval-mode", approval_mode])
    if task:
        cmd.append(task)
    try:
        return subprocess.run(cmd, cwd=tui_root, check=False).returncode
    except OSError as exc:
        print(f"tui error: {exc}")
        return 1


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
                profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
                tools_factory=lambda _config: default_tools(),
                policy_factory=lambda _config: default_policy(),
                resources_factory=lambda _config, profile: ResourceLoader().load(
                    args.suite_path,
                    runtime_capabilities=profile.runtime_capabilities,
                ),
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


def _load_product_config() -> tuple[ProductHome, dict[str, Any]]:
    home = ProductHome.from_env()
    home.ensure()
    return home, home.load_config()


def _apply_config_defaults(args: argparse.Namespace, argv: list[str], config: dict[str, Any]) -> None:
    if hasattr(args, "provider") and not _has_cli_option(argv, "--provider"):
        provider = _config_provider(config)
        if provider:
            args.provider = provider
    defaults = {
        "approval_mode": "approval-mode",
        "approvals_reviewer": "approvals-reviewer",
        "permission_profile": "permission-profile",
        "profile": "profile",
        "sandbox_mode": "sandbox-mode",
        "session_mode": "session-mode",
        "workspace_mode": "workspace-mode",
    }
    for attr, flag in defaults.items():
        if hasattr(args, attr) and not _has_cli_option(argv, f"--{flag}"):
            value = _config_default(config, attr)
            if value:
                setattr(args, attr, value)
    if hasattr(args, "memory") and not _has_cli_option(argv, "--memory"):
        memory_enabled = _config_bool(_config_table(config, "defaults"), "memory")
        if memory_enabled is not None:
            args.memory = memory_enabled


def _config_provider(config: dict[str, Any]) -> str | None:
    return _config_str(_config_table(config, "model"), "provider") or _config_default(config, "provider")


def _config_default(config: dict[str, Any], key: str) -> str | None:
    return _config_str(_config_table(config, "defaults"), key)


def _provider_env_for_config(config: dict[str, Any]) -> dict[str, str]:
    values = dict(os.environ)
    model = _config_table(config, "model")
    aliases = {
        "api_key": "TINYAGENT_MODEL_API_KEY",
        "base_url": "TINYAGENT_MODEL_BASE_URL",
        "context_window": "TINYAGENT_MODEL_CONTEXT_WINDOW",
        "max_output_tokens": "TINYAGENT_MODEL_MAX_OUTPUT_TOKENS",
        "parallel_tool_calls": "TINYAGENT_MODEL_PARALLEL_TOOL_CALLS",
        "prompt_cache_key": "TINYAGENT_MODEL_PROMPT_CACHE_KEY",
        "timeout_seconds": "TINYAGENT_MODEL_TIMEOUT_SECONDS",
    }
    model_name = _config_str(model, "name") or _config_str(model, "model")
    if model_name and "TINYAGENT_MODEL_NAME" not in values:
        values["TINYAGENT_MODEL_NAME"] = model_name
    for key, env_name in aliases.items():
        if env_name not in values and key in model:
            values[env_name] = _config_env_value(model[key], f"model.{key}")
    if "TINYAGENT_MODEL_EXTRA_BODY_JSON" not in values:
        extra_body_json = _config_str(model, "extra_body_json")
        if extra_body_json:
            values["TINYAGENT_MODEL_EXTRA_BODY_JSON"] = extra_body_json
        elif "extra_body" in model:
            extra_body = model["extra_body"]
            if not isinstance(extra_body, dict):
                raise ValueError("model.extra_body must be a TOML table")
            values["TINYAGENT_MODEL_EXTRA_BODY_JSON"] = json.dumps(extra_body, sort_keys=True)
    if "TINYAGENT_MODEL_REASONING_JSON" not in values:
        reasoning = _config_reasoning(config)
        if reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(reasoning, sort_keys=True)
    return values


def _config_reasoning(config: dict[str, Any]) -> dict[str, Any] | None:
    model = _config_table(config, "model")
    result: dict[str, Any] = {}
    if "reasoning_json" in model:
        raw = _config_str(model, "reasoning_json")
        if raw:
            return _parse_reasoning_json(raw)
    if "reasoning" in model:
        reasoning = model["reasoning"]
        if not isinstance(reasoning, dict):
            raise ValueError("model.reasoning must be a TOML table")
        result.update(reasoning)
    effort = _config_str(model, "reasoning_effort")
    if effort:
        result.setdefault("effort", effort)
    if "reasoning_budget_tokens" in model:
        budget = model["reasoning_budget_tokens"]
        if not isinstance(budget, int):
            raise ValueError("model.reasoning_budget_tokens must be an integer")
        result.setdefault("budget_tokens", budget)
    return result or None


def _config_table(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"[{key}] must be a TOML table")
    return value


def _config_str(table: dict[str, Any], key: str) -> str | None:
    if key not in table:
        return None
    value = table[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip() or None


def _config_bool(table: dict[str, Any], key: str) -> bool | None:
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _config_env_value(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        return str(value)
    raise ValueError(f"{key} must be a string, number, or boolean")


def _security_settings(args: argparse.Namespace, argv: list[str]):
    permission_profile = permission_profile_for(getattr(args, "permission_profile", None))
    if permission_profile is None:
        return args.workspace_mode, args.approval_mode, args.sandbox_mode, default_policy(), None, False, False
    workspace_mode = args.workspace_mode if _has_cli_option(argv, "--workspace-mode") else permission_profile.workspace_mode
    approval_mode = args.approval_mode if _has_cli_option(argv, "--approval-mode") else permission_profile.approval_mode
    sandbox_mode = args.sandbox_mode if _has_cli_option(argv, "--sandbox-mode") else permission_profile.sandbox_mode
    return (
        workspace_mode,
        approval_mode,
        sandbox_mode,
        permission_profile.policy(),
        permission_profile.name,
        permission_profile.enforce_policy_in_yolo,
        permission_profile.deny_yolo_approvals,
    )


def _has_cli_option(argv: list[str], option: str) -> bool:
    return any(value == option or value.startswith(f"{option}=") for value in argv)


def _looks_like_run_id(path: Path) -> bool:
    value = str(path)
    candidate = Path(value).expanduser()
    return not candidate.exists() and not candidate.is_absolute() and "/" not in value and "\\" not in value and not value.startswith(".")


def _is_existing_path(path: Path) -> bool:
    return Path(path).expanduser().exists()


def _model_for(
    provider: str,
    task: str,
    *,
    model_name: str | None = None,
    reasoning_json: str | None = None,
    product_config: dict[str, Any] | None = None,
):
    config = product_config or {}
    reasoning = _parse_reasoning_json(reasoning_json) if reasoning_json is not None else _config_reasoning(config)
    return provider_for(
        ProviderSpec(kind=provider, model=model_name, reasoning=reasoning),
        task,
        env=_provider_env_for_config(config),
    )  # type: ignore[arg-type]


def _approval_handler_for(approval_mode: str, approvals_reviewer: str, model):
    if approval_mode != "on-request":
        return None
    if approvals_reviewer == "auto_review":
        return AutoReviewApprovalHandler(model)
    return _CliApprovalHandler()


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


def _stream_sink(mode: str, debug_level: int, *, output_format: str = "text"):
    if mode == "text":
        return ConsoleTextSink(sys.stderr if output_format == "json" else sys.stdout)
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

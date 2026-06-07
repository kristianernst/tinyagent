"""Product HTTP server built around the tinyagent.core runtime primitives."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from tinyagent.app.product import ProductHome, WorkspaceRecord, WorkspaceStore
from tinyagent.app.update import UpdateManager
from tinyagent.core.contracts import ModelProvider
from tinyagent.core.index import WorkspaceIndexManager
from tinyagent.core.models import ProviderError
from tinyagent.core.providers.factory import ProviderSpec, provider_for
from tinyagent.core.state import ApprovalMode, SessionMode
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode
from tinyagent.extensions.lsp import load_lsp_config
from tinyagent.extensions.mcp import load_mcp_config
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.protocol_v1 import V1_RUN_START_KEYS, error_response, health_response, openapi_spec, run_object
from tinyagent.runtime.server import (
    RunController,
    RuntimeConfig,
    RuntimeHandler,
    UnsupportedMediaType,
    _conversation_id_for_run,
    validate_approval_mode,
    validate_session_mode,
)
from tinyagent.runtime.workspace_surface import git_status_response, workspace_files_response


class ProductRuntimeController:
    def __init__(
        self,
        *,
        home: ProductHome,
        provider_factory: Callable[[str], ModelProvider],
        stream: bool = True,
        debug_level: int = 0,
        workspace_mode: WorkspaceMode = "current",
        approval_mode: ApprovalMode = "yolo",
        session_mode: SessionMode = "normal",
        approvals_reviewer: str = "user",
        sandbox_mode: SandboxModeInput = "none",
        permission_profile: str | None = None,
        profile: str = "tiny-coder",
        profile_override: bool = False,
        todo_memory_enabled: bool = False,
        memory_enabled: bool = False,
    ) -> None:
        home.ensure()
        self.home = home
        self.store = WorkspaceStore(home)
        self.provider_factory = provider_factory
        self.stream = stream
        self.debug_level = debug_level
        self.workspace_mode = workspace_mode
        self.approval_mode = approval_mode
        self.session_mode = session_mode
        self.approvals_reviewer = approvals_reviewer
        self.sandbox_mode = sandbox_mode
        self.permission_profile = permission_profile
        self.profile = profile
        self.profile_override = profile_override
        self.todo_memory_enabled = todo_memory_enabled
        self.memory_enabled = memory_enabled
        self._lock = threading.Lock()
        self._controllers: dict[str, RunController] = {}

    def workspaces(self) -> list[dict[str, Any]]:
        return [record.to_json_dict() for record in self.store.list()]

    def register_workspace(self, root: Path, *, name: str | None = None) -> dict[str, Any]:
        return self.store.register(root, name=name).to_json_dict()

    def update_status(self) -> dict[str, Any]:
        return UpdateManager(self.home).auto_check_if_configured().to_json_dict()

    def update_check(self, *, channel: str | None = None, manifest_source: str | None = None) -> dict[str, Any]:
        return UpdateManager(self.home).check(channel=channel, manifest_source=manifest_source).to_json_dict()

    def update_apply(self, *, channel: str | None = None, manifest_source: str | None = None) -> dict[str, Any]:
        return UpdateManager(self.home).apply(channel=channel, manifest_source=manifest_source).to_json_dict()

    def update_rollback(self) -> dict[str, Any]:
        return UpdateManager(self.home).rollback().to_json_dict()

    def controller_for_workspace(self, workspace_id: str) -> RunController:
        with self._lock:
            if workspace_id not in self._controllers:
                record = self.store.load(workspace_id)
                self._controllers[workspace_id] = self._new_controller(record)
            return self._controllers[workspace_id]

    def controller_for_run(self, run_id: str, *, workspace_id: str | None = None) -> RunController:
        if workspace_id:
            return self.controller_for_workspace(workspace_id)
        for record in self.store.list():
            controller = self.controller_for_workspace(record.workspace_id)
            if controller.run_exists(run_id):
                return controller
        raise FileNotFoundError(f"run not found in product home: {run_id}")

    def _new_controller(self, record: WorkspaceRecord) -> RunController:
        workspace_root = Path(record.root).expanduser().resolve()
        workspace_root_path = self.store.workspace_path(record.workspace_id)
        mcp_config = load_mcp_config(self.store.home.config_path, workspace_root / ".tinyagent" / "config.toml")
        lsp_config = load_lsp_config(self.store.home.config_path, workspace_root / ".tinyagent" / "config.toml")
        return RunController(
            RuntimeConfig(
                workspace=workspace_root,
                run_root=self.store.run_root(record.workspace_id),
                provider_factory=self.provider_factory,
                stream=self.stream,
                debug_level=self.debug_level,
                workspace_mode=self.workspace_mode,
                approval_mode=self.approval_mode,
                session_mode=self.session_mode,
                approvals_reviewer=self.approvals_reviewer,
                sandbox_mode=self.sandbox_mode,
                permission_profile=self.permission_profile,
                profile=self.profile if self.profile_override else record.default_profile,
                conversation_store=ConversationStore(workspace_root_path / "conversations"),
                workspace_index_manager=WorkspaceIndexManager.for_workspace_id(
                    record.workspace_id,
                    index_root=self.store.home.workspaces_dir / record.workspace_id / "search",
                ),
                mcp_config=mcp_config,
                lsp_config=lsp_config,
                todo_memory_enabled=self.todo_memory_enabled,
                memory_enabled=self.memory_enabled,
            )
        )


class ProductRuntimeHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], product: ProductRuntimeController) -> None:
        self.product = product
        super().__init__(server_address, ProductRuntimeHandler)


class ProductRuntimeHandler(RuntimeHandler):
    server: ProductRuntimeHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = _path_parts(parsed.path)
        if parts and parts[0] == "v1":
            self._v1_get(parts[1:], parsed)
            return
        try:
            if parts == ["api", "workspaces"]:
                self._json(HTTPStatus.OK, {"workspaces": self.server.product.workspaces()})
                return
            if parts == ["api", "runs"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, {"runs": controller.store.list_runs()})
                return
            if parts == ["api", "conversations"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                conversations = (
                    controller.config.conversation_store.list(workspace=controller.config.workspace)
                    if controller.config.conversation_store is not None
                    else []
                )
                self._json(HTTPStatus.OK, {"conversations": conversations})
                return
            if parts == ["api", "workspace", "files"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, workspace_files_response(controller.config.workspace))
                return
            if parts == ["api", "git", "status"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, git_status_response(controller.config.workspace))
                return
            if parts == ["api", "mcp", "servers"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, {"servers": controller.mcp_servers()})
                return
            if parts == ["api", "lsp", "servers"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, {"servers": controller.lsp_servers()})
                return
            if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "turns":
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                if controller.config.conversation_store is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "conversation store is not configured"})
                    return
                controller.config.conversation_store.load(parts[2])
                self._json(HTTPStatus.OK, {"conversation_id": parts[2], "turns": controller.config.conversation_store.turns(parts[2])})
                return
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                controller = self.server.product.controller_for_run(parts[2], workspace_id=_workspace_id(parsed.query))
                self._json(HTTPStatus.OK, controller.run_summary(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events.json":
                self._events_json(parts[2], parsed.query)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events":
                self._events(parts[2], parsed.query)
                return
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3:] == ["memory", "todo"]:
                controller = self.server.product.controller_for_run(parts[2], workspace_id=_workspace_id(parsed.query))
                self._json(HTTPStatus.OK, controller.todo_state(parts[2]))
                return
            if len(parts) >= 5 and parts[:2] == ["api", "runs"] and parts[3] == "artifacts":
                self._artifact(parts[2], "/".join(parts[4:]), workspace_id=_workspace_id(parsed.query))
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, ProviderError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = _path_parts(parsed.path)
        try:
            body = self._read_body()
        except UnsupportedMediaType as exc:
            if parts and parts[0] == "v1":
                self._v1_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", str(exc))
                return
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": str(exc)})
            return
        except json.JSONDecodeError as exc:
            if parts and parts[0] == "v1":
                self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", f"Invalid JSON body: {exc}")
                return
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON body: {exc}"})
            return
        if parts and parts[0] == "v1":
            self._v1_post(parts[1:], parsed, body)
            return
        try:
            if parts == ["api", "workspaces"]:
                root = str(body.get("path") or body.get("root") or "").strip()
                if not root:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "path is required"})
                    return
                name_value = body.get("name")
                name = str(name_value).strip() if name_value else None
                self._json(HTTPStatus.CREATED, {"workspace": self.server.product.register_workspace(Path(root), name=name)})
                return

            workspace_id = _require_workspace_id(str(body.get("workspace_id") or ""))
            controller = self.server.product.controller_for_workspace(workspace_id)
            if parts == ["api", "runs"]:
                task = str(body.get("task") or "")
                if not task:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "task is required"})
                    return
                self._json(
                    HTTPStatus.ACCEPTED,
                    controller.start_run(
                        task,
                        run_id=body.get("run_id"),
                        approval_mode=validate_approval_mode(body.get("approval_mode"), controller.config.approval_mode),
                        session_mode=validate_session_mode(body.get("session_mode"), controller.config.session_mode),
                        approvals_reviewer=str(body.get("approvals_reviewer") or controller.config.approvals_reviewer),
                        profile=str(body.get("profile") or controller.config.profile),
                    ),
                )
                return
            if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "turns":
                task = str(body.get("message") or body.get("task") or "")
                if not task:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "message is required"})
                    return
                payload = controller.start_conversation_turn(
                    parts[2],
                    task,
                    run_id=body.get("run_id"),
                    turn_id=body.get("turn_id"),
                    parent_turn_id=body.get("parent_turn_id"),
                    approval_mode=validate_approval_mode(body.get("approval_mode"), controller.config.approval_mode),
                    session_mode=validate_session_mode(body.get("session_mode"), controller.config.session_mode),
                    approvals_reviewer=str(body.get("approvals_reviewer") or controller.config.approvals_reviewer),
                    profile=str(body.get("profile") or controller.config.profile),
                )
                payload["events_url"] = f"/api/runs/{payload['run_id']}/events?workspace_id={workspace_id}"
                self._json(HTTPStatus.ACCEPTED, payload)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                ok = controller.cancel(parts[2], str(body.get("reason") or "server_cancelled"))
                self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"cancelled": ok})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "approve":
                approval_id = str(body.get("approval_id") or "")
                ok = controller.approvals.approve(
                    parts[2],
                    approval_id,
                    decision=str(body.get("decision") or "approved"),
                    scope=body.get("scope", "once"),
                    reason=body.get("reason") or "server_resolved",
                )
                self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"resolved": ok})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "fork":
                if "output_dir" in body:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "custom fork output_dir is not supported by the HTTP API"})
                    return
                self._json(HTTPStatus.CREATED, controller.fork(parts[2], str(body.get("at") or "")))
                return
            if parts == ["api", "mcp", "reload"]:
                self._json(HTTPStatus.OK, {"servers": controller.mcp_servers()})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, ProviderError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _controller_for_run(self, run_id: str, query: str) -> RunController:
        return self.server.product.controller_for_run(run_id, workspace_id=_workspace_id(query))

    def _v1_get(self, parts: list[str], parsed) -> None:
        try:
            if parts == ["health"]:
                self._json(HTTPStatus.OK, health_response())
                return
            if parts == ["openapi.json"]:
                self._json(HTTPStatus.OK, openapi_spec(product=True))
                return
            if parts in (["update"], ["update", "status"]):
                self._json(HTTPStatus.OK, self.server.product.update_status())
                return
            if parts == ["workspaces"]:
                self._json(HTTPStatus.OK, {"items": self.server.product.workspaces()})
                return
            if len(parts) == 2 and parts[0] == "workspaces":
                self._json(HTTPStatus.OK, {"workspace": self.server.product.store.load(parts[1]).to_json_dict()})
                return
            if len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "files":
                controller = self.server.product.controller_for_workspace(parts[1])
                self._json(HTTPStatus.OK, workspace_files_response(controller.config.workspace))
                return
            if len(parts) == 4 and parts[0] == "workspaces" and parts[2:] == ["git", "status"]:
                controller = self.server.product.controller_for_workspace(parts[1])
                self._json(HTTPStatus.OK, git_status_response(controller.config.workspace))
                return
            if parts == ["conversations"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                conversations = (
                    controller.config.conversation_store.list(workspace=controller.config.workspace)
                    if controller.config.conversation_store is not None
                    else []
                )
                self._json(HTTPStatus.OK, {"items": conversations})
                return
            if len(parts) == 3 and parts[0] == "conversations" and parts[2] == "turns":
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                if controller.config.conversation_store is None:
                    self._v1_error(HTTPStatus.NOT_FOUND, "conversation_store_missing", "conversation store is not configured")
                    return
                controller.config.conversation_store.load(parts[1])
                turns = controller.config.conversation_store.turns(parts[1])
                self._json(HTTPStatus.OK, {"conversation_id": parts[1], "items": turns, "turns": turns})
                return
            if parts == ["runs"]:
                workspace_id = _require_workspace_id(_workspace_id(parsed.query))
                controller = self.server.product.controller_for_workspace(workspace_id)
                self._json(HTTPStatus.OK, {"items": [run_object(run, workspace_id=workspace_id) for run in controller.store.list_runs()]})
                return
            if parts == ["skills", "drafts"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, controller.skill_drafts())
                return
            if len(parts) == 3 and parts[:2] == ["skills", "drafts"]:
                controller = self.server.product.controller_for_workspace(_require_workspace_id(_workspace_id(parsed.query)))
                self._json(HTTPStatus.OK, controller.show_skill_draft(parts[2]))
                return
            if len(parts) >= 2 and parts[0] == "runs":
                self._v1_run_get(parts[1], parts[2:], parsed.query)
                return
            if parts == ["extensions"]:
                workspace_id = _workspace_id(parsed.query)
                if workspace_id:
                    controller = self.server.product.controller_for_workspace(workspace_id)
                    self._json(
                        HTTPStatus.OK,
                        {
                            "items": [
                                {"name": "mcp", "servers": controller.mcp_servers()},
                                {"name": "lsp", "servers": controller.lsp_servers()},
                                {"name": "todo_memory", "enabled": controller.config.todo_memory_enabled},
                            ]
                        },
                    )
                    return
                self._json(HTTPStatus.OK, {"items": [{"name": "product_runtime", "enabled": True}]})
                return
            self._v1_error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint not found.")
        except FileNotFoundError as exc:
            self._v1_error(HTTPStatus.NOT_FOUND, _not_found_code(str(exc)), str(exc))
        except (OSError, ValueError, ProviderError) as exc:
            self._v1_error(HTTPStatus.BAD_REQUEST, _bad_request_code(str(exc)), str(exc))

    def _v1_run_get(self, run_id: str, tail: list[str], query: str) -> None:
        controller = self.server.product.controller_for_run(run_id, workspace_id=_workspace_id(query))
        workspace_id = _workspace_id(query) or _workspace_id_for_controller(self.server.product, controller)
        conversation_id = _conversation_id_for_run(controller, run_id)
        self._v1_run_get_shared(
            controller,
            run_id,
            tail,
            query,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
        )

    def _v1_post(self, parts: list[str], parsed, body: dict[str, Any]) -> None:
        try:
            if parts == ["workspaces"]:
                root = str(body.get("root") or body.get("path") or "").strip()
                if not root:
                    self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", "root is required")
                    return
                name_value = body.get("name")
                name = str(name_value).strip() if name_value else None
                self._json(HTTPStatus.CREATED, {"workspace": self.server.product.register_workspace(Path(root), name=name)})
                return
            if parts == ["update", "check"]:
                manifest_source = body.get("manifest_source") or body.get("manifest")
                self._json(
                    HTTPStatus.OK,
                    self.server.product.update_check(
                        channel=str(body.get("channel")) if body.get("channel") else None,
                        manifest_source=str(manifest_source) if manifest_source else None,
                    ),
                )
                return
            if parts == ["update", "apply"]:
                manifest_source = body.get("manifest_source") or body.get("manifest")
                self._json(
                    HTTPStatus.OK,
                    self.server.product.update_apply(
                        channel=str(body.get("channel")) if body.get("channel") else None,
                        manifest_source=str(manifest_source) if manifest_source else None,
                    ),
                )
                return
            if parts == ["update", "rollback"]:
                self._json(HTTPStatus.OK, self.server.product.update_rollback())
                return
            if parts == ["runs"]:
                unsupported = sorted(set(body) - V1_RUN_START_KEYS)
                if unsupported:
                    self._v1_error(
                        HTTPStatus.BAD_REQUEST,
                        "bad_request",
                        f"Unsupported run fields: {', '.join(unsupported)}",
                    )
                    return
                workspace_id = _require_workspace_id(str(body.get("workspace_id") or ""))
                task = str(body.get("task") or "").strip()
                if not task:
                    self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", "task is required")
                    return
                controller = self.server.product.controller_for_workspace(workspace_id)
                if body.get("conversation_id"):
                    payload = controller.start_conversation_turn(
                        str(body["conversation_id"]),
                        task,
                        run_id=body.get("run_id"),
                        turn_id=body.get("turn_id"),
                        parent_turn_id=body.get("parent_turn_id"),
                        approval_mode=validate_approval_mode(body.get("approval_mode"), controller.config.approval_mode),
                        session_mode=validate_session_mode(body.get("session_mode"), controller.config.session_mode),
                        approvals_reviewer=str(body.get("approvals_reviewer") or controller.config.approvals_reviewer),
                        profile=str(body.get("profile") or controller.config.profile),
                    )
                else:
                    payload = controller.start_run(
                        task,
                        run_id=body.get("run_id"),
                        approval_mode=validate_approval_mode(body.get("approval_mode"), controller.config.approval_mode),
                        session_mode=validate_session_mode(body.get("session_mode"), controller.config.session_mode),
                        approvals_reviewer=str(body.get("approvals_reviewer") or controller.config.approvals_reviewer),
                        profile=str(body.get("profile") or controller.config.profile),
                    )
                self._json(
                    HTTPStatus.ACCEPTED,
                    {
                        "run": run_object(payload, workspace_id=workspace_id),
                        "events_url": f"/v1/runs/{payload['run_id']}/events?workspace_id={workspace_id}",
                    },
                )
                return
            if parts == ["evals"]:
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_workspace(_require_workspace_id(workspace_id))
                self._json(
                    HTTPStatus.CREATED,
                    controller.eval_suite(
                        str(body.get("suite_path") or ""),
                        output_dir=str(body.get("output_dir")) if body.get("output_dir") else None,
                        profile=str(body.get("profile")) if body.get("profile") else None,
                        approval_mode=str(body.get("approval_mode")) if body.get("approval_mode") else None,
                        session_mode=str(body.get("session_mode")) if body.get("session_mode") else None,
                        approvals_reviewer=str(body.get("approvals_reviewer")) if body.get("approvals_reviewer") else None,
                    ),
                )
                return
            if parts == ["skills", "drafts"]:
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_workspace(_require_workspace_id(workspace_id))
                self._json(HTTPStatus.CREATED, controller.create_skill_draft(str(body.get("run_id") or "")))
                return
            if len(parts) == 4 and parts[:2] == ["skills", "drafts"] and parts[3] == "install":
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_workspace(_require_workspace_id(workspace_id))
                self._json(HTTPStatus.CREATED, controller.install_skill_draft(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["skills", "drafts"] and parts[3] == "reject":
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_workspace(_require_workspace_id(workspace_id))
                self._json(HTTPStatus.CREATED, controller.reject_skill_draft(parts[2]))
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "cancel":
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_run(parts[1], workspace_id=workspace_id)
                ok = controller.cancel(parts[1], str(body.get("reason") or "server_cancelled"))
                if not ok:
                    self._v1_error(HTTPStatus.NOT_FOUND, "run_not_active", f"Run is not active: {parts[1]}")
                    return
                self._json(HTTPStatus.OK, {"cancelled": True})
                return
            if len(parts) == 5 and parts[0] == "runs" and parts[2] == "approvals" and parts[4] == "resolve":
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_run(parts[1], workspace_id=workspace_id)
                ok = controller.approvals.approve(
                    parts[1],
                    parts[3],
                    decision=str(body.get("decision") or "approved"),
                    scope=body.get("scope", "once"),
                    reason=body.get("reason") or "server_resolved",
                )
                if not ok:
                    self._v1_error(HTTPStatus.NOT_FOUND, "approval_not_found", f"Approval not found: {parts[3]}")
                    return
                self._json(HTTPStatus.OK, {"resolved": True})
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "fork":
                if "output_dir" in body:
                    self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", "custom fork output_dir is not supported by the HTTP API")
                    return
                workspace_id = _workspace_id(parsed.query) or str(body.get("workspace_id") or "")
                controller = self.server.product.controller_for_run(parts[1], workspace_id=workspace_id)
                self._json(HTTPStatus.CREATED, controller.fork(parts[1], str(body.get("at") or "")))
                return
            self._v1_error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint not found.")
        except FileNotFoundError as exc:
            self._v1_error(HTTPStatus.NOT_FOUND, _not_found_code(str(exc)), str(exc))
        except (OSError, ValueError, ProviderError) as exc:
            self._v1_error(HTTPStatus.BAD_REQUEST, _bad_request_code(str(exc)), str(exc))

    def _v1_error(self, status: HTTPStatus, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self._json(status, error_response(code, message, details))


def create_product_runtime_server(
    home: ProductHome,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    provider: str = "fake",
    model_name: str | None = None,
    reasoning: dict[str, Any] | None = None,
    model_env: Mapping[str, str] | None = None,
    stream: bool = True,
    debug_level: int = 0,
    workspace_mode: WorkspaceMode = "current",
    approval_mode: ApprovalMode = "yolo",
    session_mode: SessionMode = "normal",
    approvals_reviewer: str = "user",
    sandbox_mode: SandboxModeInput = "none",
    permission_profile: str | None = None,
    profile: str = "tiny-coder",
    profile_override: bool = False,
    todo_memory_enabled: bool = False,
    memory_enabled: bool = False,
) -> ProductRuntimeHTTPServer:
    spec = ProviderSpec(kind=provider, model=model_name, reasoning=reasoning)  # type: ignore[arg-type]
    provider_for(spec, "provider validation", env=model_env)
    product = ProductRuntimeController(
        home=home,
        provider_factory=lambda task: provider_for(spec, task, env=model_env),
        stream=stream,
        debug_level=debug_level,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        session_mode=session_mode,
        approvals_reviewer=approvals_reviewer,
        sandbox_mode=sandbox_mode,
        permission_profile=permission_profile,
        profile=profile,
        profile_override=profile_override or profile != "tiny-coder",
        todo_memory_enabled=todo_memory_enabled,
        memory_enabled=memory_enabled,
    )
    return ProductRuntimeHTTPServer((host, port), product)


def _path_parts(path: str) -> list[str]:
    return [unquote(part) for part in path.split("/") if part]


def _workspace_id(query: str) -> str | None:
    values = parse_qs(query).get("workspace_id")
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _require_workspace_id(workspace_id: str | None) -> str:
    if not workspace_id:
        raise ValueError("workspace_id is required")
    return workspace_id


def _not_found_code(message: str) -> str:
    lowered = message.lower()
    if "workspace" in lowered:
        return "workspace_not_found"
    if "approval" in lowered:
        return "approval_not_found"
    if "artifact" in lowered:
        return "artifact_not_found"
    if "conversation" in lowered:
        return "conversation_not_found"
    if "run" in lowered:
        return "run_not_found"
    return "not_found"


def _bad_request_code(message: str) -> str:
    lowered = message.lower()
    if "already exists" in lowered:
        return "already_exists"
    if "provider" in lowered:
        return "provider_error"
    return "bad_request"


def _workspace_id_for_controller(product: ProductRuntimeController, controller: RunController) -> str:
    for record in product.store.list():
        if product.controller_for_workspace(record.workspace_id) is controller:
            return record.workspace_id
    return ""

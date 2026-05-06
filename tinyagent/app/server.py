"""Product HTTP server built around the tinyagent.core runtime primitives."""

from __future__ import annotations

import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from tinyagent.app.product import ProductHome, WorkspaceRecord, WorkspaceStore
from tinyagent.core.contracts import ModelProvider
from tinyagent.core.models import ProviderError
from tinyagent.core.providers.factory import ProviderSpec, provider_for
from tinyagent.core.state import ApprovalMode
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.server import RunController, RuntimeConfig, RuntimeHandler


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
        sandbox_mode: SandboxModeInput = "none",
    ) -> None:
        home.ensure()
        self.store = WorkspaceStore(home)
        self.provider_factory = provider_factory
        self.stream = stream
        self.debug_level = debug_level
        self.workspace_mode = workspace_mode
        self.approval_mode = approval_mode
        self.sandbox_mode = sandbox_mode
        self._lock = threading.Lock()
        self._controllers: dict[str, RunController] = {}

    def workspaces(self) -> list[dict[str, Any]]:
        return [record.to_json_dict() for record in self.store.list()]

    def register_workspace(self, root: Path, *, name: str | None = None) -> dict[str, Any]:
        return self.store.register(root, name=name).to_json_dict()

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
        return RunController(
            RuntimeConfig(
                workspace=workspace_root,
                run_root=self.store.run_root(record.workspace_id),
                provider_factory=self.provider_factory,
                stream=self.stream,
                debug_level=self.debug_level,
                workspace_mode=self.workspace_mode,
                approval_mode=self.approval_mode,
                sandbox_mode=self.sandbox_mode,
                conversation_store=ConversationStore(workspace_root_path / "conversations"),
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
        body = self._read_body()
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
                        approval_mode=str(body.get("approval_mode") or controller.config.approval_mode),
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
                    approval_mode=str(body.get("approval_mode") or controller.config.approval_mode),
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
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, ProviderError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _controller_for_run(self, run_id: str, query: str) -> RunController:
        return self.server.product.controller_for_run(run_id, workspace_id=_workspace_id(query))


def create_product_runtime_server(
    home: ProductHome,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    provider: str = "fake",
    model_name: str | None = None,
    reasoning: dict[str, Any] | None = None,
    stream: bool = True,
    debug_level: int = 0,
    workspace_mode: WorkspaceMode = "current",
    approval_mode: ApprovalMode = "yolo",
    sandbox_mode: SandboxModeInput = "none",
) -> ProductRuntimeHTTPServer:
    spec = ProviderSpec(kind=provider, model=model_name, reasoning=reasoning)  # type: ignore[arg-type]
    provider_for(spec, "provider validation")
    product = ProductRuntimeController(
        home=home,
        provider_factory=lambda task: provider_for(spec, task),
        stream=stream,
        debug_level=debug_level,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        sandbox_mode=sandbox_mode,
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


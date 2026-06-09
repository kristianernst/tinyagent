"""Product backend contract over run primitives."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from tinyagent.core.events import Event
from tinyagent.runtime.protocol_v1 import run_object
from tinyagent.runtime.server import RunController


@dataclass(frozen=True)
class RunRequest:
    task: str
    run_id: str | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    parent_turn_id: str | None = None
    approval_mode: str | None = None
    session_mode: str | None = None
    approvals_reviewer: str | None = None
    profile: str | None = None
    permission_profile: str | None = None


@dataclass(frozen=True)
class BackendRunHandle:
    run_id: str
    status: str
    events_url: str = ""


@dataclass(frozen=True)
class ArtifactInfo:
    path: str
    kind: str
    bytes: int
    safe_to_display: bool = True


class RunBackend(Protocol):
    def start_run(self, request: RunRequest) -> BackendRunHandle: ...

    def get_run(self, run_id: str) -> dict[str, object]: ...

    def events(self, run_id: str, after_seq: int = 0) -> Iterable[Event]: ...

    def cancel(self, run_id: str, reason: str = "cancelled") -> bool: ...

    def artifacts(self, run_id: str) -> list[ArtifactInfo]: ...

    def fetch_artifact(self, run_id: str, path: str) -> bytes: ...

    def pending_approvals(self, run_id: str) -> list[dict[str, object]]: ...

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        decision: str = "approved",
        scope: str | None = "once",
        reason: str = "backend_resolved",
    ) -> bool: ...


class LocalRunBackend:
    """RunBackend implementation backed by the in-process RunController."""

    def __init__(self, controller: RunController, *, workspace_id: str = "") -> None:
        self.controller = controller
        self.workspace_id = workspace_id

    def start_run(self, request: RunRequest) -> BackendRunHandle:
        if request.conversation_id:
            payload = self.controller.start_conversation_turn(
                request.conversation_id,
                request.task,
                run_id=request.run_id,
                turn_id=request.turn_id,
                parent_turn_id=request.parent_turn_id,
                approval_mode=request.approval_mode,
                session_mode=request.session_mode,
                approvals_reviewer=request.approvals_reviewer,
                permission_profile=request.permission_profile,
                profile=request.profile,
            )
        else:
            payload = self.controller.start_run(
                request.task,
                run_id=request.run_id,
                approval_mode=request.approval_mode,
                session_mode=request.session_mode,
                approvals_reviewer=request.approvals_reviewer,
                permission_profile=request.permission_profile,
                profile=request.profile,
            )
        run_id = str(payload["run_id"])
        return BackendRunHandle(
            run_id=run_id,
            status=str(payload.get("status") or "running"),
            events_url=f"/v1/runs/{run_id}/events",
        )

    def get_run(self, run_id: str) -> dict[str, object]:
        return run_object(self.controller.run_summary(run_id), workspace_id=self.workspace_id)

    def events(self, run_id: str, after_seq: int = 0) -> Iterable[Event]:
        return self.controller.events(run_id, after_seq=after_seq)

    def cancel(self, run_id: str, reason: str = "cancelled") -> bool:
        return self.controller.cancel(run_id, reason=reason)

    def artifacts(self, run_id: str) -> list[ArtifactInfo]:
        return [
            ArtifactInfo(
                path=str(item.get("path") or ""),
                kind=str(item.get("kind") or "artifact"),
                bytes=int(item.get("bytes") or 0),
                safe_to_display=bool(item.get("safe_to_display", True)),
            )
            for item in self.controller.artifacts(run_id)
        ]

    def fetch_artifact(self, run_id: str, path: str) -> bytes:
        return self.controller.public_artifact_path(run_id, path).read_bytes()

    def pending_approvals(self, run_id: str) -> list[dict[str, object]]:
        if not self.controller.run_exists(run_id):
            raise FileNotFoundError(f"run not found: {run_id}")
        return [approval for approval in self.controller.approvals.pending() if approval.get("run_id") == run_id]

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        decision: str = "approved",
        scope: str | None = "once",
        reason: str = "backend_resolved",
    ) -> bool:
        return self.controller.approvals.approve(run_id, approval_id, decision=decision, scope=scope, reason=reason)


class HTTPRunBackend:
    """RunBackend implementation for a v1 HTTP tinyagent server."""

    def __init__(self, base_url: str, *, workspace_id: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.timeout = timeout

    def start_run(self, request: RunRequest) -> BackendRunHandle:
        body = {
            "task": request.task,
            "run_id": request.run_id,
            "workspace_id": request.workspace_id or self.workspace_id,
            "conversation_id": request.conversation_id,
            "turn_id": request.turn_id,
            "parent_turn_id": request.parent_turn_id,
            "approval_mode": request.approval_mode,
            "session_mode": request.session_mode,
            "approvals_reviewer": request.approvals_reviewer,
            "permission_profile": request.permission_profile,
            "profile": request.profile,
        }
        payload = self._json("POST", "/v1/runs", {key: value for key, value in body.items() if value is not None})
        run = payload["run"]
        return BackendRunHandle(run_id=str(run["run_id"]), status=str(run["status"]), events_url=str(payload.get("events_url") or ""))

    def get_run(self, run_id: str) -> dict[str, object]:
        return self._json("GET", f"/v1/runs/{quote(run_id)}{self._query()}")["run"]

    def events(self, run_id: str, after_seq: int = 0) -> Iterable[Event]:
        query = self._query({"after_seq": str(after_seq)})
        payload = self._json("GET", f"/v1/runs/{quote(run_id)}/events.jsonl{query}")
        return [Event.from_json_dict(item) for item in payload["items"]]

    def cancel(self, run_id: str, reason: str = "cancelled") -> bool:
        try:
            payload = self._json("POST", f"/v1/runs/{quote(run_id)}/cancel{self._query()}", {"reason": reason})
        except FileNotFoundError:
            return False
        return bool(payload.get("cancelled"))

    def artifacts(self, run_id: str) -> list[ArtifactInfo]:
        payload = self._json("GET", f"/v1/runs/{quote(run_id)}/artifacts{self._query()}")
        return [
            ArtifactInfo(
                path=str(item.get("path") or ""),
                kind=str(item.get("kind") or "artifact"),
                bytes=int(item.get("bytes") or 0),
                safe_to_display=bool(item.get("safe_to_display", True)),
            )
            for item in payload["items"]
        ]

    def fetch_artifact(self, run_id: str, path: str) -> bytes:
        return self._request("GET", f"/v1/runs/{quote(run_id)}/artifacts/{quote(path, safe='')}{self._query()}")

    def pending_approvals(self, run_id: str) -> list[dict[str, object]]:
        return list(self._json("GET", f"/v1/runs/{quote(run_id)}/approvals{self._query()}")["items"])

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        decision: str = "approved",
        scope: str | None = "once",
        reason: str = "backend_resolved",
    ) -> bool:
        payload = self._json(
            "POST",
            f"/v1/runs/{quote(run_id)}/approvals/{quote(approval_id)}/resolve{self._query()}",
            {"decision": decision, "scope": scope, "reason": reason},
        )
        return bool(payload.get("resolved"))

    def _json(self, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        return json.loads(self._request(method, path, body).decode())

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            payload = exc.read().decode(errors="replace")
            if exc.code == 404:
                raise FileNotFoundError(payload) from exc
            if exc.code == 403:
                raise PermissionError(payload) from exc
            raise RuntimeError(payload) from exc

    def _query(self, extra: dict[str, str] | None = None) -> str:
        params = dict(extra or {})
        if self.workspace_id:
            params["workspace_id"] = self.workspace_id
        return f"?{urlencode(params)}" if params else ""

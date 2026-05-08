"""Shared v1 protocol response helpers."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1

V1_RUN_START_KEYS = frozenset(
    {
        "workspace_id",
        "task",
        "run_id",
        "approval_mode",
        "profile",
        "conversation_id",
        "turn_id",
        "parent_turn_id",
    }
)


def health_response(*, version: str = "0.1.0") -> dict[str, object]:
    return {"healthy": True, "version": version, "schema_version": SCHEMA_VERSION}


def error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": f"req_{uuid4().hex}",
        }
    }


def run_links(run_id: str, *, workspace_id: str | None = None) -> dict[str, str]:
    query = f"?workspace_id={workspace_id}" if workspace_id else ""
    return {
        "events": f"/v1/runs/{run_id}/events{query}",
        "artifacts": f"/v1/runs/{run_id}/artifacts{query}",
    }


def run_object(summary: dict[str, Any], *, workspace_id: str | None = None) -> dict[str, Any]:
    run_id = str(summary.get("run_id") or summary.get("id") or "")
    return {
        "id": run_id,
        "run_id": run_id,
        "workspace_id": workspace_id or summary.get("workspace_id") or "",
        "conversation_id": summary.get("conversation_id") or "",
        "turn_id": summary.get("turn_id") or "",
        "status": summary.get("status") or "unknown",
        "task": summary.get("task") or "",
        "created_at": summary.get("started_at") or summary.get("created_at") or "",
        "updated_at": summary.get("completed_at") or summary.get("updated_at") or "",
        "started_at": summary.get("started_at") or "",
        "completed_at": summary.get("completed_at"),
        "run_path": summary.get("run_path") or "",
        "model": summary.get("model") or summary.get("model_spec") or {},
        "profile": summary.get("profile") or "",
        "workspace_mode": summary.get("workspace_mode") or "",
        "approval_mode": summary.get("approval_mode") or "",
        "sandbox_mode": summary.get("sandbox_mode") or "",
        "event_count": summary.get("event_count") or 0,
        "artifact_count": summary.get("artifact_count") or 0,
        "links": run_links(run_id, workspace_id=workspace_id),
    }


def openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "tinyagent app protocol", "version": "0.1.0"},
        "paths": {
            "/v1/health": {"get": {"summary": "Health check", "responses": _response("Health")}},
            "/v1/workspaces": {
                "get": {"summary": "List workspaces", "responses": _response("WorkspaceList")},
                "post": {"summary": "Register workspace", "responses": _response("WorkspaceResponse")},
            },
            "/v1/runs": {
                "get": {"summary": "List runs", "responses": _response("RunList")},
                "post": {"summary": "Start run", "responses": _response("RunStartResponse", status="202")},
            },
            "/v1/runs/{run_id}": {"get": {"summary": "Get run", "responses": _response("RunResponse")}},
            "/v1/runs/{run_id}/events": {
                "get": {
                    "summary": "Stream run events",
                    "parameters": [_path_param("run_id"), _workspace_param(required=False), _after_seq_param()],
                    "responses": {
                        "200": {
                            "description": "SSE event stream",
                            "content": {
                                "text/event-stream": {
                                    "schema": {"type": "string"},
                                    "x-itemSchema": {"$ref": "#/components/schemas/Event"},
                                }
                            },
                        },
                        **_error_responses(),
                    },
                }
            },
            "/v1/runs/{run_id}/events.jsonl": {
                "get": {
                    "summary": "List run events after a sequence",
                    "parameters": [_path_param("run_id"), _workspace_param(required=False), _after_seq_param()],
                    "responses": _response("EventList"),
                }
            },
            "/v1/runs/{run_id}/artifacts": {
                "get": {
                    "summary": "List public run artifacts",
                    "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                    "responses": _response("ArtifactList"),
                }
            },
            "/v1/runs/{run_id}/artifacts/{path}": {
                "get": {
                    "summary": "Fetch public run artifact",
                    "parameters": [_path_param("run_id"), _path_param("path"), _workspace_param(required=False)],
                    "responses": {
                        "200": {"description": "Artifact bytes", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
                        **_error_responses(),
                    },
                }
            },
            "/v1/runs/{run_id}/approvals": {
                "get": {
                    "summary": "List pending run approvals",
                    "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                    "responses": _response("ApprovalList"),
                }
            },
            "/v1/runs/{run_id}/cancel": {
                "post": {
                    "summary": "Cancel active run",
                    "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                    "responses": _response("CancelResponse"),
                }
            },
            "/v1/runs/{run_id}/approvals/{approval_id}/resolve": {
                "post": {
                    "summary": "Resolve pending approval",
                    "parameters": [_path_param("run_id"), _path_param("approval_id"), _workspace_param(required=False)],
                    "responses": _response("ApprovalResolutionResponse"),
                }
            },
        },
        "components": {
            "schemas": {
                "Health": _object({"healthy": {"type": "boolean"}, "version": {"type": "string"}, "schema_version": {"type": "integer"}}),
                "Workspace": _object({"workspace_id": {"type": "string"}, "id": {"type": "string"}, "root": {"type": "string"}, "name": {"type": "string"}}),
                "WorkspaceList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Workspace"}}}),
                "WorkspaceResponse": _object({"workspace": {"$ref": "#/components/schemas/Workspace"}}),
                "Run": _object(
                    {
                        "id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "turn_id": {"type": "string"},
                        "status": {"type": "string"},
                        "task": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                        "started_at": {"type": "string"},
                        "completed_at": {"type": ["string", "null"]},
                        "run_path": {"type": "string"},
                        "model": {"type": "object"},
                        "profile": {"type": "string"},
                        "workspace_mode": {"type": "string"},
                        "approval_mode": {"type": "string"},
                        "sandbox_mode": {"type": "string"},
                        "event_count": {"type": "integer"},
                        "artifact_count": {"type": "integer"},
                        "links": {"type": "object", "additionalProperties": {"type": "string"}},
                    }
                ),
                "RunList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Run"}}}),
                "RunResponse": _object({"run": {"$ref": "#/components/schemas/Run"}}),
                "RunStartResponse": _object({"run": {"$ref": "#/components/schemas/Run"}, "events_url": {"type": "string"}}),
                "Event": _object(
                    {
                        "id": {"type": "string"},
                        "seq": {"type": "integer"},
                        "type": {"type": "string"},
                        "run_id": {"type": "string"},
                        "turn_id": {"type": ["string", "null"]},
                        "item_id": {"type": ["string", "null"]},
                        "parent_item_id": {"type": ["string", "null"]},
                        "source": {"type": "string"},
                        "visibility": {"type": "string"},
                        "durability": {"type": "string"},
                        "time": {"type": "string"},
                        "data": {"type": "object"},
                        "artifact_refs": {"type": "array", "items": {"type": "string"}},
                        "workspace_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                    }
                ),
                "EventList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Event"}}}),
                "Artifact": _object(
                    {
                        "path": {"type": "string"},
                        "kind": {"type": "string"},
                        "bytes": {"type": "integer"},
                        "created_at": {"type": ["string", "object"]},
                        "safe_to_display": {"type": "boolean"},
                    }
                ),
                "ArtifactList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Artifact"}}}),
                "Approval": _object(
                    {
                        "approval_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "turn_id": {"type": ["string", "null"]},
                        "step_id": {"type": ["string", "null"]},
                        "action_kind": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "cwd": {"type": "string"},
                        "args_preview": {"type": "string"},
                        "command": {"type": ["string", "null"]},
                        "risk": {"type": "string"},
                    }
                ),
                "ApprovalList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Approval"}}}),
                "ApprovalResolutionResponse": _object({"resolved": {"type": "boolean"}}),
                "CancelResponse": _object({"cancelled": {"type": "boolean"}}),
                "ErrorResponse": _object(
                    {
                        "error": _object(
                            {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "object"},
                                "request_id": {"type": "string"},
                            }
                        )
                    }
                ),
            }
        },
    }


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": True}


def _response(schema: str, *, status: str = "200") -> dict[str, Any]:
    return {
        status: {
            "description": schema,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
        },
        **_error_responses(),
    }


def _error_responses() -> dict[str, Any]:
    error = {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
    return {"400": error, "403": error, "404": error}


def _path_param(name: str) -> dict[str, Any]:
    return {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}


def _workspace_param(*, required: bool) -> dict[str, Any]:
    return {"name": "workspace_id", "in": "query", "required": required, "schema": {"type": "string"}}


def _after_seq_param() -> dict[str, Any]:
    return {"name": "after_seq", "in": "query", "schema": {"type": "integer"}}
